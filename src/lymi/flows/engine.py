"""Motor de workflows.

Ejecuta los pasos en orden, evalua sus condiciones, pide aprobacion antes de
cualquier efecto y reintenta solo lo que es seguro reintentar. Toda la corrida
queda en el ledger bajo el nombre del workflow, paso por paso.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from lymi.bench.runner import Recorder
from lymi.control import Detenido, Presupuesto, PresupuestoAgotado, verificar_parada
from lymi.ejecutor import Diario, Ejecutor, Perfil, cargar_perfil, raiz_diario
from lymi.flows import condition, template
from lymi.flows.aprobaciones import Politica, Solicitud, resolver_aprobacion
from lymi.flows.nodes import McpPool, PasoError, Recursos, destino_de, ejecutar, vista_previa
from lymi.flows.schema import InputSpec, McpIntegration, PcStep, WebStep, Workflow
from lymi.web import Buscador, Web, buscador_configurado
from lymi.ledger import Billing, Ledger
from lymi.privacidad import sanear_valor
from lymi.providers.base import LLMClient

Aprobador = Callable[..., bool | Awaitable[bool]]
"""Recibe el id del paso y una vista previa de lo que va a hacer, y decide."""


class EntradaError(ValueError):
    """Las entradas no cumplen lo que el workflow declara."""


def negar_todo(_paso: str, _vista: str) -> bool:
    """Aprobador por defecto: ningun efecto sale sin que alguien lo autorice."""
    return False


@dataclass(slots=True)
class EstadoPaso:
    id: str
    status: str
    """ok | omitido | rechazado | fallo"""
    detalle: str = ""
    intentos: int = 0
    duracion_ms: int = 0


@dataclass(slots=True)
class ResultadoFlujo:
    run_id: str
    ok: bool
    pasos: list[EstadoPaso]
    salidas: dict[str, Any] = field(default_factory=dict)
    detalle: str = ""


_VERDADEROS = frozenset({"true", "si", "sí", "1", "yes"})
_FALSOS = frozenset({"false", "no", "0"})


def _convertir(nombre: str, spec: InputSpec, valor: Any) -> Any:
    if spec.type == "string":
        if isinstance(valor, str):
            return valor
        raise EntradaError(f"{nombre}: se esperaba texto")

    if spec.type == "number":
        if isinstance(valor, (int, float)) and not isinstance(valor, bool):
            return valor
        if isinstance(valor, str):
            for convertir in (int, float):
                try:
                    return convertir(valor)
                except ValueError:
                    continue
        raise EntradaError(f"{nombre}: se esperaba un numero, llego {valor!r}")

    if spec.type == "boolean":
        if isinstance(valor, bool):
            return valor
        if isinstance(valor, str) and valor.strip().lower() in _VERDADEROS | _FALSOS:
            return valor.strip().lower() in _VERDADEROS
        raise EntradaError(f"{nombre}: se esperaba true o false, llego {valor!r}")

    if isinstance(valor, (dict, list)):
        return valor
    if isinstance(valor, str):
        try:
            datos = json.loads(valor)
        except json.JSONDecodeError as exc:
            raise EntradaError(f"{nombre}: JSON invalido") from exc
        if isinstance(datos, (dict, list)):
            return datos
    raise EntradaError(f"{nombre}: se esperaba un objeto JSON")


def preparar_inputs(flujo: Workflow, valores: Mapping[str, Any]) -> dict[str, Any]:
    """Valida y convierte las entradas contra lo declarado en el workflow."""
    desconocidas = sorted(set(valores) - set(flujo.inputs))
    if desconocidas:
        raise EntradaError(f"entradas desconocidas: {', '.join(desconocidas)}")

    listas: dict[str, Any] = {}
    for nombre, spec in flujo.inputs.items():
        if nombre in valores:
            listas[nombre] = _convertir(nombre, spec, valores[nombre])
        elif spec.default is not None:
            listas[nombre] = spec.default
        elif spec.required:
            raise EntradaError(f"falta la entrada requerida {nombre!r}")
        else:
            listas[nombre] = None
    return listas


def _ms(inicio: float) -> int:
    return int((time.perf_counter() - inicio) * 1000)


async def ejecutar_flujo(
    flujo: Workflow,
    inputs: Mapping[str, Any],
    *,
    ledger: Ledger,
    local: LLMClient | None = None,
    remote: LLMClient | None = None,
    aprobar: Aprobador = negar_todo,
    politica: Politica | None = None,
    tiempo_aprobacion: float | None = None,
    presupuesto: Presupuesto | None = None,
    protegidos: tuple[str, ...] = (),
    perfil: Perfil | None = None,
    web: Web | None = None,
    buscador: Buscador | None = None,
    entorno: Mapping[str, str] | None = None,
    http_client: httpx.AsyncClient | None = None,
    variante: str = "flow",
    espera: Callable[[float], Awaitable[Any]] = asyncio.sleep,
) -> ResultadoFlujo:
    """Corre el workflow completo y devuelve el estado de cada paso."""
    # Las entradas son texto ajeno (un correo, un webhook): se sanean antes de que
    # cualquier plantilla las lleve a un modelo.
    valores, _ = sanear_valor(preparar_inputs(flujo, inputs))
    entorno = dict(os.environ) if entorno is None else dict(entorno)
    contexto: dict[str, Any] = {"inputs": valores, "steps": {}}
    estados: list[EstadoPaso] = []

    if remote is not None:
        billing = remote.billing
    elif local is not None:
        billing = Billing.LOCAL
    else:
        billing = Billing.NONE

    servidores_mcp = {n: i for n, i in flujo.integrations.items() if isinstance(i, McpIntegration)}
    cliente_http = http_client or httpx.AsyncClient(follow_redirects=False)

    def salidas() -> dict[str, Any]:
        return {k: v["output"] for k, v in contexto["steps"].items()}

    with ledger.run(flujo.name, variante, billing) as run:
        pool = McpPool(servidores_mcp, entorno)
        grabador = Recorder(run, presupuesto=presupuesto, protegidos=protegidos)
        # El ejecutor y su diario solo existen si el workflow actua sobre el PC.
        ejecutor = None
        if any(isinstance(p, PcStep) for p in flujo.steps):
            base = Path.cwd()
            ejecutor = Ejecutor(
                perfil or cargar_perfil(base / "ejecutor.yml", base),
                Diario(raiz_diario() / run.run_id),
                base=base,
            )
        if any(isinstance(p, WebStep) for p in flujo.steps):
            web = web or Web(cliente_http)
            buscador = buscador or buscador_configurado(entorno, cliente_http)
        recursos = Recursos(grabador, local, remote, pool, cliente_http, entorno, ejecutor, web, buscador)

        def terminar_mal(estado: EstadoPaso) -> ResultadoFlujo:
            estados.append(estado)
            contexto["steps"][estado.id] = {"output": None, "status": estado.status}
            run.fail(f"{estado.id}: {estado.detalle}")
            return ResultadoFlujo(
                run.run_id, False, estados, salidas(), f"{estado.status} en {estado.id}: {estado.detalle}"
            )

        try:
            for paso in flujo.steps:
                inicio = time.perf_counter()

                # Entre pasos, no solo entre llamadas: un paso http o de herramienta
                # tambien actua fuera de lymi.
                try:
                    verificar_parada()
                    if presupuesto is not None:
                        presupuesto.verificar()
                except (Detenido, PresupuestoAgotado) as exc:
                    return terminar_mal(EstadoPaso(paso.id, "fallo", str(exc)))

                if paso.when is not None:
                    try:
                        cumple = condition.evaluar(paso.when, contexto)
                    except condition.ConditionError as exc:
                        return terminar_mal(EstadoPaso(paso.id, "fallo", str(exc)))
                    if not cumple:
                        estados.append(EstadoPaso(paso.id, "omitido", f"when falso: {paso.when}"))
                        contexto["steps"][paso.id] = {"output": None, "status": "omitido"}
                        continue

                if paso.efectos:
                    try:
                        vista = vista_previa(paso, contexto)
                        destino, metodo = destino_de(paso, contexto)
                    except (template.TemplateError, PasoError) as exc:
                        return terminar_mal(EstadoPaso(paso.id, "fallo", str(exc)))
                    solicitud = Solicitud(paso.id, paso.type, destino, metodo, vista)
                    aprobado, motivo = await resolver_aprobacion(solicitud, aprobar, politica, tiempo_aprobacion)
                    if not aprobado:
                        return terminar_mal(EstadoPaso(paso.id, "rechazado", motivo))

                intentos = 0
                while True:
                    intentos += 1
                    try:
                        salida = await asyncio.wait_for(
                            ejecutar(paso, contexto, recursos, flujo), timeout=paso.timeout_s
                        )
                        break
                    except TimeoutError:
                        error = PasoError(f"supero {paso.timeout_s:g} s")
                    except (template.TemplateError, condition.ConditionError) as exc:
                        error = PasoError(str(exc), reintentable=False)
                    except PasoError as exc:
                        error = exc
                    except Exception as exc:  # noqa: BLE001 - todo fallo inesperado se reporta
                        error = PasoError(f"{type(exc).__name__}: {exc}")

                    if not error.reintentable or intentos > paso.retries:
                        return terminar_mal(EstadoPaso(paso.id, "fallo", str(error), intentos, _ms(inicio)))
                    await espera(min(2 ** (intentos - 1), 8))

                contexto["steps"][paso.id] = {"output": salida, "status": "ok"}
                estados.append(EstadoPaso(paso.id, "ok", "", intentos, _ms(inicio)))

            hechos = sum(1 for e in estados if e.status == "ok")
            run.notes = f"{hechos} pasos ok, {len(estados) - hechos} omitidos"
            return ResultadoFlujo(run.run_id, True, estados, salidas())
        finally:
            await pool.aclose()
            if http_client is None:
                await cliente_http.aclose()


def correr(flujo: Workflow, inputs: Mapping[str, Any], **opciones: Any) -> ResultadoFlujo:
    """Version sincrona de `ejecutar_flujo`, para la linea de comandos."""
    return asyncio.run(ejecutar_flujo(flujo, inputs, **opciones))
