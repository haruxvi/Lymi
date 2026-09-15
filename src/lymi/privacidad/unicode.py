"""Saneamiento de texto ajeno antes de que llegue a un modelo.

Un documento, una pagina o la salida de una herramienta pueden traer
instrucciones que una persona no ve: caracteres de ancho cero, controles
bidireccionales que reordenan lo que se muestra, o "tag characters"
(U+E0000..U+E007F) que codifican texto ASCII invisible. El modelo si los lee.

Se quitan antes y se cuenta cuantos: un texto con cientos de invisibles es una
senal en si mismo. El costo asumido: tambien se van los unidores de emojis
compuestos (ZWJ). Una familia de emojis puede verse separada; una instruccion
escondida no llega.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

_BIDI = frozenset("\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069\u200e\u200f\u061c")
_ANCHO_CERO = frozenset("\u200b\u200c\u200d\u2060\ufeff\u180e")
_CONSERVAR = frozenset("\n\t\r")
_CONTROL_ASCII = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


@dataclass(frozen=True, slots=True)
class Saneado:
    texto: str
    quitados: dict[str, int] = field(default_factory=dict)
    """Cuantos caracteres se quitaron, por categoria."""

    @property
    def total(self) -> int:
        return sum(self.quitados.values())


def _categoria(caracter: str) -> str | None:
    if caracter in _CONSERVAR:
        return None
    punto = ord(caracter)
    if 0xE0000 <= punto <= 0xE007F:
        return "etiquetas_invisibles"
    if caracter in _BIDI:
        return "bidi"
    if caracter in _ANCHO_CERO:
        return "ancho_cero"
    categoria = unicodedata.category(caracter)
    if categoria == "Cc":
        return "control"
    if categoria == "Cf":
        return "formato"
    if categoria == "Co":
        return "uso_privado"
    return None


def sanear(texto: str) -> Saneado:
    """Quita caracteres invisibles, de control y bidireccionales."""
    # Camino rapido: el texto ASCII sin controles, que es casi todo, no se recorre.
    if texto.isascii() and not _CONTROL_ASCII.search(texto):
        return Saneado(texto)

    partes: list[str] = []
    quitados: dict[str, int] = {}
    for caracter in texto:
        categoria = _categoria(caracter)
        if categoria is None:
            partes.append(caracter)
        else:
            quitados[categoria] = quitados.get(categoria, 0) + 1
    return Saneado("".join(partes), quitados)


def sanear_valor(valor: Any) -> tuple[Any, int]:
    """Sanea todas las cadenas de una estructura JSON. Devuelve (valor, quitados)."""
    if isinstance(valor, str):
        resultado = sanear(valor)
        return resultado.texto, resultado.total
    if isinstance(valor, list):
        total = 0
        lista = []
        for elemento in valor:
            limpio, n = sanear_valor(elemento)
            lista.append(limpio)
            total += n
        return lista, total
    if isinstance(valor, dict):
        total = 0
        mapa = {}
        for clave, elemento in valor.items():
            clave_limpia, n_clave = sanear_valor(clave) if isinstance(clave, str) else (clave, 0)
            limpio, n = sanear_valor(elemento)
            mapa[clave_limpia] = limpio
            total += n + n_clave
        return mapa, total
    return valor, 0
