"""Plantillas de workflow: `{{ ruta }}` y nada mas.

Decision de seguridad, no de simplicidad. En muchos motores de workflow las
llaves ejecutan codigo. Si un correo entrante contiene
`{{ __import__('os').system(...) }}` y el workflow lo interpola, el correo de un
desconocido acaba de ejecutar codigo en tu maquina.

Aqui una plantilla solo puede BUSCAR un valor por ruta:

- sin expresiones, sin filtros, sin llamadas;
- sin segmentos que empiecen por `_`;
- una sola pasada: si la salida de un modelo contiene `{{ inputs.secreto }}`, ese
  texto se inserta tal cual y NUNCA se vuelve a expandir.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

PATRON = re.compile(r"\{\{\s*([^{}]*?)\s*\}\}")
_RUTA = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)*$")


class TemplateError(ValueError):
    """Una plantilla mal formada o que apunta a un valor inexistente."""


def segmentos(ruta: str) -> list[str]:
    """Valida una ruta y la parte en segmentos."""
    if not _RUTA.fullmatch(ruta):
        raise TemplateError(
            f"ruta invalida {ruta!r}: solo se admiten nombres separados por puntos "
            "(sin expresiones, filtros ni llamadas)"
        )
    partes = ruta.split(".")
    if any(p.startswith("_") for p in partes):
        raise TemplateError(f"ruta invalida {ruta!r}: segmentos privados no permitidos")
    return partes


def resolver_ruta(contexto: Mapping[str, Any], ruta: str) -> Any:
    """Busca `ruta` dentro del contexto. Solo diccionarios e indices de lista."""
    actual: Any = contexto
    recorrido: list[str] = []
    for seg in segmentos(ruta):
        recorrido.append(seg)
        if isinstance(actual, Mapping):
            if seg not in actual:
                raise TemplateError(f"{'.'.join(recorrido)!r} no existe")
            actual = actual[seg]
        elif isinstance(actual, Sequence) and not isinstance(actual, str) and seg.isdigit():
            indice = int(seg)
            if indice >= len(actual):
                raise TemplateError(f"{'.'.join(recorrido)!r}: indice fuera de rango")
            actual = actual[indice]
        else:
            tipo = type(actual).__name__
            raise TemplateError(f"{'.'.join(recorrido)!r}: no se puede entrar en un {tipo}")
    return actual


def _como_texto(valor: Any) -> str:
    if isinstance(valor, str):
        return valor
    return json.dumps(valor, ensure_ascii=False)


def render(valor: Any, contexto: Mapping[str, Any]) -> Any:
    """Resuelve plantillas dentro de cadenas, diccionarios y listas.

    Una cadena que es EXACTAMENTE una plantilla conserva el tipo del valor
    (diccionario, numero...). Mezclada con texto, se convierte a cadena.
    """
    if isinstance(valor, str):
        unica = PATRON.fullmatch(valor.strip())
        if unica is not None:
            return resolver_ruta(contexto, unica.group(1))
        # re.sub no vuelve a examinar el texto insertado: una sola pasada.
        return PATRON.sub(lambda m: _como_texto(resolver_ruta(contexto, m.group(1))), valor)
    if isinstance(valor, Mapping):
        return {k: render(v, contexto) for k, v in valor.items()}
    if isinstance(valor, list):
        return [render(v, contexto) for v in valor]
    return valor


def referencias(valor: Any) -> set[str]:
    """Rutas que una plantilla consulta. Sirve para validar el workflow sin correrlo."""
    encontradas: set[str] = set()
    if isinstance(valor, str):
        for m in PATRON.finditer(valor):
            segmentos(m.group(1))  # levanta si la ruta es invalida
            encontradas.add(m.group(1))
    elif isinstance(valor, Mapping):
        for v in valor.values():
            encontradas |= referencias(v)
    elif isinstance(valor, list):
        for v in valor:
            encontradas |= referencias(v)
    return encontradas
