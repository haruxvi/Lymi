"""Trabajos en segundo plano de la interfaz.

Todo lo que gasta tokens, sale a la red o tiene efectos corre aqui, por el mismo
motor que la terminal: workflows de archivo, workflows de un paso que arma la
interfaz (resumir el correo, investigar en la web), corridas de la agencia (el
chat es una) y funciones sueltas (redactar un borrador).

Cada trabajo corre en su propio hilo, con su propia conexion al ledger: SQLite no
comparte conexiones entre hilos. La interfaz consulta el estado por sondeo.

Las aprobaciones se resuelven desde la pagina: el aprobador publica la solicitud
en el trabajo y espera la decision con vencimiento. Un vencimiento cuenta como
rechazo, igual que en la terminal. Si varios agentes piden a la vez, se atienden
de a uno: la pagina nunca muestra una solicitud que otra pisó.
"""

from __future__ import annotations

import asyncio
import json
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lymi.flows.aprobaciones import Decision, MemoriaAprobaciones, Politica, ReglaError, Solicitud
from lymi.flows.engine import ejecutar_flujo, preparar_inputs
from lymi.flows.schema import Workflow, cargar
from lymi.ledger import Ledger

VENCIMIENTO_APROBACION = 300.0
MAX_EVENTOS = 200
MAX_SIMULTANEOS = 4
LIMITE_SALIDA = 4000
"""Caracteres maximos de cada salida de paso que se devuelven como texto."""
LIMITE_DATOS = 400_000
"""Bytes maximos de las salidas estructuradas; por encima, solo va el texto."""

DECISIONES = frozenset({"aprobar", "rechazar", "siempre"})
_ACTIVOS = frozenset({"en_curso", "esperando"})
_TOTALES = ("remote_tokens", "local_tokens", "egress_calls", "cost_usd", "billing_mode")


class TrabajoError(RuntimeError):
    """El trabajo no se puede lanzar o la operacion no aplica a su estado."""


def _hora() -> str:
    return datetime.now(UTC).astimezone().strftime("%H:%M:%S")


@dataclass(slots=True)
class Trabajo:
    id: str
    tipo: str
    """bench | workflow | flujo | agencia | chat | funcion"""
    titulo: str
    contexto: dict[str, Any] = field(default_factory=dict)
    """Lo que la pagina necesita para volver a su sitio: archivo, sesion, carpeta..."""
    estado: str = "en_curso"
    """en_curso | esperando | ok | fallo | error"""
    eventos: list[str] = field(default_factory=list)
    pasos: dict[str, dict[str, str]] = field(default_factory=dict)
    """Estado en vivo de cada paso de un workflow: lo pinta el lienzo."""
    pendiente: dict[str, Any] | None = None
    resultado: dict[str, Any] | None = None
    creado: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))
    decision: str | None = None
    hay_decision: threading.Event = field(default_factory=threading.Event)
    turno_aprobacion: threading.Lock = field(default_factory=threading.Lock)

    def vista(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tipo": self.tipo,
            "titulo": self.titulo,
            "contexto": dict(self.contexto),
            "estado": self.estado,
            "eventos": list(self.eventos),
            "pasos": {k: dict(v) for k, v in self.pasos.items()},
            "pendiente": dict(self.pendiente) if self.pendiente else None,
            "resultado": self.resultado,
            "creado": self.creado,
        }


def _recortar(valor: Any) -> Any:
    texto = valor if isinstance(valor, str) else json.dumps(valor, ensure_ascii=False, default=str)
    return texto if len(texto) <= LIMITE_SALIDA else texto[:LIMITE_SALIDA] + " […]"


def _acotar(datos: dict[str, Any]) -> dict[str, Any] | None:
    """Las salidas estructuradas, si caben. Una salida enorme no viaja entera a la pagina."""
    try:
        crudo = json.dumps(datos, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return None
    return json.loads(crudo) if len(crudo.encode("utf-8")) <= LIMITE_DATOS else None


class Trabajos:
    def __init__(
        self,
        *,
        ledger: Path,
        memoria: Path,
        proveedores: Callable[[], tuple[Any, str | None, Any, str | None]] | None = None,
        cablear: Callable[[], Any] | None = None,
        vencimiento: float = VENCIMIENTO_APROBACION,
        max_simultaneos: int = MAX_SIMULTANEOS,
        avisos: Any = None,
    ) -> None:
        self.avisos = avisos
        """`lymi.avisos.Avisos`: que algo espera tu decision o termino, aunque no mires la pagina."""
        self.ledger = ledger
        self._memoria = memoria
        self._proveedores = proveedores
        self._cablear = cablear
        self._vencimiento = vencimiento
        self._max = max_simultaneos
        self._lock = threading.Lock()
        self._trabajos: dict[str, Trabajo] = {}

    # ------------------------------------------------------------ consulta

    def listar(self) -> list[dict[str, Any]]:
        with self._lock:
            trabajos = sorted(self._trabajos.values(), key=lambda t: t.creado, reverse=True)
            return [t.vista() for t in trabajos]

    def obtener(self, trabajo_id: str) -> dict[str, Any] | None:
        with self._lock:
            trabajo = self._trabajos.get(trabajo_id)
            return trabajo.vista() if trabajo else None

    def activos(self) -> int:
        with self._lock:
            return sum(1 for t in self._trabajos.values() if t.estado in _ACTIVOS)

    def esperando(self) -> list[dict[str, Any]]:
        """Los trabajos que esperan una decision tuya, para la pantalla Hoy."""
        with self._lock:
            return [t.vista() for t in self._trabajos.values() if t.pendiente is not None]

    def proveedores(
        self, modelo_local: str | None = None, modelo_remoto: str | None = None
    ) -> tuple[Any, str | None, Any, str | None]:
        if self._proveedores is None:
            from lymi.bench.wiring import proveedores

            return proveedores(modelo_local, modelo_remoto)
        return self._proveedores()

    # ------------------------------------------------------------ ciclo de vida

    def _nuevo(self, tipo: str, titulo: str, contexto: dict[str, Any] | None = None) -> Trabajo:
        with self._lock:
            activos = [t for t in self._trabajos.values() if t.estado in _ACTIVOS]
            if tipo == "bench" and any(t.tipo == "bench" for t in activos):
                raise TrabajoError("ya hay una medicion en curso: dos a la vez se pisarian la cache")
            if len(activos) >= self._max:
                raise TrabajoError(f"ya hay {len(activos)} trabajos en curso; espera a que alguno termine")
            trabajo = Trabajo(uuid.uuid4().hex[:10], tipo, titulo, dict(contexto or {}))
            self._trabajos[trabajo.id] = trabajo
            return trabajo

    def evento(self, trabajo: Trabajo, texto: str) -> None:
        with self._lock:
            trabajo.eventos.append(f"{_hora()}  {texto}")
            del trabajo.eventos[:-MAX_EVENTOS]

    def _terminar(self, trabajo: Trabajo, estado: str, resultado: dict[str, Any] | None) -> None:
        with self._lock:
            trabajo.estado = estado
            trabajo.resultado = resultado
            trabajo.pendiente = None

    def _lanzar(
        self,
        trabajo: Trabajo,
        objetivo: Callable[[Trabajo], None],
        al_terminar: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        def envolver() -> None:
            try:
                objetivo(trabajo)
            except Exception as exc:  # noqa: BLE001 - todo fallo se muestra en la pagina
                self.evento(trabajo, f"error: {type(exc).__name__}: {exc}")
                self._terminar(trabajo, "error", {"tipo": "error", "detalle": f"{exc}"})
            if al_terminar is not None:
                try:
                    al_terminar(trabajo.vista())
                except Exception as exc:  # noqa: BLE001 - el trabajo ya termino; solo se avisa
                    self.evento(trabajo, f"no se pudo guardar el resultado: {exc}")
            if self.avisos is not None and trabajo.tipo != "bench":
                ok = trabajo.estado == "ok"
                detalle = (trabajo.resultado or {}).get("detalle") or ""
                self.avisos.publicar("terminado" if ok else "error", f"{'Listo' if ok else 'No termino'}: {trabajo.titulo}",
                                     "" if ok else str(detalle)[:300], self._enlace(trabajo))

        hilo = threading.Thread(target=envolver, name=f"lymi-{trabajo.tipo}-{trabajo.id}", daemon=True)
        hilo.start()
        return trabajo.vista()

    @staticmethod
    def _enlace(trabajo: Trabajo) -> str:
        """Donde mirar este trabajo en la interfaz."""
        if sesion := trabajo.contexto.get("sesion"):
            return f"#/chat/{sesion}"
        if trabajo.tipo == "workflow" and (archivo := trabajo.contexto.get("archivo")):
            return f"#/workflows/{archivo}"
        return f"#/trabajos/{trabajo.id}"

    def decidir(self, trabajo_id: str, decision: str) -> None:
        if decision not in DECISIONES:
            raise ValueError("decision invalida: aprobar, rechazar o siempre")
        with self._lock:
            trabajo = self._trabajos.get(trabajo_id)
            if trabajo is None:
                raise KeyError(trabajo_id)
            if trabajo.pendiente is None:
                raise TrabajoError("este trabajo no espera ninguna aprobacion")
            trabajo.decision = decision
        trabajo.hay_decision.set()

    def revocar_pendientes(self) -> int:
        """Rechaza toda aprobacion en espera: parte del interruptor de parada."""
        with self._lock:
            esperando = [t for t in self._trabajos.values() if t.pendiente is not None]
            for trabajo in esperando:
                trabajo.decision = "rechazar"
        for trabajo in esperando:
            trabajo.hay_decision.set()
        return len(esperando)

    # ------------------------------------------------------------ aprobaciones

    def _aprobador(self, trabajo: Trabajo, memoria: MemoriaAprobaciones) -> Callable[..., bool]:
        def aprobar(paso_id: str, vista: str, solicitud: Solicitud) -> bool:
            with trabajo.turno_aprobacion:
                return self._preguntar(trabajo, memoria, paso_id, vista, solicitud)

        return aprobar

    def _preguntar(
        self, trabajo: Trabajo, memoria: MemoriaAprobaciones, paso_id: str, vista: str, solicitud: Solicitud
    ) -> bool:
        with self._lock:
            trabajo.decision = None
            trabajo.hay_decision.clear()
            trabajo.pendiente = {
                "paso": paso_id,
                "tipo": solicitud.tipo,
                "destino": solicitud.destino,
                "metodo": solicitud.metodo,
                "vista": vista,
                "vence_en_s": self._vencimiento,
            }
            trabajo.estado = "esperando"
        self.evento(trabajo, f"{paso_id} pide aprobacion para {solicitud.destino}")
        if self.avisos is not None:
            self.avisos.publicar("aprobacion", f"Espera tu decision: {trabajo.titulo}",
                                 f"{paso_id} quiere actuar en {solicitud.destino}", self._enlace(trabajo))

        llego = trabajo.hay_decision.wait(self._vencimiento)
        with self._lock:
            decision = trabajo.decision if llego else None
            trabajo.pendiente = None
            trabajo.estado = "en_curso"

        if decision is None:
            self.evento(trabajo, f"{paso_id}: la aprobacion vencio sin respuesta")
            return False
        if decision == "siempre":
            try:
                hasta = memoria.recordar(solicitud.destino, solicitud.metodo, Decision.APROBAR)
                self.evento(trabajo, f"{paso_id}: aprobado y recordado hasta {hasta:%Y-%m-%d}")
            except ReglaError as exc:
                self.evento(trabajo, f"{paso_id}: aprobado solo esta vez ({exc})")
            return True
        self.evento(trabajo, f"{paso_id}: {'aprobado' if decision == 'aprobar' else 'rechazado'}")
        return decision == "aprobar"

    # ------------------------------------------------------------ bench

    def lanzar_bench(self, *, demo: bool, calentar: bool, confirmar: bool) -> dict[str, Any]:
        if not demo and not confirmar:
            raise ValueError("una medicion real gasta tokens de tu proveedor: confirma para lanzarla")
        titulo = "Snake en Python" + (" · demo" if demo else "")
        trabajo = self._nuevo("bench", titulo)
        return self._lanzar(trabajo, lambda t: self._correr_bench(t, demo=demo, calentar=calentar))

    def _correr_bench(self, trabajo: Trabajo, *, demo: bool, calentar: bool) -> None:
        from lymi.bench.demo import MATERIAL_DEMO, construir_demo
        from lymi.bench.report import Receipt
        from lymi.bench.runner import calentar_cache, run_task
        from lymi.bench.strategies import SISTEMA
        from lymi.bench.tasks import SnakeTask
        from lymi.ledger.pricing import load_overrides

        load_overrides()
        if demo:
            objetivo, base, lymi = construir_demo()
            procedencia = "respuestas guionadas (no demuestra ahorro real)"
        else:
            if self._cablear is None:
                from lymi.bench.wiring import cablear
            else:
                cablear = self._cablear
            cableado = cablear()
            objetivo = SnakeTask()
            objetivo.material = MATERIAL_DEMO  # type: ignore[attr-defined]
            base, lymi, procedencia = cableado.base, cableado.lymi, cableado.resumen
        self.evento(trabajo, f"proveedores: {procedencia}")

        ledger = Ledger(self.ledger)
        try:
            if calentar and not demo:
                self.evento(trabajo, "calentando la cache del proveedor (llamada minima, registrada aparte)")
                calentar_cache(ledger, objetivo, base.remote, system=SISTEMA)
            self.evento(trabajo, "[1/2] linea base: esperando al modelo remoto")
            r_base = run_task(ledger, objetivo, base)
            self.evento(trabajo, f"linea base: {r_base.gate.detail}")
            self.evento(trabajo, "[2/2] lymi: destilando en local y consultando al remoto")
            r_lymi = run_task(ledger, objetivo, lymi)
            self.evento(trabajo, f"lymi: {r_lymi.gate.detail}")
        finally:
            ledger.close()

        recibo = Receipt(
            task_id=objetivo.id, task_title=objetivo.title, base=r_base, test=r_lymi, demo=demo
        )
        resultado = {
            "tipo": "recibo",
            "titulo": objetivo.title,
            "demo": demo,
            "procedencia": procedencia,
            "base": {"run_id": r_base.run_id, "tokens": recibo.base_tokens,
                     "paso": r_base.gate.passed, "puerta": r_base.gate.detail},
            "lymi": {"run_id": r_lymi.run_id, "tokens": recibo.test_tokens,
                     "paso": r_lymi.gate.passed, "puerta": r_lymi.gate.detail},
            "ahorro": recibo.ahorro,
            "motivo": recibo.motivo_sin_ahorro,
            "local_tokens": recibo.local_tokens,
            "egress": recibo.egress,
            "cache_remota": recibo.cache_remota,
            "suscripcion": recibo.suscripcion,
            "sin_tarifa": recibo.sin_tarifa,
            "reproduce": "lymi bench snake" + (" --demo" if demo else ""),
        }
        self.evento(trabajo, "recibo listo")
        self._terminar(trabajo, "ok", resultado)

    # ------------------------------------------------------------ workflows

    def lanzar_workflow(self, ruta: Path, entradas: dict[str, Any]) -> dict[str, Any]:
        flujo = cargar(ruta)
        # Se validan ahora: un error de entradas se muestra en el formulario, no
        # como un trabajo fallido.
        preparar_inputs(flujo, entradas)
        trabajo = self._nuevo("workflow", flujo.name, {"archivo": ruta.name})
        # Se relee al correr: el archivo pudo cambiar desde que se valido.
        return self._lanzar(trabajo, lambda t: self._correr_flujo(t, lambda: cargar(ruta), entradas))

    def lanzar_flujo(
        self,
        flujo: Workflow,
        *,
        titulo: str,
        tipo: str = "flujo",
        contexto: dict[str, Any] | None = None,
        entradas: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Un workflow armado por la interfaz (un paso de correo, de web...)."""
        preparar_inputs(flujo, entradas or {})
        trabajo = self._nuevo(tipo, titulo, contexto)
        return self._lanzar(trabajo, lambda t: self._correr_flujo(t, lambda: flujo, entradas or {}))

    def _correr_flujo(self, trabajo: Trabajo, obtener: Callable[[], Workflow], entradas: dict[str, Any]) -> None:
        flujo = obtener()
        with self._lock:
            trabajo.pasos = {p.id: {"estado": "pendiente", "detalle": ""} for p in flujo.steps}
        local, etiqueta_local, remoto, etiqueta_remota = self.proveedores()
        self.evento(
            trabajo,
            f"local: {etiqueta_local or 'no disponible'} · remoto: {etiqueta_remota or 'no disponible'}",
        )
        memoria = MemoriaAprobaciones(self._memoria)

        def avisar(paso: str, estado: str, detalle: str) -> None:
            with self._lock:
                trabajo.pasos[paso] = {"estado": estado, "detalle": detalle}

        ledger = Ledger(self.ledger)
        try:
            resultado = asyncio.run(
                ejecutar_flujo(
                    flujo, entradas, ledger=ledger, local=local, remote=remoto,
                    aprobar=self._aprobador(trabajo, memoria), politica=Politica(memoria=memoria),
                    variante="ui", avisar=avisar,
                )
            )
            totales = ledger.totals(resultado.run_id) or {}
        finally:
            ledger.close()

        pasos = [
            {"id": e.id, "estado": e.status, "detalle": e.detalle, "duracion_ms": e.duracion_ms}
            for e in resultado.pasos
        ]
        salidas = {k: v for k, v in resultado.salidas.items() if v is not None}
        self.evento(trabajo, "terminado" if resultado.ok else f"detenido: {resultado.detalle}")
        self._terminar(
            trabajo,
            "ok" if resultado.ok else "fallo",
            {
                "tipo": "workflow",
                "run_id": resultado.run_id,
                "ok": resultado.ok,
                "detalle": resultado.detalle,
                "pasos": pasos,
                "salidas": {k: _recortar(v) for k, v in salidas.items()},
                "datos": _acotar(salidas),
                "totales": {k: totales.get(k) for k in _TOTALES},
            },
        )

    # ------------------------------------------------------------ agencia

    def lanzar_agencia(
        self,
        agencia: Any,
        texto: str,
        *,
        titulo: str,
        tipo: str = "agencia",
        agente: str | None = None,
        contexto: dict[str, Any] | None = None,
        al_terminar: Callable[[dict[str, Any]], None] | None = None,
        modelos: tuple[str | None, str | None] = (None, None),
    ) -> dict[str, Any]:
        """`modelos`: (local, remoto) elegidos en la interfaz; None es el configurado en lymi."""
        trabajo = self._nuevo(tipo, titulo, contexto)
        return self._lanzar(
            trabajo, lambda t: self._correr_agencia(t, agencia, texto, agente, modelos), al_terminar
        )

    def _correr_agencia(
        self, trabajo: Trabajo, agencia: Any, texto: str, agente: str | None,
        modelos: tuple[str | None, str | None] = (None, None),
    ) -> None:
        from lymi.agencia import correr_agencia

        local, etiqueta_local, remoto, etiqueta_remota = self.proveedores(*modelos)
        self.evento(
            trabajo,
            f"local: {etiqueta_local or 'no disponible'} · remoto: {etiqueta_remota or 'no disponible'}",
        )
        memoria = MemoriaAprobaciones(self._memoria)
        ledger = Ledger(self.ledger)
        try:
            r = asyncio.run(
                correr_agencia(
                    agencia, texto, ledger=ledger, local=local, remote=remoto, agente=agente,
                    aprobar=self._aprobador(trabajo, memoria), politica=Politica(memoria=memoria),
                    tiempo_aprobacion=self._vencimiento, avisar=lambda texto: self.evento(trabajo, texto),
                )
            )
            totales = ledger.totals(r.run_id) or {}
        finally:
            ledger.close()
        self.evento(trabajo, f"{r.agente}: {'terminado' if r.ok else r.detalle}")
        self._terminar(
            trabajo,
            "ok" if r.ok else "fallo",
            {
                "tipo": "agencia",
                "run_id": r.run_id,
                "ok": r.ok,
                "agente": r.agente,
                "ruta": r.motivo_ruta,
                "resultado": r.resultado,
                "detalle": r.detalle,
                "tareas": [t.resumen() for t in r.tareas],
                "max_simultaneos": r.max_simultaneos,
                "totales": {k: totales.get(k) for k in _TOTALES},
            },
        )

    # ------------------------------------------------------------ funciones sueltas

    def lanzar_funcion(
        self,
        tipo: str,
        titulo: str,
        objetivo: Callable[[Trabajo], dict[str, Any]],
        *,
        contexto: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Algo que no es un workflow pero si llama a un modelo: `objetivo` devuelve el resultado."""
        trabajo = self._nuevo(tipo, titulo, contexto)

        def correr(t: Trabajo) -> None:
            resultado = objetivo(t)
            self._terminar(t, "ok" if resultado.get("ok", True) else "fallo", {"tipo": tipo, **resultado})

        return self._lanzar(trabajo, correr)
