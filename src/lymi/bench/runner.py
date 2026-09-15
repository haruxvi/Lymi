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
from lymi.control import Presupuesto, verificar_parada
from lymi.ledger import Billing, CallRecord, Ledger, RunHandle
from lymi.privacidad import EgressBloqueado, Redactor, sanear
from lymi.privacidad.etiquetas import fragmentos_protegidos
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

    def __init__(
        self,
        run: RunHandle,
        *,
        presupuesto: Presupuesto | None = None,
        redactar: bool = True,
        protegidos: tuple[str, ...] = (),
    ) -> None:
        self._run = run
        self._presupuesto = presupuesto
        self._redactar = redactar
        self._protegidos = tuple(p for p in protegidos if p)

    def proteger(self, contenido: str) -> None:
        """Agrega un contenido `nunca-sale` descubierto durante la corrida (ej. leido del PC)."""
        self._protegidos = (*self._protegidos, *fragmentos_protegidos(contenido))

    def accion_local(
        self,
        *,
        tipo: str,
        destino: str,
        proposito: str,
        latencia_ms: int,
        ok: bool = True,
        error: str | None = None,
    ) -> None:
        """Registra una accion que no sale de la maquina: el ejecutor del host."""
        self._run.record(
            CallRecord(
                provider=tipo, model=destino, billing=Billing.NONE, tier="local", purpose=proposito,
                latency_ms=latencia_ms, ok=ok, error=error, egress=False,
            )
        )

    def verificar_protegido(self, texto: str) -> None:
        """Bloquea si el texto trae literal un contenido etiquetado `nunca-sale`."""
        if any(fragmento in texto for fragmento in self._protegidos):
            raise EgressBloqueado({"ARCHIVO_NUNCA_SALE"})

    def preparar(
        self, client, messages: list[Message], system: str | None
    ) -> tuple[list[Message], str | None, Redactor | None]:
        """La pasarela: lo que pasa antes de toda llamada a un modelo.

        1. Parada y presupuesto: si alguno corta, no se llama.
        2. Saneamiento de Unicode invisible, tambien hacia el modelo local: el que
           puede ser manipulado es el modelo, no la red.
        3. Redaccion reversible solo si el texto sale de la maquina. El egress que
           se registra es el texto redactado: lo que de verdad salio.
        """
        verificar_parada()
        if self._presupuesto is not None:
            self._presupuesto.verificar()
        mensajes = [Message(m.role, sanear(m.content).texto) for m in messages]
        sistema = sanear(system).texto if system is not None else None
        sale = getattr(client, "billing", Billing.API) is not Billing.LOCAL
        if sale:
            # Antes de redactar: la redaccion cambia el texto y el literal ya no coincidiria.
            for contenido in (*(m.content for m in mensajes), sistema or ""):
                self.verificar_protegido(contenido)
        if not (sale and self._redactar):
            return mensajes, sistema, None
        redactor = Redactor()
        mensajes = [Message(m.role, redactor.redactar(m.content)) for m in mensajes]
        sistema = redactor.redactar(sistema) if sistema is not None else None
        return mensajes, sistema, redactor

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
        """Ejecuta una llamada a traves de la pasarela y la registra."""
        enviados, sistema, redactor = self.preparar(client, messages, system)
        completion = client.complete(
            enviados, system=sistema, max_tokens=max_tokens, cache_system=cache_system
        )
        if redactor is not None:
            completion.text = redactor.rehidratar(completion.text)
        self.registrar(
            completion, enviados, purpose=purpose, system=sistema, egress=egress,
            redacciones=redactor.total if redactor is not None else 0,
        )
        return completion

    def registrar(
        self,
        completion: Completion,
        messages: list[Message],
        *,
        purpose: str,
        system: str | None = None,
        egress: bool | None = None,
        redacciones: int = 0,
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
                redacciones=redacciones,
            )
        )
        if self._presupuesto is not None:
            remotos = 0 if completion.billing is Billing.LOCAL else (
                u.input_tokens + u.output_tokens + u.cache_read_tokens + u.cache_write_tokens
            )
            self._presupuesto.sumar(remotos)


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


def calentar_cache(ledger: Ledger, task: Task, client, *, system: str) -> str:
    """Hace una llamada minima con el mismo prefijo que usaran las corridas.

    El proveedor cachea el prefijo estable (el sistema y, en Claude Code, el harness
    de ~28k tokens). Sin esto la linea base corre primero, escribe ese prefijo en
    cache y lymi lo lee barato: un ahorro del orden de ejecucion, no de lymi.
    Calentando antes, las dos corridas leen la misma cache.

    Queda en el ledger como corrida propia (variante `calentamiento`): gasta tokens
    de verdad y no se esconde, pero no se suma a ninguna estrategia.
    """
    with ledger.run(task.id, "calentamiento", getattr(client, "billing", Billing.API)) as run:
        Recorder(run).call(
            client,
            [Message("user", "Responde solo: ok")],
            purpose="calentar",
            system=system,
            max_tokens=16,
            cache_system=True,
        )
        run.notes = "calentamiento de cache: no cuenta para ninguna estrategia"
    return run.run_id


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
