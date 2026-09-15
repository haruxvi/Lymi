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

CLAVES = ("papel", "panel", "texto", "remoto", "local", "gris")
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_NOMBRE = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")

POR_DEFECTO = "riso-rosa-menta"

PRESETS: dict[str, dict[str, Any]] = {
    "riso-rosa-menta": {"nombre": "Rosa + menta", "tinta": {
        "papel": "#191324", "panel": "#221a31", "texto": "#f5eee0",
        "remoto": "#ff48a0", "local": "#5ef2a8", "gris": "#a89cbd"}},
    "riso-federal": {"nombre": "Amarillo + azul", "tinta": {
        "papel": "#13162b", "panel": "#1c2140", "texto": "#f3efe4",
        "remoto": "#ffd23f", "local": "#58c4ff", "gris": "#9aa3c7"}},
    "riso-naranja-lila": {"nombre": "Naranja + lila", "tinta": {
        "papel": "#1d1216", "panel": "#2a1a20", "texto": "#f6ede3",
        "remoto": "#ff6c2f", "local": "#b7a4ff", "gris": "#b39aa4"}},
    "riso-papel-claro": {"nombre": "Papel claro", "tinta": {
        "papel": "#f1ebdf", "panel": "#e3d8c6", "texto": "#1b1422",
        "remoto": "#e0245e", "local": "#0a8f5b", "gris": "#6c6272"}},
    "catppuccin-mocha": {"nombre": "Catppuccin Mocha", "tinta": {
        "papel": "#1e1e2e", "panel": "#313244", "texto": "#cdd6f4",
        "remoto": "#fab387", "local": "#a6e3a1", "gris": "#9399b2"}},
    "gruvbox-dark": {"nombre": "Gruvbox Dark", "tinta": {
        "papel": "#282828", "panel": "#3c3836", "texto": "#ebdbb2",
        "remoto": "#fe8019", "local": "#b8bb26", "gris": "#a89984"}},
    "tokyo-night": {"nombre": "Tokyo Night", "tinta": {
        "papel": "#1a1b26", "panel": "#24283b", "texto": "#c0caf5",
        "remoto": "#ff9e64", "local": "#9ece6a", "gris": "#787c99"}},
    "rose-pine": {"nombre": "Rosé Pine", "tinta": {
        "papel": "#191724", "panel": "#26233a", "texto": "#e0def4",
        "remoto": "#eb6f92", "local": "#9ccfd8", "gris": "#908caa"}},
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

    tinta = dict(PRESETS[POR_DEFECTO]["tinta"])
    colores = crudo.get("tinta")
    if isinstance(colores, dict):
        for clave in CLAVES:
            valor = colores.get(clave)
            if isinstance(valor, str) and _HEX.match(valor):
                tinta[clave] = valor.lower()
    nombre = crudo.get("name")
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
