"""Aprobaciones ampliadas: reglas, decisiones recordadas y vencimiento.

Antes de preguntar a una persona por un paso con efectos, se consulta, en orden:

1. **Reglas explicitas**, la primera que coincide gana (como un cortafuegos).
2. **Decisiones recordadas** ("siempre para este destino"), con fecha de vencimiento.
3. Si nada decide: se pregunta, y la pregunta puede **vencer**.

Tres garantias:

- Las reglas se evaluan antes que la memoria: una regla que rechaza nunca queda
  anulada por una aprobacion recordada.
- Una regla que aprueba necesita paso o destino. "Aprobar todo" existe (`--yes`),
  pero se elige a sabiendas en cada corrida, no se guarda en un archivo olvidado.
- Una aprobacion que vence cuenta como rechazo.
"""

from __future__ import annotations

import asyncio
import inspect
import sqlite3
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

import yaml

COMODINES_TOTALES = frozenset({"*", "**", "*.*"})
DIAS_RECORDAR = 30


class Decision(StrEnum):
    APROBAR = "aprobar"
    RECHAZAR = "rechazar"
    PREGUNTAR = "preguntar"


class ReglaError(ValueError):
    """Regla de aprobacion invalida."""


@dataclass(frozen=True, slots=True)
class Solicitud:
    """Lo que un paso con efectos quiere hacer."""

    paso_id: str
    tipo: str
    """http | tool"""
    destino: str
    """Host para http, `mcp:integracion.herramienta` para tool, `?` si no se sabe."""
    metodo: str | None
    vista: str
    """Vista previa legible, sin secretos."""


@dataclass(frozen=True, slots=True)
class Regla:
    accion: Decision
    paso: str | None = None
    """Patron glob sobre el id del paso."""
    destino: str | None = None
    """Patron glob sobre el destino, ej. `*.slack.com` o `mcp:crm.*`."""
    metodo: str | None = None

    def __post_init__(self) -> None:
        if self.accion is Decision.PREGUNTAR:
            return
        if self.metodo is not None:
            object.__setattr__(self, "metodo", self.metodo.upper())
        if self.accion is Decision.APROBAR:
            sin_alcance = self.paso is None and self.destino is None
            comodin = (self.destino in COMODINES_TOTALES and self.paso in (None, *COMODINES_TOTALES)) or (
                self.paso in COMODINES_TOTALES and self.destino is None
            )
            if sin_alcance or comodin:
                raise ReglaError(
                    "una regla que aprueba necesita un paso o un destino concreto; "
                    "aprobar todo se hace con --yes, a sabiendas, en cada corrida"
                )

    def aplica(self, s: Solicitud) -> bool:
        if self.paso is not None and not fnmatchcase(s.paso_id, self.paso):
            return False
        if self.destino is not None and not fnmatchcase(s.destino.lower(), self.destino.lower()):
            return False
        return self.metodo is None or (s.metodo or "").upper() == self.metodo

    def describir(self) -> str:
        partes = [f"{k}={v}" for k, v in (("paso", self.paso), ("destino", self.destino), ("metodo", self.metodo)) if v]
        return f"{self.accion} {' '.join(partes)}".strip()


def _ahora(ahora: datetime | None) -> datetime:
    return (ahora or datetime.now(UTC)).astimezone(UTC)


class MemoriaAprobaciones:
    """Decisiones "siempre para este destino", persistentes y con vencimiento.

    Abre una conexion por operacion: el aprobador interactivo corre en otro hilo
    y SQLite no permite compartir conexiones entre hilos.
    """

    _ESQUEMA = """
    CREATE TABLE IF NOT EXISTS decisiones (
        destino  TEXT NOT NULL,
        metodo   TEXT NOT NULL DEFAULT '',
        decision TEXT NOT NULL,
        hasta    TEXT NOT NULL,
        creado   TEXT NOT NULL,
        PRIMARY KEY (destino, metodo)
    )
    """

    def __init__(self, ruta: str | Path) -> None:
        self.ruta = Path(ruta)
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._conectar()) as conn:
            conn.execute(self._ESQUEMA)

    def _conectar(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.ruta, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn

    def recordar(
        self,
        destino: str,
        metodo: str | None,
        decision: Decision,
        *,
        dias: int = DIAS_RECORDAR,
        ahora: datetime | None = None,
    ) -> datetime:
        """Guarda una decision. Devuelve hasta cuando vale."""
        if decision is Decision.PREGUNTAR:
            raise ReglaError("solo se recuerda aprobar o rechazar")
        if destino == "?" or destino in COMODINES_TOTALES:
            raise ReglaError("no se recuerda una decision para un destino desconocido o comodin")
        if not 1 <= dias <= 365:
            raise ReglaError("una decision se recuerda entre 1 y 365 dias")
        momento = _ahora(ahora)
        hasta = momento + timedelta(days=dias)
        with closing(self._conectar()) as conn:
            conn.execute(
                "INSERT INTO decisiones (destino, metodo, decision, hasta, creado) VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT(destino, metodo) DO UPDATE SET decision = excluded.decision,"
                " hasta = excluded.hasta, creado = excluded.creado",
                (destino.lower(), (metodo or "").upper(), str(decision), hasta.isoformat(), momento.isoformat()),
            )
        return hasta

    def consultar(self, destino: str, metodo: str | None, ahora: datetime | None = None) -> Decision | None:
        momento = _ahora(ahora)
        with closing(self._conectar()) as conn:
            fila = conn.execute(
                "SELECT decision, hasta FROM decisiones WHERE destino = ? AND metodo = ?",
                (destino.lower(), (metodo or "").upper()),
            ).fetchone()
            if fila is None:
                return None
            if datetime.fromisoformat(fila["hasta"]) <= momento:
                conn.execute(
                    "DELETE FROM decisiones WHERE destino = ? AND metodo = ?",
                    (destino.lower(), (metodo or "").upper()),
                )
                return None
        return Decision(fila["decision"])

    def olvidar(self, destino: str, metodo: str | None = None) -> int:
        with closing(self._conectar()) as conn:
            if metodo is None:
                return conn.execute("DELETE FROM decisiones WHERE destino = ?", (destino.lower(),)).rowcount
            return conn.execute(
                "DELETE FROM decisiones WHERE destino = ? AND metodo = ?", (destino.lower(), metodo.upper())
            ).rowcount

    def listar(self) -> list[dict[str, str]]:
        with closing(self._conectar()) as conn:
            return [dict(f) for f in conn.execute("SELECT * FROM decisiones ORDER BY destino, metodo")]


@dataclass(slots=True)
class Politica:
    reglas: list[Regla] = field(default_factory=list)
    memoria: MemoriaAprobaciones | None = None

    def evaluar(self, s: Solicitud, ahora: datetime | None = None) -> tuple[Decision, str]:
        for regla in self.reglas:
            if regla.aplica(s):
                return regla.accion, f"regla: {regla.describir()}"
        if self.memoria is not None:
            recordada = self.memoria.consultar(s.destino, s.metodo, ahora)
            if recordada is not None:
                return recordada, f"decision recordada para {s.destino}"
        return Decision.PREGUNTAR, "sin regla ni decision recordada"


def cargar_politica(ruta: str | Path, memoria: MemoriaAprobaciones | None = None) -> Politica:
    """Lee reglas desde YAML: `reglas: [{accion, paso?, destino?, metodo?}]`."""
    p = Path(ruta)
    try:
        datos = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ReglaError(f"no se pudo leer la politica {p}: {exc}") from None
    if not isinstance(datos, dict) or not isinstance(datos.get("reglas", []), list):
        raise ReglaError(f"{p}: se esperaba `reglas:` con una lista")

    reglas: list[Regla] = []
    permitidas = {"accion", "paso", "destino", "metodo"}
    for i, crudo in enumerate(datos.get("reglas", [])):
        if not isinstance(crudo, dict) or set(crudo) - permitidas:
            raise ReglaError(f"{p}: regla {i} invalida; campos permitidos: {', '.join(sorted(permitidas))}")
        try:
            accion = Decision(str(crudo.get("accion", "")).lower())
        except ValueError:
            raise ReglaError(f"{p}: regla {i}: accion debe ser aprobar, rechazar o preguntar") from None
        reglas.append(
            Regla(accion, paso=crudo.get("paso"), destino=crudo.get("destino"), metodo=crudo.get("metodo"))
        )
    return Politica(reglas, memoria)


async def resolver_aprobacion(
    s: Solicitud,
    aprobar: Callable[..., Any],
    politica: Politica | None = None,
    tiempo: float | None = None,
) -> tuple[bool, str]:
    """Decide un paso con efectos. Devuelve (aprobado, motivo)."""
    if politica is not None:
        decision, motivo = politica.evaluar(s)
        if decision is Decision.APROBAR:
            return True, motivo
        if decision is Decision.RECHAZAR:
            return False, motivo

    # El aprobador puede declarar un parametro `solicitud` para ver destino y metodo.
    try:
        quiere_solicitud = "solicitud" in inspect.signature(aprobar).parameters
    except (TypeError, ValueError):
        quiere_solicitud = False
    argumentos: dict[str, Any] = {"solicitud": s} if quiere_solicitud else {}

    async def preguntar() -> bool:
        if inspect.iscoroutinefunction(aprobar):
            return bool(await aprobar(s.paso_id, s.vista, **argumentos))
        # En un hilo: un aprobador bloqueante (una pregunta en la terminal) no debe
        # congelar el bucle, o el vencimiento no podria cumplirse.
        resultado = await asyncio.to_thread(aprobar, s.paso_id, s.vista, **argumentos)
        if inspect.isawaitable(resultado):
            resultado = await resultado
        return bool(resultado)

    try:
        aprobado = await (asyncio.wait_for(preguntar(), tiempo) if tiempo else preguntar())
    except TimeoutError:
        return False, f"la aprobacion vencio tras {tiempo:g} s sin respuesta"
    return (True, "aprobado por una persona") if aprobado else (False, "el efecto no fue aprobado")
