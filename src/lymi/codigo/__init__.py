"""Mapa del codigo de un repositorio: menos lectura a ciegas, menos tokens.

Idea tomada de Graft y codebase-memory-mcp (ambos MIT; no se copio codigo): un
agente no deberia re-explorar el repositorio en cada tarea. Implementacion propia
con `ast` de la libreria estandar, un indice SQLite fresco antes de cada consulta
y el ahorro medido en bytes reales, no prometido.
"""

from lymi.codigo.extraer import LENGUAJES, Extraido, Llamada, Simbolo, extraer
from lymi.codigo.indice import Actualizacion, Indice, IndiceError, abrir, ruta_indice

__all__ = [
    "LENGUAJES",
    "Actualizacion",
    "Extraido",
    "Indice",
    "IndiceError",
    "Llamada",
    "Simbolo",
    "abrir",
    "extraer",
    "ruta_indice",
]
