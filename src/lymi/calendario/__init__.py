"""Calendario local: archivos .ics leidos sin conectarse a nadie."""

from lymi.calendario.ics import (
    Calendario,
    CalendarioError,
    Evento,
    expandir,
    leer,
    raiz_calendarios,
)

__all__ = ["Calendario", "CalendarioError", "Evento", "expandir", "leer", "raiz_calendarios"]
