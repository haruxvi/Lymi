"""Agenda de workflows programados.

Guarda en SQLite que workflow corre, cuando, con que entradas y que efectos
quedan preaprobados.

Dos decisiones:

- **Todo se valida al programar**, no al ejecutar: el workflow, la expresion cron,
  la zona horaria, las entradas y los pasos preaprobados. Un error se descubre
  cuando alguien lo esta mirando, no a las tres de la manana.
- **Un workflow programado no puede pedir aprobacion en el momento.** Quien lo
  programa autoriza de antemano, paso por paso, los efectos que puede ejecutar
  sin nadie delante. Cualquier otro efecto se rechaza.

Sin recuperacion de ejecuciones perdidas: si la maquina estuvo apagada tres dias,
el workflow corre una vez y la siguiente se calcula desde ese momento. Disparar
de golpe tres dias de avisos atrasados casi nunca es lo que alguien quiere.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lymi.flows.engine import EntradaError, preparar_inputs
from lymi.flows.schema import WorkflowError, cargar
from lymi.triggers.cron import CronError, parsear, zona_horaria
from lymi.triggers.politica import (
    aprobador_desatendido,
    efectos_sin_autorizar,
    validar_preaprobados,
)

__all__ = ["Agenda", "AgendaError", "Programacion", "aprobador_desatendido"]

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS agenda (
    id        TEXT PRIMARY KEY,
    workflow  TEXT NOT NULL,
    cron      TEXT NOT NULL,
    zona      TEXT NOT NULL DEFAULT 'UTC',
    entradas  TEXT NOT NULL DEFAULT '{}',
    aprobados TEXT NOT NULL DEFAULT '[]',
    activo    INTEGER NOT NULL DEFAULT 1,
    creado    TEXT NOT NULL,
    ultima    TEXT,
    proxima   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agenda_pendientes ON agenda(activo, proxima);
"""


class AgendaError(ValueError):
    """La programacion no es valida. El mensaje dice por que."""


def _iso(momento: datetime) -> str:
    # Formato unico en UTC: asi las comparaciones de texto en SQLite ordenan bien.
    return momento.astimezone(UTC).isoformat(timespec="seconds")


def _fecha(texto: str | None) -> datetime | None:
    return None if texto is None else datetime.fromisoformat(texto)


@dataclass(frozen=True, slots=True)
class Programacion:
    id: str
    workflow: Path
    cron: str
    zona: str
    entradas: dict[str, Any]
    aprobados: frozenset[str]
    activo: bool
    ultima: datetime | None
    proxima: datetime


class Agenda:
    """Programaciones persistentes en SQLite."""

    def __init__(self, ruta: str | Path) -> None:
        self.ruta = Path(ruta)
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.ruta, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_ESQUEMA)

    def close(self) -> None:
        self._conn.close()

    def _programacion(self, fila: sqlite3.Row) -> Programacion:
        proxima = _fecha(fila["proxima"])
        assert proxima is not None  # la columna es NOT NULL
        return Programacion(
            id=fila["id"],
            workflow=Path(fila["workflow"]),
            cron=fila["cron"],
            zona=fila["zona"],
            entradas=json.loads(fila["entradas"]),
            aprobados=frozenset(json.loads(fila["aprobados"])),
            activo=bool(fila["activo"]),
            ultima=_fecha(fila["ultima"]),
            proxima=proxima,
        )

    def obtener(self, id_: str) -> Programacion:
        fila = self._conn.execute("SELECT * FROM agenda WHERE id = ?", (id_,)).fetchone()
        if fila is None:
            raise AgendaError(f"no hay ninguna programacion con id {id_!r}")
        return self._programacion(fila)

    def agregar(
        self,
        workflow: str | Path,
        expresion: str,
        *,
        zona: str = "UTC",
        entradas: dict[str, Any] | None = None,
        aprobados: list[str] | None = None,
        ahora: datetime | None = None,
    ) -> Programacion:
        """Programa un workflow. Valida todo antes de guardar nada."""
        ruta = Path(workflow).resolve()
        try:
            flujo = cargar(ruta)
        except WorkflowError as exc:
            raise AgendaError(str(exc)) from None

        try:
            cron = parsear(expresion)
            tz = zona_horaria(zona)
        except CronError as exc:
            raise AgendaError(str(exc)) from None

        valores = dict(entradas or {})
        try:
            preparar_inputs(flujo, valores)
        except EntradaError as exc:
            raise AgendaError(f"entradas: {exc}") from None

        try:
            autorizados = validar_preaprobados(flujo, aprobados or [])
        except ValueError as exc:
            raise AgendaError(str(exc)) from None

        ahora = ahora or datetime.now(UTC)
        try:
            proxima = cron.siguiente(ahora, tz)
        except CronError as exc:
            raise AgendaError(str(exc)) from None

        id_ = uuid.uuid4().hex[:10]
        self._conn.execute(
            "INSERT INTO agenda (id, workflow, cron, zona, entradas, aprobados, activo, creado, proxima)"
            " VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)",
            (
                id_, str(ruta), cron.expresion, zona or "UTC",
                json.dumps(valores, ensure_ascii=False), json.dumps(sorted(autorizados)),
                _iso(ahora), _iso(proxima),
            ),
        )
        return self.obtener(id_)

    def efectos_sin_autorizar(self, prog: Programacion) -> list[str]:
        """Pasos con efectos que esta programacion rechazara si llegan a ejecutarse."""
        return efectos_sin_autorizar(cargar(prog.workflow), prog.aprobados)

    def listar(self) -> list[Programacion]:
        filas = self._conn.execute("SELECT * FROM agenda ORDER BY proxima").fetchall()
        return [self._programacion(f) for f in filas]

    def quitar(self, id_: str) -> None:
        if self._conn.execute("DELETE FROM agenda WHERE id = ?", (id_,)).rowcount == 0:
            raise AgendaError(f"no hay ninguna programacion con id {id_!r}")

    def pausar(self, id_: str) -> Programacion:
        self.obtener(id_)
        self._conn.execute("UPDATE agenda SET activo = 0 WHERE id = ?", (id_,))
        return self.obtener(id_)

    def reanudar(self, id_: str, *, ahora: datetime | None = None) -> Programacion:
        prog = self.obtener(id_)
        ahora = ahora or datetime.now(UTC)
        # Desde ahora: reanudar no debe disparar al instante una hora que ya paso.
        proxima = parsear(prog.cron).siguiente(ahora, zona_horaria(prog.zona))
        self._conn.execute("UPDATE agenda SET activo = 1, proxima = ? WHERE id = ?", (_iso(proxima), id_))
        return self.obtener(id_)

    def vencidas(self, ahora: datetime) -> list[Programacion]:
        filas = self._conn.execute(
            "SELECT * FROM agenda WHERE activo = 1 AND proxima <= ? ORDER BY proxima", (_iso(ahora),)
        ).fetchall()
        return [self._programacion(f) for f in filas]

    def marcar_ejecutada(self, id_: str, momento: datetime) -> Programacion:
        """Registra una ejecucion y calcula la siguiente desde ese momento."""
        prog = self.obtener(id_)
        proxima = parsear(prog.cron).siguiente(momento, zona_horaria(prog.zona))
        self._conn.execute(
            "UPDATE agenda SET ultima = ?, proxima = ? WHERE id = ?", (_iso(momento), _iso(proxima), id_)
        )
        return self.obtener(id_)
