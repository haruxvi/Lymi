"""Registro de webhooks entrantes.

El secreto de cada webhook vive en el almacen de credenciales del sistema, no en
la base de datos: quien copie el archivo SQLite no puede firmar disparos. Se
muestra una sola vez, al crearlo o al rotarlo.
"""

from __future__ import annotations

import json
import re
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

import keyring
from keyring.errors import KeyringError, PasswordDeleteError

from lymi.flows.schema import cargar
from lymi.triggers.politica import validar_preaprobados

SERVICIO = "lymi-webhooks"
ESQUEMAS = ("lymi", "github")
Esquema = Literal["lymi", "github"]

_NOMBRE = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")

_SQL = """
CREATE TABLE IF NOT EXISTS ganchos (
    nombre    TEXT PRIMARY KEY,
    workflow  TEXT NOT NULL,
    esquema   TEXT NOT NULL DEFAULT 'lymi',
    aprobados TEXT NOT NULL DEFAULT '[]',
    activo    INTEGER NOT NULL DEFAULT 1,
    creado    TEXT NOT NULL
);
"""


class GanchoError(ValueError):
    """Operacion invalida sobre un webhook. El mensaje dice por que."""


@dataclass(frozen=True, slots=True)
class Gancho:
    nombre: str
    workflow: Path
    esquema: Esquema
    aprobados: frozenset[str]
    activo: bool


class Ganchos:
    """Webhooks persistentes. Metadatos en SQLite; secretos en el almacen del sistema."""

    def __init__(self, ruta: str | Path, *, servicio: str = SERVICIO) -> None:
        self.ruta = Path(ruta)
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        self._servicio = servicio
        self._conn = sqlite3.connect(self.ruta, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SQL)

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------ secretos

    def _guardar_secreto(self, nombre: str, valor: str) -> None:
        try:
            keyring.set_password(self._servicio, nombre, valor)
        except KeyringError as exc:
            raise GanchoError(
                f"no se pudo guardar el secreto en el almacen de credenciales ({type(exc).__name__})"
            ) from None

    def _borrar_secreto(self, nombre: str) -> None:
        try:
            keyring.delete_password(self._servicio, nombre)
        except PasswordDeleteError:
            pass
        except KeyringError as exc:
            raise GanchoError(
                f"no se pudo borrar el secreto del almacen de credenciales ({type(exc).__name__})"
            ) from None

    def secreto(self, nombre: str) -> bytes | None:
        """Secreto de un webhook, o None si no hay (o el almacen no responde)."""
        try:
            valor = keyring.get_password(self._servicio, nombre)
        except KeyringError:
            return None
        return None if valor is None else valor.encode()

    # ------------------------------------------------------------ webhooks

    def _gancho(self, fila: sqlite3.Row) -> Gancho:
        return Gancho(
            nombre=fila["nombre"],
            workflow=Path(fila["workflow"]),
            esquema=cast(Esquema, fila["esquema"]),
            aprobados=frozenset(json.loads(fila["aprobados"])),
            activo=bool(fila["activo"]),
        )

    def obtener(self, nombre: str) -> Gancho | None:
        fila = self._conn.execute("SELECT * FROM ganchos WHERE nombre = ?", (nombre,)).fetchone()
        return None if fila is None else self._gancho(fila)

    def listar(self) -> list[Gancho]:
        filas = self._conn.execute("SELECT * FROM ganchos ORDER BY nombre").fetchall()
        return [self._gancho(f) for f in filas]

    def crear(
        self,
        nombre: str,
        workflow: str | Path,
        *,
        esquema: str = "lymi",
        aprobados: list[str] | None = None,
    ) -> tuple[Gancho, str]:
        """Crea un webhook. Devuelve el secreto: es la unica vez que se entrega."""
        if not _NOMBRE.fullmatch(nombre):
            raise GanchoError(f"nombre invalido {nombre!r}: minusculas, digitos, - y _, empezando por letra")
        if esquema not in ESQUEMAS:
            raise GanchoError(f"esquema {esquema!r} no soportado (lymi o github)")
        if self.obtener(nombre) is not None:
            raise GanchoError(f"ya existe un webhook llamado {nombre!r}")

        ruta = Path(workflow).resolve()
        try:
            autorizados = validar_preaprobados(cargar(ruta), aprobados or [])
        except ValueError as exc:
            raise GanchoError(str(exc)) from None

        secreto = secrets.token_urlsafe(48)
        self._guardar_secreto(nombre, secreto)
        try:
            self._conn.execute(
                "INSERT INTO ganchos (nombre, workflow, esquema, aprobados, activo, creado)"
                " VALUES (?, ?, ?, ?, 1, ?)",
                (nombre, str(ruta), esquema, json.dumps(sorted(autorizados)),
                 datetime.now(UTC).isoformat(timespec="seconds")),
            )
        except sqlite3.Error:
            self._borrar_secreto(nombre)  # sin fila, el secreto quedaria huerfano
            raise

        gancho = self.obtener(nombre)
        assert gancho is not None
        return gancho, secreto

    def rotar(self, nombre: str) -> str:
        """Reemplaza el secreto. El anterior deja de servir al instante."""
        if self.obtener(nombre) is None:
            raise GanchoError(f"no existe el webhook {nombre!r}")
        secreto = secrets.token_urlsafe(48)
        self._guardar_secreto(nombre, secreto)
        return secreto

    def activar(self, nombre: str, activo: bool) -> Gancho:
        if self._conn.execute("UPDATE ganchos SET activo = ? WHERE nombre = ?", (int(activo), nombre)).rowcount == 0:
            raise GanchoError(f"no existe el webhook {nombre!r}")
        gancho = self.obtener(nombre)
        assert gancho is not None
        return gancho

    def quitar(self, nombre: str) -> None:
        if self._conn.execute("DELETE FROM ganchos WHERE nombre = ?", (nombre,)).rowcount == 0:
            raise GanchoError(f"no existe el webhook {nombre!r}")
        self._borrar_secreto(nombre)
