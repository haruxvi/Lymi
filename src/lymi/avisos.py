"""Avisos: lo que lymi te cuenta sin que lo mires.

Una lista en memoria, por proceso, que otros llenan y quien muestra lee:

- la agenda, cuando una programacion termina ("el informe del dia esta listo");
- los trabajos, cuando algo espera tu aprobacion o un chat termino;
- el vigia del calendario, quince minutos antes de cada evento.

La app de escritorio los muestra como notificaciones del sistema desde la bandeja;
la pagina, como avisos dentro de la interfaz. Nada sale de la maquina: son
notificaciones locales, sin servicios de push de terceros.
"""

from __future__ import annotations

import itertools
import threading
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

MAX_AVISOS = 200
ANTICIPO_EVENTOS = timedelta(minutes=15)


@dataclass(frozen=True, slots=True)
class Aviso:
    id: int
    tipo: str
    """programacion | aprobacion | terminado | evento | error"""
    titulo: str
    texto: str = ""
    enlace: str = ""
    """Ruta de la interfaz que lo explica (`#/corridas/<id>`, `#/chat/<id>`...)."""
    ts: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))

    def como_dict(self) -> dict[str, Any]:
        return asdict(self)


class Avisos:
    """Cola acotada y segura entre hilos. Cada lector lleva su propio cursor (el ultimo id visto)."""

    def __init__(self, maximo: int = MAX_AVISOS) -> None:
        self._lock = threading.Lock()
        self._lista: deque[Aviso] = deque(maxlen=maximo)
        self._ids = itertools.count(1)
        self._vistos: set[str] = set()

    def publicar(self, tipo: str, titulo: str, texto: str = "", enlace: str = "", *, clave: str | None = None) -> Aviso | None:
        """Agrega un aviso. Con `clave`, uno igual no se repite (un evento avisa una sola vez)."""
        with self._lock:
            if clave is not None:
                if clave in self._vistos:
                    return None
                self._vistos.add(clave)
                if len(self._vistos) > 4 * MAX_AVISOS:
                    self._vistos = set(list(self._vistos)[-2 * MAX_AVISOS:])
            aviso = Aviso(next(self._ids), tipo, titulo[:120], texto[:300], enlace)
            self._lista.append(aviso)
            return aviso

    def despues_de(self, ultimo: int = 0) -> list[Aviso]:
        with self._lock:
            return [a for a in self._lista if a.id > ultimo]

    def ultimo(self) -> int:
        with self._lock:
            return self._lista[-1].id if self._lista else 0


def eventos_proximos(avisos: Avisos, ahora: datetime | None = None, anticipo: timedelta = ANTICIPO_EVENTOS) -> int:
    """Avisa de los eventos que empiezan dentro de `anticipo`. Devuelve cuantos avisos nuevos hubo.

    Sin calendario configurado no hay nada que vigilar: no es un error.
    """
    from lymi.calendario import Calendario, CalendarioError

    ahora = ahora or datetime.now().astimezone()
    try:
        eventos, _ = Calendario().eventos(ahora, ahora + anticipo)
    except (CalendarioError, OSError):
        return 0
    nuevos = 0
    for e in eventos:
        if e.todo_el_dia or e.inicio < ahora:
            continue
        minutos = max(1, round((e.inicio - ahora).total_seconds() / 60))
        lugar = f" · {e.lugar}" if e.lugar else ""
        if avisos.publicar("evento", f"En {minutos} min: {e.titulo}", f"{e.inicio:%H:%M}{lugar}", "#/calendario",
                           clave=f"evento:{e.titulo}:{e.inicio.isoformat()}"):
            nuevos += 1
    return nuevos
