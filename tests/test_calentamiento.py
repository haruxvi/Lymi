"""Pruebas del calentamiento de cache del bench.

Motivo: en la tercera corrida real la linea base escribio el prefijo del harness
en cache y lymi lo leyo barato. El recibo se nego a anunciar ahorro, con razon.
Calentar antes deja a las dos corridas en igualdad, sin esconder lo que cuesta.
"""

from __future__ import annotations

from lymi.bench.demo import SNAKE_SOLUCION
from lymi.bench.runner import calentar_cache, run_task
from lymi.bench.strategies import SISTEMA, BaselineAgent
from lymi.bench.tasks import SnakeTask
from lymi.ledger import Billing, Ledger
from lymi.providers.base import Completion, Usage
from lymi.providers.fake import ScriptedClient, ScriptedTurn


class Espia:
    provider = "espia"
    model = "claude-opus-5"
    billing = Billing.SUBSCRIPTION
    tier = "frontier"

    def __init__(self) -> None:
        self.llamadas: list[dict] = []

    def complete(self, messages, *, system=None, max_tokens=4096, cache_system=False) -> Completion:
        self.llamadas.append({"system": system, "max_tokens": max_tokens, "cache_system": cache_system})
        return Completion(
            text="ok",
            usage=Usage(input_tokens=5, output_tokens=1, cache_write_tokens=28_000),
            model=self.model, provider=self.provider, billing=self.billing, tier=self.tier, latency_ms=10,
        )


def test_queda_como_corrida_propia(tmp_path) -> None:
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    try:
        run_id = calentar_cache(ledger, SnakeTask(), Espia(), system=SISTEMA)
        corrida = ledger.conn.execute("SELECT variant, billing_mode FROM runs WHERE id = ?", (run_id,)).fetchone()
        llamada = ledger.conn.execute("SELECT purpose, egress FROM calls WHERE run_id = ?", (run_id,)).fetchone()
        totales = ledger.totals(run_id)
    finally:
        ledger.close()

    assert corrida["variant"] == "calentamiento"
    assert corrida["billing_mode"] == "subscription"
    assert llamada["purpose"] == "calentar"
    # Gasta tokens de verdad y sale de la maquina: se registra, no se esconde.
    assert llamada["egress"] == 1
    assert totales["remote_tokens"] == 28_006


def test_usa_el_mismo_prefijo_que_las_estrategias(tmp_path) -> None:
    espia = Espia()
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    try:
        calentar_cache(ledger, SnakeTask(), espia, system=SISTEMA)
    finally:
        ledger.close()

    (llamada,) = espia.llamadas
    assert llamada["system"] == SISTEMA
    assert llamada["cache_system"] is True
    assert llamada["max_tokens"] <= 32


def test_no_se_suma_a_la_corrida_de_la_estrategia(tmp_path) -> None:
    cliente = ScriptedClient([
        ScriptedTurn("ok", input_tokens=5, output_tokens=1),
        ScriptedTurn(SNAKE_SOLUCION, input_tokens=100, output_tokens=50),
    ])
    tarea = SnakeTask()
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    try:
        calentar_cache(ledger, tarea, cliente, system=SISTEMA)
        resultado = run_task(ledger, tarea, BaselineAgent(cliente))
    finally:
        ledger.close()

    assert resultado.gate.passed, resultado.gate.detail
    assert resultado.totals["remote_tokens"] == 150
