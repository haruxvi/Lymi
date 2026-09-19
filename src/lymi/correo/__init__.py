"""Correo: lectura del buzon local de Thunderbird y resumen que arma lymi."""

from lymi.correo.buzon import Buzon, CorreoError, Mensaje, perfil_por_defecto, raiz_perfiles
from lymi.correo.resumen import Anotacion, Resumen, render, resumir

__all__ = [
    "Anotacion",
    "Buzon",
    "CorreoError",
    "Mensaje",
    "Resumen",
    "perfil_por_defecto",
    "raiz_perfiles",
    "render",
    "resumir",
]
