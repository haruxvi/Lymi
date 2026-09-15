"""Etiquetas de sensibilidad por ruta: que archivos pueden salir y cuales no.

Cuatro niveles, de menos a mas restrictivo: publico, interno, confidencial y
nunca-sale. Las reglas viven en `sensibilidad.yml` (la primera que coincide gana)
y hay un piso fijo que ninguna regla baja: llaves, `.env` y bovedas de secretos
son `nunca-sale` aunque el archivo diga otra cosa.

Lo que garantiza cada nivel hoy, sin adornos:

- `nunca-sale`: su texto literal (entero o cualquier linea larga) no llega a un
  proveedor remoto, a una herramienta MCP ni a un destino HTTP. Un resumen hecho
  por el modelo local si puede salir: es justo el diseno, el modelo local lee lo
  sensible y al remoto solo llega lo destilado.
- `confidencial`, `interno`, `publico`: salen redactados, como todo lo demas.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from fnmatch import fnmatch
from pathlib import Path

import yaml

PISO = (
    ".env", ".env.*", "*.env", "*.pem", "*.key", "*.p12", "*.pfx", "*.kdbx",
    "id_rsa*", "id_ecdsa*", "id_ed25519*", ".ssh/*", "*/.ssh/*", ".netrc", ".npmrc", ".pypirc",
)
"""Rutas que son `nunca-sale` siempre, por nombre o por ruta."""

LINEA_MINIMA = 40
"""Largo minimo de una linea para vigilarla por separado: las cortas son demasiado
comunes ('}' o 'import os') y bloquearian por coincidencia."""


class EtiquetaError(ValueError):
    """`sensibilidad.yml` invalido."""


class Nivel(IntEnum):
    PUBLICO = 0
    INTERNO = 1
    CONFIDENCIAL = 2
    NUNCA_SALE = 3

    @classmethod
    def desde(cls, texto: object) -> Nivel:
        nombres = {n.etiqueta: n for n in cls}
        if not isinstance(texto, str) or texto.strip().lower() not in nombres:
            raise EtiquetaError(f"nivel invalido {texto!r}: usa {', '.join(nombres)}")
        return nombres[texto.strip().lower()]

    @property
    def etiqueta(self) -> str:
        return self.name.lower().replace("_", "-")


@dataclass(frozen=True, slots=True)
class Regla:
    patron: str
    nivel: Nivel


def _formas(ruta: Path) -> tuple[str, ...]:
    """La ruta como se escribio, relativa al directorio actual si se puede, y su nombre."""
    formas = {ruta.as_posix(), ruta.name}
    try:
        formas.add(ruta.resolve().relative_to(Path.cwd().resolve()).as_posix())
    except (OSError, ValueError):
        pass
    return tuple(formas)


@dataclass(slots=True)
class Etiquetas:
    reglas: list[Regla] = field(default_factory=list)
    por_defecto: Nivel = Nivel.INTERNO

    def nivel_de(self, ruta: Path) -> Nivel:
        formas = _formas(ruta)
        if any(fnmatch(forma, patron) for forma in formas for patron in PISO):
            return Nivel.NUNCA_SALE
        for regla in self.reglas:
            if any(fnmatch(forma, regla.patron) for forma in formas):
                return regla.nivel
        return self.por_defecto


def cargar_etiquetas(ruta: Path | None) -> Etiquetas:
    """Lee `sensibilidad.yml`. Sin archivo, solo rige el piso fijo."""
    if ruta is None or not ruta.exists():
        return Etiquetas()
    try:
        datos = yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise EtiquetaError(f"no se pudo leer {ruta}: {exc}") from None
    if not isinstance(datos, dict) or not isinstance(datos.get("reglas", []), list):
        raise EtiquetaError(f"{ruta}: se esperaba `reglas:` con una lista")

    reglas = []
    for i, crudo in enumerate(datos.get("reglas", [])):
        if not isinstance(crudo, dict) or set(crudo) != {"ruta", "nivel"} or not isinstance(crudo["ruta"], str):
            raise EtiquetaError(f"{ruta}: regla {i} invalida; cada regla lleva `ruta` y `nivel`")
        reglas.append(Regla(crudo["ruta"], Nivel.desde(crudo["nivel"])))
    por_defecto = Nivel.desde(datos["por_defecto"]) if "por_defecto" in datos else Nivel.INTERNO
    return Etiquetas(reglas, por_defecto)


def fragmentos_protegidos(contenido: str) -> tuple[str, ...]:
    """Lo que se vigila de un contenido `nunca-sale`: el texto entero y sus lineas largas."""
    lineas = {linea.strip() for linea in contenido.splitlines() if len(linea.strip()) >= LINEA_MINIMA}
    entero = contenido.strip()
    return tuple(sorted({entero, *lineas} - {""}, key=len, reverse=True))
