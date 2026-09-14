"""Ejecucion de tareas del banco de pruebas.

Una ESTRATEGIA es una forma de resolver una tarea (el agente ingenuo, lymi con
cache, lymi con tier local...). El runner las ejecuta contra la misma tarea y la
misma puerta, y deja todo registrado en el ledger.

Todas las estrategias comparten runner, tarea y puerta: si la comparacion fuera
entre codigos distintos, no seria una comparacion.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from lymi.bench.tasks import GateResult, Task
from lymi.ledger import Billing, CallRecord, Ledger, RunHandle
from lymi.providers.base import Completion, Message


@dataclass(slots=True)
class RunOutcome:
    """Lo que produjo una corrida: identidad, veredicto y consumo."""

    run_id: str
    task_id: str
    variant: str
    gate: GateResult
    totals: dict


class Recorder:
    """Envoltura que obliga a registrar cada llamada.

    Las estrategias no hablan con los clientes directamente: hablan con esto. Asi
    una llamada sin registrar deja de ser un descuido posible y pasa a ser
    imposible por construccion.
    """

    def __init__(self, run: RunHandle) -> None:
        self._run = run

    def call(
        self,
        client,
        messages: list[Message],
        *,
        purpose: str,
        system: str | None = None,
        max_tokens: int = 16000,
        cache_system: bool = False,
        egress: bool | None = None,
    ) -> Completion:
        """Ejecuta una llamada y la registra. Devuelve la respuesta."""
        completion = client.complete(
            messages, system=system, max_tokens=max_tokens, cache_system=cache_system
        )
        self.registrar(completion, messages, purpose=purpose, system=system, egress=egress)
        return completion

    def registrar(
        self,
        completion: Completion,
        messages: list[Message],
        *,
        purpose: str,
        system: str | None = None,
        egress: bool | None = None,
    ) -> None:
        """Registra una respuesta ya obtenida.

        Separado de `call` para el motor de workflows: la llamada al modelo corre
        en un hilo, pero SQLite exige escribir desde el hilo que abrio la conexion.
        """
        u = completion.usage

        # El egress se deduce del modo de facturacion salvo que se indique: lo
        # local no sale de la maquina, todo lo demas si.
        if egress is None:
            egress = completion.billing is not Billing.LOCAL

        payload = None
        if egress:
            payload = (system or "") + "\n".join(m.content for m in messages)

        self._run.record(
            CallRecord(
                provider=completion.provider,
                model=completion.model,
                billing=completion.billing,
                tier=completion.tier,
                purpose=purpose,
                input_tokens=u.input_tokens,
                output_tokens=u.output_tokens,
                cache_read_tokens=u.cache_read_tokens,
                cache_write_tokens=u.cache_write_tokens,
                latency_ms=completion.latency_ms,
                egress=egress,
                payload=payload,
            )
        )


    def integracion(
        self,
        *,
        tipo: str,
        destino: str,
        proposito: str,
        payload: str | None,
        latencia_ms: int,
        ok: bool = True,
        error: str | None = None,
    ) -> None:
        """Registra una llamada que no es a un modelo: HTTP o herramienta MCP.

        Se marca como egress siempre. Un servidor MCP es un proceso ajeno que
        puede llamar a internet sin que lymi lo vea; para un log de auditoria lo
        honesto es asumir que el dato salio, no que se quedo.
        """
        self._run.record(
            CallRecord(
                provider=tipo,
                model=destino,
                billing=Billing.NONE,
                tier="integracion",
                purpose=proposito,
                latency_ms=latencia_ms,
                ok=ok,
                error=error,
                egress=True,
                payload=payload,
            )
        )


@runtime_checkable
class Strategy(Protocol):
    """Una forma de resolver tareas. El objeto de estudio del banco de pruebas."""

    name: str
    billing: Billing

    def solve(self, task: Task, rec: Recorder) -> str:
        """Resuelve la tarea usando `rec` para toda llamada a un modelo."""
        ...


def run_task(ledger: Ledger, task: Task, strategy: Strategy) -> RunOutcome:
    """Corre una tarea con una estrategia y devuelve el resultado medido."""
    with ledger.run(task.id, strategy.name, strategy.billing) as run:
        rec = Recorder(run)
        salida = strategy.solve(task, rec)
        veredicto = task.gate(salida)
        run.score = veredicto.score
        if not veredicto.passed:
            run.fail(veredicto.detail)
        run.notes = veredicto.detail

    return RunOutcome(
        run_id=run.run_id,
        task_id=task.id,
        variant=strategy.name,
        gate=veredicto,
        totals=ledger.totals(run.run_id) or {},
    )
