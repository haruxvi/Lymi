"""Escritura y lectura del ledger.

Toda llamada a un modelo pasa por aqui. Es deliberadamente aburrido: SQLite,
sin ORM, sin magia. El valor esta en que sea imposible de eludir.
"""

from __future__ import annotations

import sqlite3
import subprocess
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from lymi.ledger.pricing import Billing, compute_cost

SCHEMA = Path(__file__).with_name("schema.sql")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _git_sha() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


@dataclass(slots=True)
class CallRecord:
    """Una llamada a un modelo, ya ejecutada."""

    provider: str
    model: str
    billing: Billing
    tier: str = "frontier"
    purpose: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    latency_ms: int | None = None
    ok: bool = True
    error: str | None = None
    egress: bool = False
    redacciones: int = 0
    """Secretos o datos personales reemplazados por marcadores antes de salir."""
    payload: str | None = field(default=None, repr=False)
    """Texto exacto enviado al proveedor. No se guarda: solo su hash y tamano.
    Asi el log de egress es auditable sin convertirse en una segunda copia de
    tus datos sensibles."""


class Ledger:
    """Base de datos de corridas y llamadas."""

    def __init__(self, db_path: str | Path = "runs/lymi.sqlite3") -> None:
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self._migrar()
        self.conn.executescript(SCHEMA.read_text(encoding="utf-8"))

    def close(self) -> None:
        self.conn.close()

    def _migrar(self) -> None:
        """Agrega columnas nuevas a bases creadas con un esquema anterior.

        Va antes del esquema: la vista `run_totals` se recrea al abrir y ya lee las
        columnas nuevas, asi que sobre una tabla vieja fallaria.
        """
        tablas = {f[0] for f in self.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "calls" not in tablas:
            return
        columnas = {f[1] for f in self.conn.execute("PRAGMA table_info(calls)")}
        if "redacciones" not in columnas:
            self.conn.execute("ALTER TABLE calls ADD COLUMN redacciones INTEGER NOT NULL DEFAULT 0")

    # ---------------- corridas ----------------

    def start_run(self, task_id: str, variant: str, billing: Billing) -> str:
        run_id = uuid.uuid4().hex[:12]
        self.conn.execute(
            "INSERT INTO runs (id, task_id, variant, billing_mode, started_at, git_sha)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, task_id, variant, str(billing), _now(), _git_sha()),
        )
        return run_id

    def finish_run(
        self, run_id: str, status: str, score: float | None = None, notes: str | None = None
    ) -> None:
        self.conn.execute(
            "UPDATE runs SET finished_at = ?, status = ?, score = ?, notes = ? WHERE id = ?",
            (_now(), status, score, notes, run_id),
        )

    @contextmanager
    def run(self, task_id: str, variant: str, billing: Billing) -> Iterator[RunHandle]:
        """Contexto que garantiza que la corrida quede cerrada, incluso si falla."""
        run_id = self.start_run(task_id, variant, billing)
        handle = RunHandle(self, run_id)
        try:
            yield handle
        except Exception as exc:
            self.finish_run(run_id, "error", handle.score, f"{type(exc).__name__}: {exc}")
            raise
        else:
            self.finish_run(run_id, handle.status, handle.score, handle.notes)

    # ---------------- lectura ----------------

    def totals(self, run_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM run_totals WHERE run_id = ?", (run_id,)
        ).fetchone()
        return dict(row) if row else None

    def totals_for(self, task_id: str, variant: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM run_totals WHERE task_id = ? AND variant = ?", (task_id, variant)
        ).fetchall()
        return [dict(r) for r in rows]


@dataclass(slots=True)
class RunHandle:
    """Handle de una corrida abierta. Registra cada llamada en orden."""

    ledger: Ledger
    run_id: str
    _seq: int = 0
    status: str = "passed"
    score: float | None = None
    notes: str | None = None

    def record(self, call: CallRecord) -> float | None:
        """Registra una llamada y devuelve su costo (None si no es comparable)."""
        self._seq += 1
        cost = compute_cost(
            call.model,
            call.billing,
            call.input_tokens,
            call.output_tokens,
            call.cache_read_tokens,
            call.cache_write_tokens,
        )
        digest = size = None
        if call.payload is not None:
            raw = call.payload.encode("utf-8")
            digest, size = sha256(raw).hexdigest(), len(raw)

        self.ledger.conn.execute(
            "INSERT INTO calls (run_id, seq, ts, provider, model, billing_mode, tier,"
            " purpose, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,"
            " cost_usd, latency_ms, ok, error, egress, payload_sha256, payload_bytes, redacciones)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                self.run_id, self._seq, _now(), call.provider, call.model,
                str(call.billing), call.tier, call.purpose,
                call.input_tokens, call.output_tokens,
                call.cache_read_tokens, call.cache_write_tokens,
                cost, call.latency_ms, int(call.ok), call.error,
                int(call.egress), digest, size, call.redacciones,
            ),
        )
        return cost

    def fail(self, reason: str) -> None:
        self.status, self.notes = "failed", reason
