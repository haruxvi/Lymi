"""Lecturas del ledger para la interfaz.

Solo lectura. Nunca devuelve payloads: el ledger no los guarda, y la interfaz no
va a ser el lugar donde eso cambie por descuido.
"""

from __future__ import annotations

from typing import Any

from lymi.ledger import Ledger

_COLUMNAS_LLAMADA = (
    "seq, ts, provider, model, billing_mode, tier, purpose, input_tokens, output_tokens,"
    " cache_read_tokens, cache_write_tokens, cost_usd, latency_ms, ok, error, egress,"
    " payload_sha256, payload_bytes, redacciones"
)


def resumen(ledger: Ledger) -> dict[str, Any]:
    """Totales de todo el ledger: lo que muestra la barra permanente."""
    fila = ledger.conn.execute(
        "SELECT COUNT(*) AS corridas,"
        " COALESCE(SUM(remote_tokens), 0) AS remote_tokens,"
        " COALESCE(SUM(local_tokens), 0) AS local_tokens,"
        " COALESCE(SUM(egress_calls), 0) AS egress_calls"
        " FROM run_totals"
    ).fetchone()
    return dict(fila)


def corridas(ledger: Ledger, limite: int = 50) -> list[dict[str, Any]]:
    filas = ledger.conn.execute(
        "SELECT t.*, r.started_at, r.finished_at, r.notes FROM run_totals t"
        " JOIN runs r ON r.id = t.run_id ORDER BY r.started_at DESC LIMIT ?",
        (limite,),
    ).fetchall()
    return [dict(f) for f in filas]


def corrida(ledger: Ledger, run_id: str) -> dict[str, Any] | None:
    totales = ledger.totals(run_id)
    if totales is None:
        return None
    meta = ledger.conn.execute(
        "SELECT started_at, finished_at, notes, git_sha FROM runs WHERE id = ?", (run_id,)
    ).fetchone()
    llamadas = ledger.conn.execute(
        f"SELECT {_COLUMNAS_LLAMADA} FROM calls WHERE run_id = ? ORDER BY seq", (run_id,)
    ).fetchall()
    return {**totales, **dict(meta), "llamadas": [dict(c) for c in llamadas]}


def egress(ledger: Ledger, limite: int = 200) -> list[dict[str, Any]]:
    """Cada llamada que saco datos de la maquina: destino, hash y tamano."""
    filas = ledger.conn.execute(
        "SELECT c.ts, c.provider, c.model, c.billing_mode, c.tier, c.purpose, c.ok,"
        " c.payload_sha256, c.payload_bytes, c.redacciones, c.run_id, r.task_id, r.variant"
        " FROM calls c JOIN runs r ON r.id = c.run_id"
        " WHERE c.egress = 1 ORDER BY c.ts DESC LIMIT ?",
        (limite,),
    ).fetchall()
    return [dict(f) for f in filas]
