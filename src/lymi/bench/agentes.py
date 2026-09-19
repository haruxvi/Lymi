"""Que modelo sirve como agente en esta maquina: medido, no opinado.

Las preguntas salen del propio repositorio (donde se define una funcion y quien
la llama) y cada respuesta se corrige sola contra el indice de codigo, sin un
modelo juez:

1. cita la definicion con ruta y linea exactas;
2. nombra al menos un llamador real (confirmado por importacion);
3. no cita nada que no haya visto (procedencia, `agencia/citas.py`).

La tercera condicion es la que importa: una respuesta rapida, segura y equivocada
no puede ganar. Idea de metodo tomada de Graft (puerta de correccion); la
implementacion y las preguntas son de lymi.
"""

from __future__ import annotations

import hashlib
import re
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from lymi.agencia import Agencia, correr_agencia
from lymi.agencia.citas import citas
from lymi.codigo import abrir
from lymi.codigo.extraer import MODULO
from lymi.ledger import Ledger
from lymi.providers.base import LLMClient

ROL_INGENIERO = """Respondes preguntas sobre el codigo del repositorio sin leer archivos enteros.

Como trabajas:
- codigo.buscar para encontrar donde esta algo.
- codigo.llamadores para saber quien usa una funcion.
- codigo.fragmento para leer solo una funcion, si lo necesitas.

Reglas:
- Cita la ruta y la linea tal como aparecen en el resultado de la herramienta, con el formato ruta:linea.
- Nunca escribas una ruta o una linea que no hayas visto en un resultado.
- Responde en el idioma de la pregunta."""

HERRAMIENTAS = ["codigo.buscar", "codigo.llamadores", "codigo.fragmento", "codigo.esqueleto"]


@dataclass(frozen=True, slots=True)
class Pregunta:
    simbolo: str
    ruta: str
    linea: int
    llamadores: frozenset[str]

    @property
    def texto(self) -> str:
        return f"¿En que archivo y linea se define `{self.simbolo}` y que funciones la llaman?"


@dataclass(slots=True)
class Respuesta:
    pregunta: Pregunta
    aprobada: bool
    motivo: str
    turnos: int
    tokens_locales: int
    tokens_remotos: int
    segundos: float
    sin_respaldo: list[str]
    texto: str


def preguntas(raiz: Path, n: int, prefijo: str = "src/") -> list[Pregunta]:
    """Funciones y metodos de nombre unico que tienen al menos un llamador confirmado.

    El orden sale del hash del nombre: estable entre corridas y sin elegir a mano
    las preguntas faciles.
    """
    with abrir(raiz) as indice:
        todos = indice.simbolos(prefijo)
        repetidos = Counter(s["simple"] for s in indice.simbolos(""))
        candidatas = []
        for s in todos:
            if s["simple"].startswith("_") or repetidos[s["simple"]] > 1:
                continue
            llamadores = frozenset(
                ll["desde"].rsplit(".", 1)[-1]
                for ll in indice.llamadores(s["nombre"])
                if ll["confirmado"] and ll["desde"] != MODULO
            )
            if llamadores:
                candidatas.append(Pregunta(s["nombre"], s["ruta"], s["linea"], llamadores))
    candidatas.sort(key=lambda p: hashlib.sha1(p.simbolo.encode()).hexdigest())
    return candidatas[:n]


def calificar(texto: str, pregunta: Pregunta, sin_respaldo: list[str]) -> tuple[bool, str]:
    esperada = f"{pregunta.ruta}:{pregunta.linea}"
    referencias = [c for c in citas(texto) if not c.startswith(("http://", "https://"))]
    cita_definicion = any(c == esperada or esperada.endswith("/" + c) for c in referencias)
    nombra = any(re.search(rf"\b{re.escape(n)}\b", texto) for n in pregunta.llamadores)
    fallas = []
    if not cita_definicion:
        fallas.append(f"no cita {esperada}")
    if not nombra:
        fallas.append("no nombra ningun llamador real")
    if sin_respaldo:
        fallas.append(f"cita sin respaldo: {', '.join(sin_respaldo[:3])}")
    return not fallas, "; ".join(fallas) or "ok"


def agencia_de_prueba(tier: str) -> Agencia:
    return Agencia.model_validate({
        "name": "eval_codigo",
        "limites": {"agentes_totales": 1, "turnos_por_agente": 8, "llamadas": 10, "segundos": 900},
        "departamentos": {"producto": {"agentes": {"ingeniero": {
            "descripcion": "responde sobre el codigo", "rol": ROL_INGENIERO, "tier": tier,
            "herramientas": HERRAMIENTAS,
        }}}},
    })


async def evaluar(
    cliente: LLMClient, tier: str, lista: list[Pregunta], *, ledger: Ledger, al_responder=None
) -> list[Respuesta]:
    agencia = agencia_de_prueba(tier)
    respuestas = []
    for pregunta in lista:
        inicio = time.monotonic()
        resultado = await correr_agencia(
            agencia, pregunta.texto, ledger=ledger, agente="producto",
            local=cliente if tier == "local" else None, remote=cliente if tier == "remote" else None,
        )
        raiz = resultado.tareas[0]
        texto = resultado.resultado or ""
        if resultado.ok:
            aprobada, motivo = calificar(texto, pregunta, raiz.sin_respaldo)
        else:
            aprobada, motivo = False, f"no termino: {resultado.detalle}"
        respuesta = Respuesta(
            pregunta, aprobada, motivo, raiz.turnos, raiz.tokens_locales, raiz.tokens_remotos,
            time.monotonic() - inicio, raiz.sin_respaldo, texto,
        )
        respuestas.append(respuesta)
        if al_responder is not None:
            al_responder(respuesta)
    return respuestas
