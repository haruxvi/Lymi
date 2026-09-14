"""Esquema de un workflow.

Todo lo que se pueda detectar sin correr el workflow se detecta aqui, al cargar:
ids duplicados, integraciones inexistentes o del tipo equivocado, condiciones con
construcciones prohibidas, y -- lo mas util -- pasos que leen la salida de un
paso que todavia no se ha ejecutado. Un error de validacion cuesta cero tokens;
el mismo error descubierto a mitad de una corrida cuesta todos los anteriores.
"""

from __future__ import annotations

import ipaddress
import re
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from lymi.flows import condition, template

ID = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")]

_ENV = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}")


def _usa_env(valor: Any) -> bool:
    """Si algun texto dentro de `valor` referencia una variable de entorno."""
    if isinstance(valor, str):
        return bool(_ENV.search(valor))
    if isinstance(valor, dict):
        return any(_usa_env(v) for v in valor.values())
    if isinstance(valor, list):
        return any(_usa_env(v) for v in valor)
    return False


def _es_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# ---------------------------------------------------------------- integraciones


class McpIntegration(_Base):
    """Servidor MCP: local por stdio o remoto por HTTP."""

    type: Literal["mcp"]
    transport: Literal["stdio", "http"] = "stdio"

    command: str | None = None
    args: list[str] = []
    env: dict[str, str] = {}
    """Solo stdio. Admite `${VARIABLE}`: los secretos viven en el entorno, nunca en el YAML."""

    url: str | None = None
    headers: dict[str, str] = {}
    """Solo http. Admite `${VARIABLE}`; los encabezados no se registran en el ledger."""
    auth: Literal["none", "oauth"] = "none"
    scopes: list[str] = []

    tools: list[str] | None = None
    """Herramientas habilitadas; `None` significa todas. Un catalogo importado trae
    solo las de lectura: las que mutan se habilitan a proposito."""

    @model_validator(mode="after")
    def _transporte(self) -> McpIntegration:
        if self.transport == "stdio":
            if not self.command:
                raise ValueError("transport stdio requiere command")
            if self.url or self.headers or self.auth != "none" or self.scopes:
                raise ValueError("url, headers, auth y scopes solo aplican a transport http")
            return self

        if not self.url:
            raise ValueError("transport http requiere url")
        if self.command or self.args or self.env:
            raise ValueError("command, args y env solo aplican a transport stdio")
        partes = urlparse(self.url)
        host = (partes.hostname or "").lower()
        if not host:
            raise ValueError(f"url sin host: {self.url!r}")
        if partes.scheme != "https" and not (partes.scheme == "http" and _es_loopback(host)):
            raise ValueError("un servidor MCP remoto exige https (http solo hacia loopback)")
        return self


class HttpIntegration(_Base):
    """Destino HTTP con lista blanca de hosts."""

    type: Literal["http"]
    allow_hosts: list[str] = Field(min_length=1)
    headers: dict[str, str] = {}
    """Admite `${VARIABLE}`. Los encabezados no se registran en el ledger."""


Integration = Annotated[McpIntegration | HttpIntegration, Field(discriminator="type")]


# ---------------------------------------------------------------- pasos


class _Paso(_Base):
    id: ID
    when: str | None = None
    retries: int = Field(0, ge=0, le=5)
    timeout_s: float = Field(120, gt=0, le=3600)

    @property
    def efectos(self) -> bool:
        """Si el paso cambia algo fuera de lymi. Los que si, requieren aprobacion."""
        return False


class LlmStep(_Paso):
    type: Literal["llm"]
    tier: Literal["local", "remote"]
    prompt: str
    system: str | None = None
    output: Literal["text", "json"] = "text"
    max_tokens: int = Field(4096, gt=0, le=128_000)


class ToolStep(_Paso):
    type: Literal["tool"]
    integration: str
    tool: str
    args: dict[str, Any] = {}
    side_effect: bool = True
    """Por defecto se asume que una herramienta ajena cambia cosas. Declararla
    `false` es una afirmacion explicita de quien escribe el workflow."""

    @property
    def efectos(self) -> bool:
        return self.side_effect


class HttpStep(_Paso):
    type: Literal["http"]
    integration: str
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = "GET"
    url: str
    body: Any = None
    side_effect: bool | None = None

    @property
    def efectos(self) -> bool:
        return self.side_effect if self.side_effect is not None else self.method != "GET"


class TransformStep(_Paso):
    """Arma datos a partir de pasos anteriores. No llama a nadie: cuesta cero."""

    type: Literal["transform"]
    set: dict[str, Any]


Step = Annotated[LlmStep | ToolStep | HttpStep | TransformStep, Field(discriminator="type")]


class InputSpec(_Base):
    type: Literal["string", "number", "boolean", "object"] = "string"
    required: bool = True
    default: Any = None
    description: str | None = None


# ---------------------------------------------------------------- workflow


class Workflow(_Base):
    name: ID
    description: str | None = None
    inputs: dict[str, InputSpec] = {}
    integrations: dict[str, Integration] = {}
    steps: list[Step] = Field(min_length=1)

    @model_validator(mode="after")
    def _coherencia(self) -> Workflow:
        vistos: set[str] = set()
        for paso in self.steps:
            if paso.id in vistos:
                raise ValueError(f"paso {paso.id!r} duplicado")

            if paso.efectos and paso.retries:
                raise ValueError(
                    f"paso {paso.id!r}: un paso con efectos no se reintenta -- podria "
                    "ejecutarse dos veces (dos correos, dos cobros)"
                )

            if _usa_env(paso.model_dump(exclude={"id", "type", "url"})):
                raise ValueError(
                    f"paso {paso.id!r}: ${{VARIABLE}} solo se admite en integrations y en la "
                    "url de un paso http; en un prompt o en argumentos el secreto acabaria en "
                    "el modelo, en una herramienta ajena o en un log"
                )

            if isinstance(paso, (ToolStep, HttpStep)):
                integ = self.integrations.get(paso.integration)
                if integ is None:
                    raise ValueError(f"paso {paso.id!r}: integracion {paso.integration!r} no declarada")
                esperado = "mcp" if isinstance(paso, ToolStep) else "http"
                if integ.type != esperado:
                    raise ValueError(
                        f"paso {paso.id!r}: la integracion {paso.integration!r} es {integ.type}, "
                        f"se esperaba {esperado}"
                    )
                if isinstance(paso, ToolStep) and integ.tools is not None and paso.tool not in integ.tools:
                    raise ValueError(
                        f"paso {paso.id!r}: la herramienta {paso.tool!r} no esta habilitada en "
                        f"{paso.integration!r} (habilitadas: {', '.join(integ.tools) or 'ninguna'})"
                    )

            rutas = set(template.referencias(paso.model_dump(exclude={"id", "type", "when"})))
            if paso.when:
                try:
                    condition.validar(paso.when)
                except condition.ConditionError as exc:
                    raise ValueError(f"paso {paso.id!r}: condicion invalida: {exc}") from exc
                rutas |= condition.referencias(paso.when)

            for ruta in rutas:
                raiz, _, resto = ruta.partition(".")
                nombre = resto.split(".")[0] if resto else ""
                if raiz == "inputs" and nombre not in self.inputs:
                    raise ValueError(f"paso {paso.id!r}: usa inputs.{nombre}, que no esta declarado")
                if raiz == "steps" and nombre not in vistos:
                    motivo = "no existe" if nombre not in {s.id for s in self.steps} else "todavia no se ha ejecutado"
                    raise ValueError(f"paso {paso.id!r}: lee steps.{nombre}, que {motivo}")
                if raiz not in {"inputs", "steps"}:
                    raise ValueError(f"paso {paso.id!r}: {ruta!r} no empieza por inputs ni steps")

            vistos.add(paso.id)
        return self


class WorkflowError(ValueError):
    """El archivo no es un workflow valido. El mensaje explica donde y por que."""


def cargar(ruta: str | Path) -> Workflow:
    """Lee y valida un workflow YAML."""
    p = Path(ruta)
    try:
        datos = yaml.safe_load(p.read_text(encoding="utf-8"))
    except OSError as exc:
        raise WorkflowError(f"no se pudo leer {p}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise WorkflowError(f"{p} no es YAML valido: {exc}") from exc

    if not isinstance(datos, dict):
        raise WorkflowError(f"{p}: se esperaba un mapa en la raiz")

    try:
        return Workflow.model_validate(datos)
    except ValidationError as exc:
        lineas = []
        for e in exc.errors():
            donde = ".".join(str(x) for x in e["loc"]) or "(raiz)"
            lineas.append(f"  {donde}: {e['msg']}")
        raise WorkflowError(f"{p} no es un workflow valido:\n" + "\n".join(lineas)) from None
