"""Piezas que comparten las rutas de la API: errores, cuerpo JSON, nombres validos."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from starlette.requests import Request

LIMITE_CUERPO = 64_000
ARCHIVO_YAML = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}\.ya?ml$")


class ErrorApi(Exception):
    def __init__(self, estado: int, mensaje: str) -> None:
        super().__init__(mensaje)
        self.estado = estado


async def cuerpo(request: Request, limite: int = LIMITE_CUERPO) -> dict[str, Any]:
    crudo = b""
    async for trozo in request.stream():
        crudo += trozo
        if len(crudo) > limite:
            raise ErrorApi(413, f"el cuerpo supera {limite} bytes")
    try:
        valor = json.loads(crudo or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ErrorApi(400, "el cuerpo no es JSON valido") from None
    if not isinstance(valor, dict):
        raise ErrorApi(400, "se esperaba un objeto JSON")
    return valor


def archivo_en(carpeta: Path, nombre: str, *, existente: bool = True) -> Path | None:
    """El YAML pedido, solo si es un archivo directamente dentro de la carpeta."""
    if not ARCHIVO_YAML.match(nombre):
        return None
    ruta = carpeta / nombre
    try:
        if ruta.resolve().parent != carpeta.resolve():
            return None
        if existente and not ruta.is_file():
            return None
    except OSError:
        return None
    return ruta


def entero(valor: Any, defecto: int, minimo: int, maximo: int) -> int:
    try:
        numero = int(valor) if valor is not None else defecto
    except (TypeError, ValueError):
        numero = defecto
    return max(minimo, min(maximo, numero))


def texto(valor: Any, campo: str, *, maximo: int = 2000, obligatorio: bool = True) -> str:
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        if obligatorio:
            raise ErrorApi(400, f"falta {campo}")
        return ""
    if not isinstance(valor, str):
        raise ErrorApi(400, f"{campo} debe ser texto")
    if len(valor) > maximo:
        raise ErrorApi(400, f"{campo} supera {maximo} caracteres")
    return valor.strip()


def tier(valor: Any) -> str:
    if valor in (None, ""):
        return "local"
    if valor not in ("local", "remote"):
        raise ErrorApi(400, "tier debe ser local o remote")
    return str(valor)
