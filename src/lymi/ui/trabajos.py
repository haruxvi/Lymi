"""Trabajos en segundo plano de la interfaz: el bench y los workflows.

Cada trabajo corre en su propio hilo, con su propia conexion al ledger: SQLite no
comparte conexiones entre hilos. La interfaz consulta el estado por sondeo.

Las aprobaciones de un workflow se resuelven desde el navegador: el aprobador
publica la solicitud en el trabajo y espera la decision con vencimiento. Un
vencimiento cuenta como rechazo, igual que en la terminal.
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
from lymi.flows.schema import cargar
from lymi.ledger import Ledger

VENCIMIENTO_APROBACION = 300.0
MAX_EVENTOS = 200
MAX_SIMULTANEOS = 2
LIMITE_SALIDA = 4000
"""Caracteres maximos de cada salida de paso que se devuelven a la pagina."""

DECISIONES = frozenset({"aprobar", "rechazar", "siempre"})
_ACTIVOS = frozenset({"en_curso", "esperando"})


class TrabajoError(RuntimeError):
    """El trabajo no se puede lanzar o la operacion no aplica a su estado."""


def _hora() -> str:
    return datetime.now(UTC).astimezone().strftime("%H:%M:%S")


@dataclass(slots=True)
class Trabajo:
    id: str
    tipo: str
    """bench | workflow"""
    titulo: str
    estado: str = "en_curso"
    """en_curso | esperando | ok | fallo | error"""
    eventos: list[str] = field(default_factory=list)
    pendiente: dict[str, Any] | None = None
    resultado: dict[str, Any] | None = None
    creado: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))
    decision: str | None = None
    hay_decision: threading.Event = field(default_factory=threading.Event)

    def vista(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tipo": self.tipo,
            "titulo": self.titulo,
            "estado": self.estado,
            "eventos": list(self.eventos),
            "pendiente": dict(self.pendiente) if self.pendiente else None,
            "resultado": self.resultado,
            "creado": self.creado,
        }


def _recortar(valor: Any) -> Any:
    texto = valor if isinstance(valor, str) else json.dumps(valor, ensure_ascii=False, default=str)
    return texto if len(texto) <= LIMITE_SALIDA else texto[:LIMITE_SALIDA] + " […]"


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
    ) -> None:
        self._ledger = ledger
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

    # ------------------------------------------------------------ ciclo de vida

    def _nuevo(self, tipo: str, titulo: str) -> Trabajo:
        with self._lock:
            activos = [t for t in self._trabajos.values() if t.estado in _ACTIVOS]
            if tipo == "bench" and any(t.tipo == "bench" for t in activos):
                raise TrabajoError("ya hay una medicion en curso: dos a la vez se pisarian la cache")
            if len(activos) >= self._max:
                raise TrabajoError("ya hay trabajos en curso; espera a que terminen")
            trabajo = Trabajo(uuid.uuid4().hex[:10], tipo, titulo)
            self._trabajos[trabajo.id] = trabajo
            return trabajo

    def _evento(self, trabajo: Trabajo, texto: str) -> None:
        with self._lock:
            trabajo.eventos.append(f"{_hora()}  {texto}")
            del trabajo.eventos[:-MAX_EVENTOS]

    def _terminar(self, trabajo: Trabajo, estado: str, resultado: dict[str, Any] | None) -> None:
        with self._lock:
            trabajo.estado = estado
            trabajo.resultado = resultado
            trabajo.pendiente = None

    def _lanzar(self, trabajo: Trabajo, objetivo: Callable[[Trabajo], None]) -> None:
        def envolver() -> None:
            try:
                objetivo(trabajo)
            except Exception as exc:  # noqa: BLE001 - todo fallo se muestra en la pagina
                self._evento(trabajo, f"error: {type(exc).__name__}: {exc}")
                self._terminar(trabajo, "error", {"tipo": "error", "detalle": f"{exc}"})

        hilo = threading.Thread(target=envolver, name=f"lymi-{trabajo.tipo}-{trabajo.id}", daemon=True)
        hilo.start()

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

    # ------------------------------------------------------------ bench

    def lanzar_bench(self, *, demo: bool, calentar: bool, confirmar: bool) -> dict[str, Any]:
        if not demo and not confirmar:
            raise ValueError("una medicion real gasta tokens de tu proveedor: confirma para lanzarla")
        titulo = "Snake en Python" + (" · demo" if demo else "")
        trabajo = self._nuevo("bench", titulo)
        self._lanzar(trabajo, lambda t: self._correr_bench(t, demo=demo, calentar=calentar))
        return trabajo.vista()

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
        self._evento(trabajo, f"proveedores: {procedencia}")

        ledger = Ledger(self._ledger)
        try:
            if calentar and not demo:
                self._evento(trabajo, "calentando la cache del proveedor (llamada minima, registrada aparte)")
                calentar_cache(ledger, objetivo, base.remote, system=SISTEMA)
            self._evento(trabajo, "[1/2] linea base: esperando al modelo remoto")
            r_base = run_task(ledger, objetivo, base)
            self._evento(trabajo, f"linea base: {r_base.gate.detail}")
            self._evento(trabajo, "[2/2] lymi: destilando en local y consultando al remoto")
            r_lymi = run_task(ledger, objetivo, lymi)
            self._evento(trabajo, f"lymi: {r_lymi.gate.detail}")
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
        self._evento(trabajo, "recibo listo")
        self._terminar(trabajo, "ok", resultado)

    # ------------------------------------------------------------ workflows

    def lanzar_workflow(self, ruta: Path, entradas: dict[str, Any]) -> dict[str, Any]:
        flujo = cargar(ruta)
        # Se validan ahora: un error de entradas se muestra en el formulario, no
        # como un trabajo fallido.
        preparar_inputs(flujo, entradas)
        trabajo = self._nuevo("workflow", flujo.name)
        self._lanzar(trabajo, lambda t: self._correr_workflow(t, ruta, entradas))
        return trabajo.vista()

    def _correr_workflow(self, trabajo: Trabajo, ruta: Path, entradas: dict[str, Any]) -> None:
        flujo = cargar(ruta)  # se relee: el archivo pudo cambiar desde que se valido
        if self._proveedores is None:
            from lymi.bench.wiring import proveedores
        else:
            proveedores = self._proveedores
        local, etiqueta_local, remoto, etiqueta_remota = proveedores()
        self._evento(
            trabajo,
            f"local: {etiqueta_local or 'no disponible'} · remoto: {etiqueta_remota or 'no disponible'}",
        )
        memoria = MemoriaAprobaciones(self._memoria)

        def aprobar(paso_id: str, vista: str, solicitud: Solicitud) -> bool:
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
            self._evento(trabajo, f"{paso_id} pide aprobacion para {solicitud.destino}")

            llego = trabajo.hay_decision.wait(self._vencimiento)
            with self._lock:
                decision = trabajo.decision if llego else None
                trabajo.pendiente = None
                trabajo.estado = "en_curso"

            if decision is None:
                self._evento(trabajo, f"{paso_id}: la aprobacion vencio sin respuesta")
                return False
            if decision == "siempre":
                try:
                    hasta = memoria.recordar(solicitud.destino, solicitud.metodo, Decision.APROBAR)
                    self._evento(trabajo, f"{paso_id}: aprobado y recordado hasta {hasta:%Y-%m-%d}")
                except ReglaError as exc:
                    self._evento(trabajo, f"{paso_id}: aprobado solo esta vez ({exc})")
                return True
            self._evento(trabajo, f"{paso_id}: {'aprobado' if decision == 'aprobar' else 'rechazado'}")
            return decision == "aprobar"

        ledger = Ledger(self._ledger)
        try:
            resultado = asyncio.run(
                ejecutar_flujo(
                    flujo, entradas, ledger=ledger, local=local, remote=remoto,
                    aprobar=aprobar, politica=Politica(memoria=memoria), variante="ui",
                )
            )
            totales = ledger.totals(resultado.run_id) or {}
        finally:
            ledger.close()

        pasos = [
            {"id": e.id, "estado": e.status, "detalle": e.detalle, "duracion_ms": e.duracion_ms}
            for e in resultado.pasos
        ]
        claves = ("remote_tokens", "local_tokens", "egress_calls", "cost_usd", "billing_mode")
        self._evento(trabajo, "terminado" if resultado.ok else f"detenido: {resultado.detalle}")
        self._terminar(
            trabajo,
            "ok" if resultado.ok else "fallo",
            {
                "tipo": "workflow",
                "run_id": resultado.run_id,
                "ok": resultado.ok,
                "detalle": resultado.detalle,
                "pasos": pasos,
                "salidas": {k: _recortar(v) for k, v in resultado.salidas.items() if v is not None},
                "totales": {k: totales.get(k) for k in claves},
            },
        )
