"""Motor de la agencia: agentes que trabajan, derivan tareas y crean ayudantes.

Un agente es un bucle: el modelo propone UNA accion JSON, lymi la valida, la
ejecuta y le devuelve el resultado. Las herramientas son los mismos pasos de los
workflows (web, codigo, pc, workflows enteros), asi que heredan todo lo que ya
protege un paso: pasarela de egress, ledger, perfil del ejecutor, aprobaciones.

Lo que otros sistemas de agentes no cuidan, y aqui es regla:

- **Topes duros compartidos por todo el arbol**: profundidad, agentes totales,
  agentes activos a la vez, turnos, llamadas, tokens remotos y tiempo. Crear
  agentes no multiplica el presupuesto: lo reparte.
- **Nadie gana permisos al delegar o crear.** Se delega solo por aristas
  declaradas en la agencia. Un ayudante creado tiene un subconjunto de las
  herramientas de su creador y no puede delegar ni crear.
- **Sin bloqueos mutuos.** Esperar a una tarea no ocupa cupo, y solo se espera a
  tareas propias: un hijo nunca espera a su padre.
- **La parada corta el arbol.** `lymi stop`, un tope o una falla cancelan a los
  descendientes; ninguna tarea queda huerfana trabajando.
- **Todo queda escrito.** Cada llamada al modelo va al ledger con su tarea y su
  agente; la traza (`runs/agencia/<corrida>.jsonl`) guarda que hizo cada uno,
  sin guardar el contenido.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from pydantic import TypeAdapter, ValidationError

from lymi.agencia.definicion import Agencia, AgenteDef
from lymi.agencia.protocolo import (
    Crear,
    Delegar,
    Enviar,
    Esperar,
    ProtocoloError,
    Terminar,
    Usar,
    instrucciones,
    interpretar,
)
from lymi.bench.runner import Recorder
from lymi.control import Detenido, Presupuesto, PresupuestoAgotado, verificar_parada
from lymi.flows import template
from lymi.flows.aprobaciones import Politica, Solicitud, resolver_aprobacion
from lymi.flows.nodes import McpPool, PasoError, Recursos, destino_de, ejecutar, vista_previa
from lymi.flows.schema import Step
from lymi.ledger import Billing, Ledger
from lymi.privacidad import EgressBloqueado
from lymi.providers.base import LLMClient, Message

LIMITE_OBSERVACION = 6000
"""Caracteres del resultado de una herramienta que vuelven al modelo."""
MAX_TOKENS_RESPUESTA = 1200
FALLOS_PROTOCOLO = 3
_TERMINADAS = frozenset({"hecha", "fallida", "cancelada"})
_ARGS_RESERVADOS = frozenset({"id", "type", "op", "when", "retries", "timeout_s", "tier"})
_PASO: TypeAdapter[Any] = TypeAdapter(Step)

Aprobador = Callable[..., Any]


class LimiteAgencia(RuntimeError):
    """Se alcanzo un tope de la agencia o de la tarea."""


def raiz_trazas() -> Path:
    return Path(os.environ.get("LYMI_TRAZAS", "runs/agencia"))


def _negar(_paso: str, _vista: str) -> bool:
    return False


@dataclass(slots=True)
class Tarea:
    id: str
    agente: str
    descripcion: str
    rol: str
    tier: str
    herramientas: frozenset[str]
    destinos: frozenset[str]
    puede_crear: bool
    max_turnos: int
    profundidad: int
    padre: str | None = None
    origen: str = "inicial"
    """inicial | delegada | creada"""
    paralela: bool = False
    estado: str = "pendiente"
    """pendiente | trabajando | esperando | hecha | fallida | cancelada"""
    resultado: str | None = None
    error: str | None = None
    hijos: list[str] = field(default_factory=list)
    buzon: list[str] = field(default_factory=list)
    turnos: int = 0
    llamadas: int = 0
    tokens_remotos: int = 0
    tokens_locales: int = 0
    segundos: float = 0.0
    tarea_async: asyncio.Task | None = field(default=None, repr=False)
    _inicio: float = field(default=0.0, repr=False)
    _insistio: bool = field(default=False, repr=False)
    _entregadas: set[str] = field(default_factory=set, repr=False)
    """Hijas cuyo resultado ya se le dio a esta tarea."""

    def resumen(self) -> dict[str, Any]:
        return {
            "id": self.id, "agente": self.agente, "padre": self.padre, "origen": self.origen,
            "paralela": self.paralela, "estado": self.estado, "turnos": self.turnos, "llamadas": self.llamadas,
            "tokens_remotos": self.tokens_remotos, "tokens_locales": self.tokens_locales,
            "segundos": round(self.segundos, 2), "error": self.error,
        }


class Orquestador:
    def __init__(
        self,
        agencia: Agencia,
        recursos: Recursos,
        *,
        aprobar: Aprobador | None = None,
        politica: Politica | None = None,
        tiempo_aprobacion: float | None = None,
        ledger: Ledger | None = None,
        traza: Path | None = None,
    ) -> None:
        self.agencia = agencia
        self.lim = agencia.limites
        self.r = recursos
        self.aprobar = aprobar or _negar
        self.politica = politica
        self.tiempo_aprobacion = tiempo_aprobacion
        self.ledger = ledger
        self.traza = traza
        self.tareas: dict[str, Tarea] = {}
        self.llamadas = 0
        self.tokens_remotos = 0
        self.max_activos = 0
        self._activos = 0
        self._cupo = asyncio.Semaphore(self.lim.simultaneos)
        self._inicio = time.monotonic()
        self._creados = 0

    # ------------------------------------------------------------ registro

    def _anotar(self, tarea: Tarea, evento: str, detalle: str = "") -> None:
        if self.traza is None:
            return
        self.traza.parent.mkdir(parents=True, exist_ok=True)
        linea = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "tarea": tarea.id, "agente": tarea.agente, "evento": evento, "detalle": detalle[:200],
        }
        with self.traza.open("a", encoding="utf-8") as f:
            f.write(json.dumps(linea, ensure_ascii=False) + "\n")

    @asynccontextmanager
    async def _ocupado(self) -> AsyncIterator[None]:
        async with self._cupo:
            self._activos += 1
            self.max_activos = max(self.max_activos, self._activos)
            try:
                yield
            finally:
                self._activos -= 1

    # ------------------------------------------------------------ tareas

    def _nueva(
        self,
        *,
        agente: str,
        descripcion: str,
        padre: str | None,
        origen: str,
        paralela: bool,
        definicion: AgenteDef | None = None,
        rol: str = "",
        herramientas: frozenset[str] = frozenset(),
        tier: str = "local",
    ) -> Tarea:
        if len(self.tareas) >= self.lim.agentes_totales:
            raise LimiteAgencia(f"se alcanzo el tope de {self.lim.agentes_totales} agentes por corrida")
        profundidad = 0 if padre is None else self.tareas[padre].profundidad + 1
        if profundidad > self.lim.profundidad:
            raise LimiteAgencia(f"se alcanzo la profundidad maxima de delegacion ({self.lim.profundidad})")
        if definicion is not None:
            rol, tier = definicion.rol, definicion.tier
            herramientas = frozenset(definicion.herramientas)
            destinos, puede_crear = self.agencia.destinos(agente), definicion.puede_crear
            max_turnos = definicion.max_turnos or self.lim.turnos_por_agente
        else:
            # Un ayudante creado no delega ni crea: el arbol no crece sin que nadie lo haya dibujado.
            destinos, puede_crear, max_turnos = frozenset(), False, self.lim.turnos_por_agente
        tarea = Tarea(
            id=f"t{len(self.tareas) + 1}", agente=agente, descripcion=descripcion, rol=rol, tier=tier,
            herramientas=herramientas, destinos=destinos, puede_crear=puede_crear, max_turnos=max_turnos,
            profundidad=profundidad, padre=padre, origen=origen, paralela=paralela,
        )
        self.tareas[tarea.id] = tarea
        if padre is not None:
            self.tareas[padre].hijos.append(tarea.id)
        self._anotar(tarea, "creada", f"{origen} por {padre or 'usuario'}")
        return tarea

    def _en_curso(self, tarea: Tarea) -> list[str]:
        return [h for h in tarea.hijos if self.tareas[h].estado not in _TERMINADAS]

    def _sin_entregar(self, tarea: Tarea) -> list[str]:
        """Hijas cuyo resultado la tarea aun no recibio, hayan terminado o no.

        Una hija paralela puede terminar antes de que su padre llame a `esperar`:
        su resultado igual tiene que llegarle.
        """
        return [h for h in tarea.hijos if h not in tarea._entregadas]

    def _cancelar(self, tarea_id: str, motivo: str) -> None:
        hija = self.tareas[tarea_id]
        if hija.tarea_async is not None and not hija.tarea_async.done():
            hija.error = hija.error or motivo
            hija.tarea_async.cancel()

    def _cancelar_hijos(self, tarea: Tarea, motivo: str) -> None:
        for h in tarea.hijos:
            self._cancelar(h, motivo)

    def _informe(self, tarea: Tarea) -> str:
        if tarea.estado == "hecha":
            return f"{tarea.id} ({tarea.agente}) termino:\n{tarea.resultado}"
        if tarea.estado == "fallida":
            return f"{tarea.id} ({tarea.agente}) fallo: {tarea.error}"
        return f"{tarea.id} ({tarea.agente}) fue cancelada: {tarea.error or 'sin motivo'}"

    # ------------------------------------------------------------ modelo

    def _verificar_limites(self) -> None:
        verificar_parada()
        if self.llamadas >= self.lim.llamadas:
            raise PresupuestoAgotado(f"se alcanzo el tope de {self.lim.llamadas} llamadas de la agencia")
        if self.lim.tokens_remotos is not None and self.tokens_remotos >= self.lim.tokens_remotos:
            raise PresupuestoAgotado(f"se alcanzo el tope de {self.lim.tokens_remotos:,} tokens remotos de la agencia")
        if time.monotonic() - self._inicio > self.lim.segundos:
            raise LimiteAgencia(f"se agoto el tiempo de la corrida ({self.lim.segundos:g} s)")

    def _cliente(self, tier: str) -> LLMClient:
        cliente = self.r.local if tier == "local" else self.r.remote
        if cliente is None:
            raise LimiteAgencia(f"no hay modelo {tier}: corre `lymi setup`")
        return cliente

    async def _modelo(self, tarea: Tarea, sistema: str, mensajes: list[Message]) -> str:
        cliente = self._cliente(tarea.tier)
        self._verificar_limites()
        enviados, sistema_final, redactor = self.r.rec.preparar(cliente, mensajes, sistema)
        remoto = getattr(cliente, "billing", Billing.API) is not Billing.LOCAL
        async with self._ocupado():
            completion = await asyncio.to_thread(
                cliente.complete, enviados, system=sistema_final, max_tokens=MAX_TOKENS_RESPUESTA,
                # El sistema de un agente se repite en cada turno: el remoto lo cachea.
                cache_system=remoto,
            )
        if redactor is not None:
            completion.text = redactor.rehidratar(completion.text)
        self.r.rec.registrar(
            completion, enviados, purpose=f"agente:{tarea.id}:{tarea.agente}", system=sistema_final,
            redacciones=redactor.total if redactor is not None else 0,
        )
        u = completion.usage
        total = u.input_tokens + u.output_tokens + u.cache_read_tokens + u.cache_write_tokens
        self.llamadas += 1
        tarea.llamadas += 1
        if completion.billing is Billing.LOCAL:
            tarea.tokens_locales += total
        else:
            tarea.tokens_remotos += total
            self.tokens_remotos += total
        return completion.text

    def _sistema(self, tarea: Tarea) -> str:
        agentes = self.agencia.agentes()
        return instrucciones(
            nombre=tarea.agente,
            rol=tarea.rol,
            herramientas=sorted(tarea.herramientas),
            descripciones_workflow={
                w: f'corre el workflow {Path(ruta).name}. args: {{"inputs": {{...}}}}'
                for w, ruta in self.agencia.workflows.items()
            },
            destinos={d: agentes[d].descripcion for d in sorted(tarea.destinos)},
            puede_crear=tarea.puede_crear,
            tareas_hermanas=tarea.padre is not None,
        )

    # ------------------------------------------------------------ trabajo

    async def _trabajar(self, tarea: Tarea) -> None:
        tarea.estado = "trabajando"
        tarea._inicio = time.monotonic()
        sistema = self._sistema(tarea)
        mensajes: list[Message] = []
        pendiente = f"Tu tarea ({tarea.id}):\n{tarea.descripcion}"
        fallos = 0
        try:
            while True:
                if tarea.turnos >= tarea.max_turnos:
                    raise LimiteAgencia(f"agoto sus {tarea.max_turnos} turnos sin terminar")
                tarea.turnos += 1
                if tarea.buzon:
                    pendiente += "\n\nMensajes nuevos:\n" + "\n".join(tarea.buzon)
                    tarea.buzon.clear()
                mensajes.append(Message("user", pendiente))
                texto = await self._modelo(tarea, sistema, mensajes)
                mensajes.append(Message("assistant", texto))
                try:
                    accion = interpretar(texto)
                except ProtocoloError as exc:
                    fallos += 1
                    self._anotar(tarea, "protocolo", str(exc))
                    if fallos >= FALLOS_PROTOCOLO:
                        raise LimiteAgencia(f"el modelo no siguio el protocolo {fallos} veces: {exc}") from None
                    pendiente = f"Respuesta invalida ({exc}). Responde SOLO un objeto JSON con una accion."
                    continue

                if isinstance(accion, Terminar):
                    en_curso = self._en_curso(tarea)
                    if en_curso and not tarea._insistio:
                        tarea._insistio = True
                        pendiente = (
                            f"Tienes tareas en curso ({', '.join(en_curso)}). Usa esperar para recibir su resultado,"
                            " o vuelve a terminar para cancelarlas."
                        )
                        continue
                    self._cancelar_hijos(tarea, f"{tarea.id} termino sin esperarla")
                    tarea.resultado = accion.resultado
                    tarea.estado = "hecha"
                    self._anotar(tarea, "hecha", f"{len(accion.resultado)} caracteres")
                    return
                # Una accion decidida despues de `lymi stop` no se ejecuta.
                verificar_parada()
                self._anotar(tarea, "accion", _describir(accion))
                observacion = await self._actuar(tarea, accion)
                if len(observacion) > LIMITE_OBSERVACION:
                    observacion = observacion[:LIMITE_OBSERVACION] + f"\n[recortado: {len(observacion)} caracteres]"
                pendiente = f"Resultado:\n{observacion}"
        except asyncio.CancelledError:
            tarea.estado = "cancelada"
            self._cancelar_hijos(tarea, f"{tarea.id} fue cancelada")
            self._anotar(tarea, "cancelada", tarea.error or "")
            raise
        except (LimiteAgencia, PresupuestoAgotado, Detenido, EgressBloqueado) as exc:
            self._fallar(tarea, str(exc))
        except Exception as exc:  # noqa: BLE001 - una tarea que revienta no tumba a la agencia
            self._fallar(tarea, f"{type(exc).__name__}: {exc}")
        finally:
            tarea.segundos = time.monotonic() - tarea._inicio

    def _fallar(self, tarea: Tarea, motivo: str) -> None:
        tarea.estado = "fallida"
        tarea.error = motivo
        self._cancelar_hijos(tarea, f"{tarea.id} fallo")
        self._anotar(tarea, "fallida", motivo)

    async def _lanzar(self, padre: Tarea, hija: Tarea, esperar: bool) -> str:
        hija.tarea_async = asyncio.create_task(self._trabajar(hija), name=hija.id)
        if not esperar:
            return f"{hija.id} ({hija.agente}) empezo en paralelo. Usa esperar para recibir su resultado."
        padre.estado = "esperando"
        try:
            # asyncio.wait no propaga la cancelacion de la hija como si fuera propia.
            await asyncio.wait({hija.tarea_async})
        finally:
            if padre.estado == "esperando":
                padre.estado = "trabajando"
        padre._entregadas.add(hija.id)
        return self._informe(hija)

    async def _actuar(self, tarea: Tarea, accion: Any) -> str:
        if isinstance(accion, Usar):
            return await self._usar(tarea, accion)

        if isinstance(accion, Delegar):
            destino = self.agencia.resolver(accion.a, desde=tarea.agente) if tarea.origen != "creada" else None
            if destino is None or destino not in tarea.destinos:
                permitidos = ", ".join(sorted(tarea.destinos)) or "ninguno"
                return f"no puedes delegar a {accion.a!r}; puedes delegar a: {permitidos}"
            try:
                hija = self._nueva(
                    agente=destino, descripcion=accion.tarea, padre=tarea.id, origen="delegada",
                    paralela=not accion.esperar, definicion=self.agencia.agentes()[destino],
                )
            except LimiteAgencia as exc:
                return f"no se pudo delegar: {exc}"
            return await self._lanzar(tarea, hija, accion.esperar)

        if isinstance(accion, Crear):
            if not tarea.puede_crear:
                return "no puedes crear ayudantes"
            pedidas = frozenset(accion.herramientas)
            if fuera := pedidas - tarea.herramientas:
                return f"un ayudante solo puede tener herramientas tuyas; no tienes: {', '.join(sorted(fuera))}"
            self._creados += 1
            try:
                hija = self._nueva(
                    agente=f"{tarea.agente}>ayudante{self._creados}", descripcion=accion.tarea, padre=tarea.id,
                    origen="creada", paralela=not accion.esperar, rol=accion.rol, herramientas=pedidas,
                    tier=tarea.tier,
                )
            except LimiteAgencia as exc:
                return f"no se pudo crear el ayudante: {exc}"
            return await self._lanzar(tarea, hija, accion.esperar)

        if isinstance(accion, Esperar):
            ids = accion.tareas or self._sin_entregar(tarea)
            if ajenas := [i for i in ids if i not in tarea.hijos]:
                return f"solo puedes esperar tareas que tu iniciaste; {', '.join(ajenas)} no lo son"
            if not ids:
                return "no tienes tareas pendientes de resultado"
            asincronas = {t for i in ids if (t := self.tareas[i].tarea_async) is not None}
            if asincronas:
                tarea.estado = "esperando"
                try:
                    await asyncio.wait(asincronas)
                finally:
                    if tarea.estado == "esperando":
                        tarea.estado = "trabajando"
            tarea._entregadas.update(ids)
            return "\n\n".join(self._informe(self.tareas[i]) for i in ids)

        if isinstance(accion, Enviar):
            hermanas = {i for i, t in self.tareas.items() if t.padre == tarea.padre and i != tarea.id} \
                if tarea.padre else set()
            relacionadas = set(tarea.hijos) | hermanas | ({tarea.padre} if tarea.padre else set())
            destino = self.tareas.get(accion.a)
            if destino is None or accion.a not in relacionadas:
                return f"solo puedes escribir a tareas relacionadas contigo: {', '.join(sorted(relacionadas)) or 'ninguna'}"
            if destino.estado in _TERMINADAS:
                return f"{accion.a} ya termino ({destino.estado})"
            destino.buzon.append(f"[{tarea.id} {tarea.agente}] {accion.texto}")
            return f"mensaje entregado a {accion.a}; lo vera en su proximo turno"

        return "accion desconocida"

    async def _usar(self, tarea: Tarea, accion: Usar) -> str:
        nombre = accion.herramienta
        if nombre not in tarea.herramientas:
            return f"no tienes la herramienta {nombre!r}; las tuyas: {', '.join(sorted(tarea.herramientas)) or 'ninguna'}"
        self._verificar_limites()
        if nombre.startswith("workflow:"):
            return await self._workflow(tarea, nombre, accion.args)

        familia, _, op = nombre.partition(".")
        # Los modelos pequenos rellenan los opcionales con "" o null: vacio es "no lo envie".
        # Si era obligatorio, el agente recibe "requiere X", que es un error que entiende.
        args = {k: v for k, v in accion.args.items() if k not in _ARGS_RESERVADOS and v not in (None, "")}
        datos: dict[str, Any] = {**args, "id": f"{tarea.id}_{tarea.turnos}", "type": familia, "op": op}
        if familia == "web" and op == "investigar":
            datos["tier"] = "local" if tarea.tier == "local" else "remote"
        try:
            paso = _PASO.validate_python(datos)
        except ValidationError as exc:
            errores = "; ".join(f"{'.'.join(map(str, e['loc'][1:])) or nombre}: {e['msg']}" for e in exc.errors()[:3])
            return f"argumentos invalidos para {nombre}: {errores}"

        if paso.efectos:
            try:
                destino, metodo = destino_de(paso, {})
                vista = vista_previa(paso, {})
            except (template.TemplateError, PasoError) as exc:
                return f"error en {nombre}: {exc}"
            solicitud = Solicitud(paso.id, "agente", destino, metodo, f"{tarea.agente} ({tarea.id}) quiere:\n{vista}")
            aprobado, motivo = await resolver_aprobacion(solicitud, self.aprobar, self.politica, self.tiempo_aprobacion)
            if not aprobado:
                self._anotar(tarea, "rechazado", nombre)
                return f"la accion fue rechazada: {motivo}"

        try:
            async with self._ocupado():
                salida = await asyncio.wait_for(ejecutar(paso, {}, self.r, None), timeout=paso.timeout_s)
        except TimeoutError:
            return f"{nombre} supero {paso.timeout_s:g} s"
        except (PasoError, template.TemplateError) as exc:
            return f"error en {nombre}: {exc}"
        if isinstance(salida, dict) and "texto" in salida:
            return str(salida["texto"])
        return salida if isinstance(salida, str) else json.dumps(salida, ensure_ascii=False)

    async def _workflow(self, tarea: Tarea, nombre: str, args: Mapping[str, Any]) -> str:
        from lymi.flows.engine import EntradaError, ejecutar_flujo
        from lymi.flows.schema import cargar

        if self.ledger is None:
            return "los workflows no estan disponibles en esta corrida"
        flujo = cargar(self.agencia.workflows[nombre])
        entradas = args.get("inputs", args)
        if not isinstance(entradas, Mapping):
            return 'args de un workflow: {"inputs": {...}}'
        try:
            resultado = await ejecutar_flujo(
                flujo, dict(entradas), ledger=self.ledger, local=self.r.local, remote=self.r.remote,
                aprobar=self.aprobar, politica=self.politica, tiempo_aprobacion=self.tiempo_aprobacion,
                variante=f"agente:{tarea.id}",
            )
        except EntradaError as exc:
            return f"entradas invalidas para {nombre}: {exc}"
        estado = "ok" if resultado.ok else f"fallo: {resultado.detalle}"
        salidas = json.dumps(resultado.salidas, ensure_ascii=False, default=str)
        return f"workflow {flujo.name} {estado} (corrida {resultado.run_id})\n{salidas}"

    # ------------------------------------------------------------ entrada

    async def correr(self, descripcion: str, agente: str) -> Tarea:
        nombre = self.agencia.resolver(agente)
        if nombre is None:
            raise ValueError(f"{agente!r} no es un agente ni un departamento de {self.agencia.name}")
        raiz = self._nueva(
            agente=nombre, descripcion=descripcion, padre=None, origen="inicial", paralela=False,
            definicion=self.agencia.agentes()[nombre],
        )
        raiz.tarea_async = asyncio.create_task(self._trabajar(raiz), name=raiz.id)
        hechas, _ = await asyncio.wait({raiz.tarea_async}, timeout=self.lim.segundos)
        if not hechas:
            self._cancelar(raiz.id, f"se agoto el tiempo de la corrida ({self.lim.segundos:g} s)")
            await asyncio.wait({raiz.tarea_async})
        # Nada queda trabajando cuando la corrida termina.
        restantes = [t.tarea_async for t in self.tareas.values() if t.tarea_async and not t.tarea_async.done()]
        for pendiente in restantes:
            pendiente.cancel()
        if restantes:
            await asyncio.wait(restantes)
        return raiz


def _describir(accion: Any) -> str:
    if isinstance(accion, Usar):
        return f"usar {accion.herramienta}"
    if isinstance(accion, Delegar):
        return f"delegar a {accion.a} ({'espera' if accion.esperar else 'paralelo'})"
    if isinstance(accion, Crear):
        return f"crear ayudante con {', '.join(accion.herramientas) or 'sin herramientas'}"
    if isinstance(accion, Esperar):
        return f"esperar {', '.join(accion.tareas) or 'todas'}"
    if isinstance(accion, Enviar):
        return f"enviar a {accion.a}"
    return type(accion).__name__


# ---------------------------------------------------------------- enrutador


async def enrutar(agencia: Agencia, texto: str, local: LLMClient | None, rec: Recorder | None) -> tuple[str, str, str]:
    """Elige quien recibe una tarea. Devuelve (agente, tarea, motivo).

    Primero `@agente` o `@departamento` al inicio. Si no, con un solo departamento,
    su lider. Si no, el modelo LOCAL elige el departamento (gratis). Si no hay modelo
    local o responde algo que no existe, el primer departamento, y se dice.
    """
    texto = texto.strip()
    if texto.startswith("@"):
        destino, _, resto = texto[1:].partition(" ")
        if (nombre := agencia.resolver(destino)) is not None and resto.strip():
            return nombre, resto.strip(), f"@{destino}"
    primero = next(iter(agencia.departamentos))
    lider = f"{primero}.{agencia.departamentos[primero].jefe}"
    if len(agencia.departamentos) == 1:
        return lider, texto, "unico departamento"
    if local is None or rec is None:
        return lider, texto, "sin modelo local para enrutar: primer departamento"

    lista = "\n".join(f"- {n}: {d.descripcion or n}" for n, d in agencia.departamentos.items())
    sistema = (
        "Eres el enrutador de una agencia. Elige el departamento que debe recibir la tarea."
        f" Responde SOLO el identificador del departamento, sin nada mas. Opciones:\n{lista}"
    )
    mensajes, sistema_final, _ = rec.preparar(local, [Message("user", texto)], sistema)
    completion = await asyncio.to_thread(local.complete, mensajes, system=sistema_final, max_tokens=20)
    rec.registrar(completion, mensajes, purpose="agencia:enrutar", system=sistema_final)
    elegido = completion.text.strip().split()[0].strip("`'\".,:") if completion.text.strip() else ""
    if elegido in agencia.departamentos:
        return f"{elegido}.{agencia.departamentos[elegido].jefe}", texto, "elegido por el modelo local"
    return lider, texto, f"el modelo local respondio {elegido!r}, que no existe: primer departamento"


# ---------------------------------------------------------------- corrida completa


@dataclass(slots=True)
class ResultadoAgencia:
    run_id: str
    ok: bool
    agente: str
    motivo_ruta: str
    resultado: str | None
    detalle: str
    tareas: list[Tarea]
    max_simultaneos: int


async def correr_agencia(
    agencia: Agencia,
    texto: str,
    *,
    ledger: Ledger,
    local: LLMClient | None = None,
    remote: LLMClient | None = None,
    agente: str | None = None,
    aprobar: Aprobador | None = None,
    politica: Politica | None = None,
    tiempo_aprobacion: float | None = None,
    protegidos: tuple[str, ...] = (),
    entorno: Mapping[str, str] | None = None,
    http_client: httpx.AsyncClient | None = None,
    web: Any = None,
) -> ResultadoAgencia:
    """Arma todo lo que necesita una corrida de la agencia y la ejecuta."""
    from lymi.ejecutor import Diario, Ejecutor, cargar_perfil, raiz_diario
    from lymi.web import Web, buscador_configurado

    entorno = dict(os.environ) if entorno is None else dict(entorno)
    herramientas = {h for a in agencia.agentes().values() for h in a.herramientas}
    billing = remote.billing if remote is not None and any(
        a.tier == "remote" for a in agencia.agentes().values()) else Billing.LOCAL if local else Billing.NONE
    lim = agencia.limites

    with ledger.run(agencia.name, "agencia", billing) as run:
        rec = Recorder(run, presupuesto=Presupuesto(lim.tokens_remotos, lim.llamadas), protegidos=protegidos)
        if agente is None:
            destino, tarea, motivo = await enrutar(agencia, texto, local, rec)
        else:
            destino, tarea, motivo = agencia.resolver(agente) or agente, texto, "elegido por quien corre"
        cliente = http_client or httpx.AsyncClient(follow_redirects=False)
        pool = McpPool({}, entorno)
        try:
            base = Path.cwd()
            ejecutor = None
            if any(h.startswith("pc.") for h in herramientas):
                ejecutor = Ejecutor(cargar_perfil(base / "ejecutor.yml", base), Diario(raiz_diario() / run.run_id), base=base)
            if web is None and any(h.startswith("web.") for h in herramientas):
                web = Web(cliente)
            buscador = buscador_configurado(entorno, cliente) if web is not None else None
            recursos = Recursos(rec, local, remote, pool, cliente, entorno, ejecutor, web, buscador)
            orquestador = Orquestador(
                agencia, recursos, aprobar=aprobar, politica=politica, tiempo_aprobacion=tiempo_aprobacion,
                ledger=ledger, traza=raiz_trazas() / f"{run.run_id}.jsonl",
            )
            raiz = await orquestador.correr(tarea, destino)
        finally:
            await pool.aclose()
            if http_client is None:
                await cliente.aclose()

        ok = raiz.estado == "hecha"
        if not ok:
            run.fail(f"{raiz.id}: {raiz.error}")
        run.notes = f"{len(orquestador.tareas)} tareas, hasta {orquestador.max_activos} a la vez; ruta: {motivo}"

    return ResultadoAgencia(
        run_id=run.run_id, ok=ok, agente=raiz.agente, motivo_ruta=motivo, resultado=raiz.resultado,
        detalle=raiz.error or "", tareas=list(orquestador.tareas.values()), max_simultaneos=orquestador.max_activos,
    )


def arbol(tareas: list[Tarea]) -> list[str]:
    """Las tareas como arbol de texto, para la terminal."""
    por_padre: dict[str | None, list[Tarea]] = {}
    for t in tareas:
        por_padre.setdefault(t.padre, []).append(t)
    lineas: list[str] = []

    def pintar(t: Tarea, prefijo: str, ultimo: bool, raiz: bool) -> None:
        rama = "" if raiz else ("└─ " if ultimo else "├─ ")
        modo = " (paralelo)" if t.paralela else ""
        tokens = f", {t.tokens_remotos:,} tok remotos" if t.tokens_remotos else ""
        estado = t.estado if t.estado == "hecha" else f"{t.estado}: {t.error}"
        lineas.append(f"{prefijo}{rama}{t.id} {t.agente}{modo}  {estado}  [{t.turnos} turnos{tokens}]")
        hijos = por_padre.get(t.id, [])
        siguiente = prefijo if raiz else prefijo + ("   " if ultimo else "│  ")
        for i, h in enumerate(hijos):
            pintar(h, siguiente, i == len(hijos) - 1, False)

    for r in por_padre.get(None, []):
        pintar(r, "", True, True)
    return lineas
