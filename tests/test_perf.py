"""Pruebas de rendimiento del ledger.

El ledger se interpone en cada llamada a un modelo. Si su overhead fuera
significativo, el instrumento estaria distorsionando lo que mide. Los limites son
holgados a proposito: detectan una regresion de orden de magnitud, no ruido de la
maquina.
"""

from __future__ import annotations

import time

import pytest

from lymi.ledger import Billing, CallRecord, Ledger

#: Overhead maximo por llamada registrada. Una llamada a un modelo tarda cientos
#: de milisegundos; 1 ms de registro es ruido (menos del 0.5%).
MAX_MS_POR_REGISTRO = 1.0


@pytest.fixture
def ledger(tmp_path):
    led = Ledger(tmp_path / "perf.sqlite3")
    yield led
    led.close()


def test_registro_de_llamadas_es_despreciable(ledger: Ledger) -> None:
    n = 2_000
    call = CallRecord(
        provider="anthropic",
        model="claude-opus-5",
        billing=Billing.API,
        input_tokens=1000,
        output_tokens=200,
    )
    with ledger.run("perf", "escritura", Billing.API) as run:
        started = time.perf_counter()
        for _ in range(n):
            run.record(call)
        elapsed_ms = (time.perf_counter() - started) * 1000

    por_llamada = elapsed_ms / n
    assert por_llamada < MAX_MS_POR_REGISTRO, (
        f"{por_llamada:.3f} ms por registro supera el limite de {MAX_MS_POR_REGISTRO} ms"
    )


def test_hashear_payload_grande_no_domina(ledger: Ledger) -> None:
    # 1 MB de payload: el caso realista de volcar un archivo grande al modelo.
    grande = "x" * 1_000_000
    call = CallRecord(
        provider="anthropic",
        model="claude-opus-5",
        billing=Billing.API,
        payload=grande,
        egress=True,
    )
    with ledger.run("perf", "hash", Billing.API) as run:
        started = time.perf_counter()
        for _ in range(20):
            run.record(call)
        elapsed_ms = (time.perf_counter() - started) * 1000
    assert elapsed_ms / 20 < 25.0, f"{elapsed_ms / 20:.1f} ms por payload de 1 MB"


def test_vista_de_totales_escala(ledger: Ledger) -> None:
    # La vista agrega. Si hiciera un scan completo del historial, el reporte se
    # volveria inusable a medida que se acumulan corridas.
    call = CallRecord(
        provider="anthropic", model="claude-opus-5", billing=Billing.API, input_tokens=100
    )
    with ledger.run("perf", "totales", Billing.API) as run:
        for _ in range(5_000):
            run.record(call)

    started = time.perf_counter()
    totales = ledger.totals(run.run_id)
    elapsed_ms = (time.perf_counter() - started) * 1000
    assert totales["n_calls"] == 5_000
    assert elapsed_ms < 100.0, f"la vista tardo {elapsed_ms:.1f} ms"
