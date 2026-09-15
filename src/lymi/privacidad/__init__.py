"""Privacidad antes del egress: saneamiento de entrada y redaccion reversible.

Resuelve el tercer riesgo de `docs/ARQUITECTURA_AGENTE_SEGURO.md`: con un modelo
remoto, todo lo que entra al contexto viaja al proveedor. Se decide por dato,
antes de que salga, si puede salir y en que forma.
"""

from lymi.privacidad.redaccion import EgressBloqueado, Redactor
from lymi.privacidad.unicode import Saneado, sanear, sanear_valor

__all__ = ["EgressBloqueado", "Redactor", "Saneado", "sanear", "sanear_valor"]
