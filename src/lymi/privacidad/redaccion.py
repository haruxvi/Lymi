"""Redaccion reversible de secretos y datos personales antes del egress.

Antes de que un texto salga hacia un proveedor remoto, cada secreto o dato
personal se reemplaza por un marcador estable (`⟦EMAIL_1_7f3a⟧`). La respuesta
vuelve con los marcadores y se rehidrata en local: el proveedor nunca ve el valor
y lymi no pierde el sentido del texto.

Dos acciones, no una. Lo que basta con ocultar se redacta. Lo que no debe salir
ni siquiera como marcador bloquea el envio: una clave privada pegada entera es
casi siempre un error, y avisar vale mas que mandar el resto del documento.

Cada redactor lleva un sufijo aleatorio en sus marcadores. Asi un texto ajeno que
ya traiga `⟦EMAIL_1⟧` no puede hacerse pasar por un marcador real y lograr que
lymi le escriba un correo verdadero en la respuesta.
"""

from __future__ import annotations

import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum


class Accion(StrEnum):
    REDACTAR = "redactar"
    BLOQUEAR = "bloquear"


class EgressBloqueado(RuntimeError):
    """El envio contiene algo que no sale de la maquina ni redactado."""

    def __init__(self, categorias: set[str] | frozenset[str]) -> None:
        self.categorias = frozenset(categorias)
        super().__init__(
            f"el envio contiene {', '.join(sorted(self.categorias)).lower().replace('_', ' ')}:"
            " no sale de la maquina"
        )


def _luhn(digitos: str) -> bool:
    if not digitos.isdigit() or not 13 <= len(digitos) <= 19:
        return False
    suma = 0
    for i, d in enumerate(reversed(digitos)):
        n = int(d)
        if i % 2:
            n = n * 2 - 9 if n > 4 else n * 2
        suma += n
    return suma % 10 == 0


def _tarjeta_valida(texto: str) -> bool:
    return _luhn(re.sub(r"\D", "", texto))


def _rut_valido(texto: str) -> bool:
    """RUT chileno con digito verificador correcto (modulo 11)."""
    cuerpo, _, dv = texto.replace(".", "").upper().partition("-")
    if not cuerpo.isdigit() or len(dv) != 1:
        return False
    suma, factor = 0, 2
    for d in reversed(cuerpo):
        suma += int(d) * factor
        factor = 2 if factor == 7 else factor + 1
    esperado = 11 - suma % 11
    return dv == {10: "K", 11: "0"}.get(esperado, str(esperado))


@dataclass(frozen=True, slots=True)
class Detector:
    categoria: str
    """Prefijo del marcador, en mayusculas: CLAVE_API, EMAIL..."""
    patron: re.Pattern[str]
    accion: Accion = Accion.REDACTAR
    grupo: int = 0
    """Grupo que se redacta. 0 = todo el match; otro = solo el valor de `clave=valor`."""
    valida: Callable[[str], bool] | None = None
    """Comprobacion extra (Luhn, digito verificador) para no redactar falsos positivos."""


# El orden importa: lo especifico antes que lo generico, para que `token: sk-ant-...`
# quede como CLAVE_API y no como CREDENCIAL. Los valores genericos excluyen `⟦`
# para no volver a redactar un marcador ya puesto.
DETECTORES: tuple[Detector, ...] = (
    Detector(
        "CLAVE_PRIVADA",
        re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----", re.DOTALL),
        Accion.BLOQUEAR,
    ),
    Detector("CLAVE_API", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}")),
    Detector("CLAVE_API", re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{32,}")),
    Detector("CLAVE_API", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    Detector("CLAVE_API", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    Detector("TOKEN", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})")),
    Detector("TOKEN", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    Detector("TOKEN", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")),
    Detector("CREDENCIAL", re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s:/@]+:([^\s@/⟦]+)@", re.IGNORECASE), grupo=1),
    Detector(
        "CREDENCIAL",
        re.compile(
            r"(?i)\b(?:password|passwd|pwd|contrase[nñ]a|clave|secret|secreto|api[_-]?key|token)\b"
            r"\s*[:=]\s*[\"']?([^\s\"'⟦]{6,})"
        ),
        grupo=1,
    ),
    Detector("EMAIL", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b")),
    Detector(
        "TARJETA",
        re.compile(r"\b(?:4|5[1-5]|2[2-7]|3[47]|6(?:011|5))\d(?:[ -]?\d){11,17}\b"),
        valida=_tarjeta_valida,
    ),
    Detector("RUT", re.compile(r"\b\d{1,2}\.?\d{3}\.?\d{3}-[\dkK]\b"), valida=_rut_valido),
    Detector("TELEFONO", re.compile(r"(?<![\w+])\+\d[\d ]{7,16}\d\b")),
)

_MARCADOR = re.compile(r"⟦[A-Z_]+_\d+_[0-9a-f]{4}⟧")


@dataclass(slots=True)
class Redactor:
    """Redacta hacia afuera y rehidrata hacia adentro, dentro de una misma corrida."""

    detectores: tuple[Detector, ...] = DETECTORES
    sufijo: str = field(default_factory=lambda: secrets.token_hex(2))
    conteo: dict[str, int] = field(default_factory=dict)
    """Ocurrencias redactadas por categoria (no valores distintos)."""
    _originales: dict[str, str] = field(default_factory=dict, repr=False)
    _marcadores: dict[tuple[str, str], str] = field(default_factory=dict, repr=False)
    _siguiente: dict[str, int] = field(default_factory=dict, repr=False)

    @property
    def total(self) -> int:
        return sum(self.conteo.values())

    def redactar(self, texto: str) -> str:
        bloqueadas = set()
        for d in self.detectores:
            if d.accion is not Accion.BLOQUEAR:
                continue
            for m in d.patron.finditer(texto):
                if d.valida is None or d.valida(m.group(d.grupo)):
                    bloqueadas.add(d.categoria)
                    break
        if bloqueadas:
            raise EgressBloqueado(bloqueadas)

        for d in self.detectores:
            if d.accion is Accion.REDACTAR:
                texto = d.patron.sub(lambda m, d=d: self._sustituir(m, d), texto)
        return texto

    def rehidratar(self, texto: str) -> str:
        if not self._originales:
            return texto
        return _MARCADOR.sub(lambda m: self._originales.get(m.group(0), m.group(0)), texto)

    def _sustituir(self, m: re.Match[str], d: Detector) -> str:
        valor = m.group(d.grupo)
        if d.valida is not None and not d.valida(valor):
            return m.group(0)
        marcador = self._marcador(d.categoria, valor)
        self.conteo[d.categoria] = self.conteo.get(d.categoria, 0) + 1
        if d.grupo == 0:
            return marcador
        entero = m.group(0)
        inicio, fin = m.start(d.grupo) - m.start(0), m.end(d.grupo) - m.start(0)
        return entero[:inicio] + marcador + entero[fin:]

    def _marcador(self, categoria: str, valor: str) -> str:
        clave = (categoria, valor)
        if clave not in self._marcadores:
            numero = self._siguiente.get(categoria, 0) + 1
            self._siguiente[categoria] = numero
            marcador = f"⟦{categoria}_{numero}_{self.sufijo}⟧"
            self._marcadores[clave] = marcador
            self._originales[marcador] = valor
        return self._marcadores[clave]
