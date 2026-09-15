"""Ejecutor del host: la unica puerta de lymi hacia los archivos y comandos del PC.

Resuelve el primer riesgo de `docs/ARQUITECTURA_AGENTE_SEGURO.md` (romper el
sistema): el modelo nunca obtiene un shell, solo operaciones cerradas sobre rutas
permitidas, y todo lo que se modifica o borra queda en un diario que se deshace.
"""

from lymi.ejecutor.capacidades import CapacidadDenegada, Comando, Perfil, PerfilError, cargar_perfil
from lymi.ejecutor.diario import Diario, DiarioError, deshacer, raiz_diario
from lymi.ejecutor.ejecutor import Ejecutor, EjecutorError, Lectura

__all__ = [
    "CapacidadDenegada",
    "Comando",
    "Diario",
    "DiarioError",
    "Ejecutor",
    "EjecutorError",
    "Lectura",
    "Perfil",
    "PerfilError",
    "cargar_perfil",
    "deshacer",
    "raiz_diario",
]
