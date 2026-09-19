"""Agencia: departamentos de agentes que trabajan, derivan tareas y crean ayudantes.

Ideas tomadas de FounderOS (MIT; no se copio codigo): departamentos con lider,
un enrutador que respeta `@agente` antes de preguntarle a un modelo, y el rol de
cada agente como archivo que ES su prompt. La delegacion, los ayudantes, el
trabajo en paralelo y todos los topes son de lymi.
"""

from lymi.agencia.definicion import (
    HERRAMIENTAS,
    Agencia,
    AgenciaError,
    AgenteDef,
    Departamento,
    Limites,
    cargar_agencia,
)
from lymi.agencia.motor import (
    LimiteAgencia,
    Orquestador,
    ResultadoAgencia,
    Tarea,
    arbol,
    correr_agencia,
    enrutar,
)

__all__ = [
    "HERRAMIENTAS",
    "Agencia",
    "AgenciaError",
    "AgenteDef",
    "Departamento",
    "LimiteAgencia",
    "Limites",
    "Orquestador",
    "ResultadoAgencia",
    "Tarea",
    "arbol",
    "cargar_agencia",
    "correr_agencia",
    "enrutar",
]
