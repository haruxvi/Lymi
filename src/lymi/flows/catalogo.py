"""Importador de catalogos de integraciones MCP.

Lee el formato `manifest.yaml` del catalogo de Hermes Agent (MIT) y lo convierte
en una integracion de lymi lista para pegar en un workflow.

Nunca instala nada ni ejecuta comandos del manifiesto. Un paso de `bootstrap` es
codigo ajeno: se muestra para que una persona lo lea y lo corra, porque
ejecutarlo sin mirar es exactamente como entra un ataque de cadena de suministro.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from lymi.flows.schema import McpIntegration

VERSIONES_SOPORTADAS = frozenset({1})
_SHA_COMPLETO = re.compile(r"^[0-9a-f]{40}$")


class CatalogoError(ValueError):
    """El manifiesto no se puede convertir en una integracion valida."""


@dataclass(frozen=True, slots=True)
class VariableRequerida:
    nombre: str
    descripcion: str
    secreta: bool
    requerida: bool
    defecto: str | None = None


@dataclass(slots=True)
class Importacion:
    nombre: str
    descripcion: str
    integracion: McpIntegration
    fuente: str | None = None
    variables: list[VariableRequerida] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    instalacion_manual: str | None = None
    """Pasos para que una persona instale el servidor. lymi no los ejecuta."""
    notas: str | None = None

    def como_yaml(self) -> str:
        """Bloque listo para pegar bajo `integrations:` en un workflow."""
        cabecera = [f"# {self.nombre}: {self.descripcion}" if self.descripcion else f"# {self.nombre}"]
        if self.fuente:
            cabecera.append(f"# fuente: {self.fuente}")
        cabecera.extend(f"# aviso: {aviso}" for aviso in self.avisos)
        cuerpo = yaml.safe_dump(
            {self.nombre: self.integracion.model_dump(exclude_defaults=True)},
            allow_unicode=True,
            sort_keys=False,
        )
        return "\n".join(cabecera) + "\n" + cuerpo


def _normalizar_nombre(nombre: str) -> str:
    limpio = re.sub(r"[^a-z0-9_]+", "_", nombre.lower()).strip("_")
    if not limpio or not limpio[0].isalpha():
        limpio = f"mcp_{limpio}".rstrip("_")
    return limpio[:40]


def _variables(auth: dict[str, Any]) -> list[VariableRequerida]:
    salida: list[VariableRequerida] = []
    for v in auth.get("env") or []:
        if not isinstance(v, dict) or not v.get("name"):
            continue
        defecto = v.get("default")
        salida.append(
            VariableRequerida(
                nombre=str(v["name"]),
                descripcion=str(v.get("prompt") or ""),
                # Sin declarar se asume secreta: equivocarse hacia el lado seguro.
                secreta=bool(v.get("secret", True)),
                requerida=bool(v.get("required", True)),
                defecto=None if defecto is None else str(defecto),
            )
        )
    return salida


def _instrucciones_git(instalacion: dict[str, Any], avisos: list[str]) -> str:
    url = instalacion.get("url") or "<url>"
    ref = str(instalacion.get("ref") or "")
    if not _SHA_COMPLETO.fullmatch(ref):
        avisos.append(
            f"la instalacion git apunta a {ref or 'ninguna referencia'!r}, no a un SHA completo: "
            "una rama o una etiqueta se pueden mover bajo tus pies"
        )
    lineas = [
        "Revisa el codigo antes de ejecutar nada. lymi no corre estos comandos por ti.",
        f"git clone {url} <carpeta>",
    ]
    if ref:
        lineas.append(f"git -C <carpeta> checkout {ref}")
    lineas.extend(f"(dentro de <carpeta>) {comando}" for comando in instalacion.get("bootstrap") or [])
    return "\n".join(lineas)


def importar_datos(datos: Any, *, origen: str = "manifiesto") -> Importacion:
    """Convierte un manifiesto ya parseado en una integracion de lymi."""
    if not isinstance(datos, dict):
        raise CatalogoError(f"{origen}: se esperaba un mapa en la raiz")

    version = datos.get("manifest_version")
    if version not in VERSIONES_SOPORTADAS:
        raise CatalogoError(f"{origen}: manifest_version {version!r} no soportada")

    original = str(datos.get("name") or "")
    if not original:
        raise CatalogoError(f"{origen}: falta name")
    nombre = _normalizar_nombre(original)
    avisos: list[str] = []
    if nombre != original:
        avisos.append(f"nombre ajustado de {original!r} a {nombre!r}")

    transporte = datos.get("transport") or {}
    auth = datos.get("auth") or {}
    tipo_auth = auth.get("type", "none")
    variables = _variables(auth)

    habilitadas = (datos.get("tools") or {}).get("default_enabled")
    tools = [str(t) for t in habilitadas] if isinstance(habilitadas, list) else None
    if tools is None:
        avisos.append(
            "el manifiesto no declara herramientas por defecto: quedan todas habilitadas; "
            "revisa cuales mutan"
        )

    campos: dict[str, Any] = {"type": "mcp", "tools": tools}
    tipo = transporte.get("type")

    if tipo == "http":
        campos.update(transport="http", url=transporte.get("url"))
        if tipo_auth == "oauth":
            campos["auth"] = "oauth"
        elif tipo_auth == "api_key" and variables:
            avisos.append(
                "clave de API sobre http: el manifiesto no dice en que encabezado va; "
                "anadela en headers como ${VARIABLE}"
            )
    elif tipo == "stdio":
        comando = transporte.get("command")
        argumentos = [str(a) for a in transporte.get("args") or []]
        campos.update(
            transport="stdio",
            command=comando,
            args=argumentos,
            env={v.nombre: "${" + v.nombre + "}" for v in variables},
        )
        if tipo_auth == "oauth":
            avisos.append("OAuth sobre stdio no esta soportado: el servidor debe autenticarse por su cuenta")
        if "${INSTALL_DIR}" in str(comando) or any("${INSTALL_DIR}" in a for a in argumentos):
            avisos.append("reemplaza ${INSTALL_DIR} por la carpeta donde clonaste el servidor")
    else:
        raise CatalogoError(f"{origen}: transport.type {tipo!r} no soportado (se admite stdio o http)")

    instalacion = datos.get("install") or {}
    manual = _instrucciones_git(instalacion, avisos) if instalacion.get("type") == "git" else None

    try:
        integracion = McpIntegration.model_validate({k: v for k, v in campos.items() if v is not None})
    except ValidationError as exc:
        motivos = "; ".join(str(e["msg"]) for e in exc.errors())
        raise CatalogoError(f"{origen}: {motivos}") from None

    fuente = datos.get("source")
    return Importacion(
        nombre=nombre,
        descripcion=str(datos.get("description") or "").strip(),
        integracion=integracion,
        fuente=None if fuente is None else str(fuente),
        variables=variables,
        avisos=avisos,
        instalacion_manual=manual,
        notas=datos.get("post_install") or None,
    )


def importar_manifiesto(ruta: str | Path) -> Importacion:
    """Lee un `manifest.yaml` y lo convierte en una integracion de lymi."""
    p = Path(ruta)
    try:
        datos = yaml.safe_load(p.read_text(encoding="utf-8"))
    except OSError as exc:
        raise CatalogoError(f"no se pudo leer {p}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise CatalogoError(f"{p} no es YAML valido: {exc}") from exc
    return importar_datos(datos, origen=str(p))
