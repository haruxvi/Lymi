"""Tema de la interfaz: `~/.config/lymi/theme.toml`.

El archivo es del usuario: se puede editar a mano. Por eso se lee con tolerancia
(lo invalido se ignora y cae al tema por defecto) y se escribe con rigor (solo
nombres y colores validados, asi nada que llegue por la API se cuela en el TOML).
"""

from __future__ import annotations

import os
import re
import tomllib
from pathlib import Path
from typing import Any

CLAVES = ("papel", "panel", "texto", "remoto", "local", "gris", "acento")
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_NOMBRE = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")

POR_DEFECTO = "sistema"
"""Sigue al sistema: claro u oscuro segun Windows/macOS/Linux. Lo resuelve la hoja de estilos."""

OBSOLETOS = frozenset({"riso-rosa-menta", "riso-federal", "riso-naranja-lila", "riso-papel-claro"})
"""Los temas neon de la primera interfaz. Un theme.toml que los nombre cae al de por defecto, avisado."""


def _tinta(papel: str, panel: str, texto: str, remoto: str, local: str, gris: str, acento: str) -> dict[str, str]:
    return {"papel": papel, "panel": panel, "texto": texto, "remoto": remoto, "local": local, "gris": gris,
            "acento": acento}


PRESETS: dict[str, dict[str, Any]] = {
    "sistema": {"nombre": "Sistema", "tinta": _tinta(
        "#f6f6f4", "#ffffff", "#1d1d1b", "#b45309", "#15803d", "#6b6b66", "#4f46e5")},
    "claro": {"nombre": "Claro", "tinta": _tinta(
        "#f6f6f4", "#ffffff", "#1d1d1b", "#b45309", "#15803d", "#6b6b66", "#4f46e5")},
    "oscuro": {"nombre": "Oscuro", "tinta": _tinta(
        "#141416", "#1c1c1f", "#e8e8e5", "#e3a35e", "#5cbf86", "#9a9a94", "#8b8ff5")},
    "papel": {"nombre": "Papel", "tinta": _tinta(
        "#f4f0e8", "#fffdf8", "#2b2620", "#a4561b", "#3f7d4f", "#7a7064", "#9a5b2f")},
    "grafito": {"nombre": "Grafito", "tinta": _tinta(
        "#1a1c20", "#22252a", "#e4e6ea", "#e3a35e", "#6cc08b", "#9aa0aa", "#7aa2f7")},
    "nord": {"nombre": "Nord", "tinta": _tinta(
        "#2e3440", "#3b4252", "#eceff4", "#ebcb8b", "#a3be8c", "#a3abba", "#88c0d0")},
    "catppuccin-mocha": {"nombre": "Catppuccin Mocha", "tinta": _tinta(
        "#1e1e2e", "#27273a", "#cdd6f4", "#fab387", "#a6e3a1", "#9399b2", "#89b4fa")},
    "gruvbox-dark": {"nombre": "Gruvbox Dark", "tinta": _tinta(
        "#282828", "#32302f", "#ebdbb2", "#fe8019", "#b8bb26", "#a89984", "#83a598")},
    "tokyo-night": {"nombre": "Tokyo Night", "tinta": _tinta(
        "#1a1b26", "#222436", "#c0caf5", "#ff9e64", "#9ece6a", "#787c99", "#7aa2f7")},
}


class TemaError(ValueError):
    """Nombre o colores de tema invalidos."""


def ruta_tema() -> Path:
    propia = os.environ.get("LYMI_TEMA")
    return Path(propia) if propia else Path.home() / ".config" / "lymi" / "theme.toml"


def _defecto(origen: str, aviso: str | None = None) -> dict[str, Any]:
    datos: dict[str, Any] = {
        "nombre": POR_DEFECTO,
        "tinta": dict(PRESETS[POR_DEFECTO]["tinta"]),
        "origen": origen,
    }
    if aviso:
        datos["aviso"] = aviso
    return datos


def leer(ruta: Path) -> dict[str, Any]:
    if not ruta.exists():
        return _defecto("por defecto")
    try:
        crudo = tomllib.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        return _defecto("por defecto", f"theme.toml ilegible ({exc}); se usa el tema por defecto")

    nombre = crudo.get("name")
    if nombre in OBSOLETOS:
        return _defecto(
            "por defecto", f"el tema {nombre} ya no existe; se usa {PRESETS[POR_DEFECTO]['nombre']}. Elige otro abajo"
        )
    tinta = dict(PRESETS[POR_DEFECTO]["tinta"])
    colores = crudo.get("tinta")
    if isinstance(colores, dict):
        for clave in CLAVES:
            valor = colores.get(clave)
            if isinstance(valor, str) and _HEX.match(valor):
                tinta[clave] = valor.lower()
    if not isinstance(nombre, str) or not _NOMBRE.match(nombre):
        nombre = "personalizado"
    return {"nombre": nombre, "tinta": tinta, "origen": str(ruta)}


def validar(nombre: Any, tinta: Any) -> tuple[str, dict[str, str]]:
    if not isinstance(nombre, str) or not _NOMBRE.match(nombre):
        raise TemaError("nombre de tema invalido: minusculas, digitos y guiones, hasta 41 caracteres")
    if not isinstance(tinta, dict) or set(tinta) != set(CLAVES):
        raise TemaError(f"la tinta debe traer exactamente: {', '.join(CLAVES)}")
    for clave in CLAVES:
        valor = tinta[clave]
        if not isinstance(valor, str) or not _HEX.match(valor):
            raise TemaError(f"{clave}: se esperaba un color #rrggbb")
    return nombre, {clave: tinta[clave].lower() for clave in CLAVES}


def escribir(ruta: Path, nombre: Any, tinta: Any) -> None:
    nombre, tinta = validar(nombre, tinta)
    lineas = [
        "# Tema de lymi. Lo escribe la interfaz; se puede editar a mano.",
        f'name = "{nombre}"',
        "",
        "[tinta]",
        *(f'{clave} = "{tinta[clave]}"' for clave in CLAVES),
    ]
    ruta.parent.mkdir(parents=True, exist_ok=True)
    # Escritura atomica: un corte a mitad no deja un theme.toml truncado.
    temporal = ruta.with_name(ruta.name + ".tmp")
    temporal.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    temporal.replace(ruta)
