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


_CAMPOS_PC = {
    "leer": {"ruta"},
    "listar": {"ruta"},
    "escribir": {"ruta", "contenido"},
    "mover": {"ruta", "destino"},
    "borrar": {"ruta"},
    "ejecutar": {"comando"},
}


class PcStep(_Paso):
    """Accion sobre este PC a traves del ejecutor del host: nunca un shell.

    Las rutas y comandos se juzgan contra el perfil (`ejecutor.yml`) al ejecutar;
    aqui se valida la forma. Escribir, mover, borrar y ejecutar piden aprobacion.
    """

    type: Literal["pc"]
    op: Literal["leer", "listar", "escribir", "mover", "borrar", "ejecutar"]
    ruta: str | None = None
    destino: str | None = None
    contenido: str | None = None
    comando: str | None = None
    args: list[str] = []

    @property
    def efectos(self) -> bool:
        return self.op in {"escribir", "mover", "borrar", "ejecutar"}

    @model_validator(mode="after")
    def _campos(self) -> PcStep:
        presentes = {c for c in ("ruta", "destino", "contenido", "comando") if getattr(self, c) is not None}
        requeridos = _CAMPOS_PC[self.op]
        if faltan := requeridos - presentes:
            raise ValueError(f"paso {self.id!r}: op {self.op} requiere {', '.join(sorted(faltan))}")
        if sobran := presentes - requeridos:
            raise ValueError(f"paso {self.id!r}: op {self.op} no admite {', '.join(sorted(sobran))}")
        if self.args and self.op != "ejecutar":
            raise ValueError(f"paso {self.id!r}: args solo aplica a op ejecutar")
        return self


_CAMPOS_WEB = {
    "extraer": {"url"},
    "mapear": {"url"},
    "buscar": {"consulta"},
    "investigar": {"pregunta"},
}


class WebStep(_Paso):
    """Lectura de la web hecha por lymi: pagina a markdown, mapa, busqueda o investigacion.

    No cambia nada afuera, asi que no pide aprobacion; pero cada peticion es egress
    y queda en el ledger, y nunca alcanza la red interna.
    """

    type: Literal["web"]
    op: Literal["extraer", "mapear", "buscar", "investigar"]
    url: str | None = None
    consulta: str | None = None
    pregunta: str | None = None
    urls: list[str] | str = []
    """Solo investigar: fuentes fijas en vez de buscar. Admite una plantilla que produzca una lista."""
    tier: Literal["local", "remote"] = "local"
    """Solo investigar: quien redacta la respuesta."""
    max_paginas: int = Field(20, ge=1, le=200)
    profundidad: int = Field(1, ge=0, le=3)
    max_resultados: int = Field(5, ge=1, le=20)

    @model_validator(mode="after")
    def _campos(self) -> WebStep:
        presentes = {c for c in ("url", "consulta", "pregunta") if getattr(self, c) is not None}
        requeridos = _CAMPOS_WEB[self.op]
        if faltan := requeridos - presentes:
            raise ValueError(f"paso {self.id!r}: op {self.op} requiere {', '.join(sorted(faltan))}")
        if sobran := presentes - requeridos:
            raise ValueError(f"paso {self.id!r}: op {self.op} no admite {', '.join(sorted(sobran))}")
        if self.urls and self.op != "investigar":
            raise ValueError(f"paso {self.id!r}: urls solo aplica a op investigar")
        if self.url is not None and _usa_env(self.url):
            raise ValueError(f"paso {self.id!r}: una URL publica no lleva ${{VARIABLE}}; los secretos no se leen en la web")
        return self


_CAMPOS_CODIGO = {
    "buscar": ({"consulta"}, set()),
    "esqueleto": ({"ruta"}, set()),
    "fragmento": ({"nombre"}, set()),
    "llamadores": ({"nombre"}, set()),
    "impacto": ({"nombre"}, set()),
    "mapa": (set(), {"ruta"}),
}


class CodigoStep(_Paso):
    """Consulta al mapa del codigo de un repositorio: local, de solo lectura, gratis.

    La salida trae `texto` (compacto, para un prompt) y `datos` (para encadenar).
    La raiz se juzga contra el perfil del ejecutor, igual que una lectura del PC.
    """

    type: Literal["codigo"]
    op: Literal["buscar", "esqueleto", "fragmento", "llamadores", "impacto", "mapa"]
    raiz: str = "."
    consulta: str | None = None
    ruta: str | None = None
    """esqueleto: el archivo. mapa: prefijo de carpeta opcional."""
    nombre: str | None = None
    profundidad: int = Field(3, ge=1, le=6)

    @model_validator(mode="after")
    def _campos(self) -> CodigoStep:
        presentes = {c for c in ("consulta", "ruta", "nombre") if getattr(self, c) is not None}
        requeridos, opcionales = _CAMPOS_CODIGO[self.op]
        if faltan := requeridos - presentes:
            raise ValueError(f"paso {self.id!r}: op {self.op} requiere {', '.join(sorted(faltan))}")
        if sobran := presentes - requeridos - opcionales:
            raise ValueError(f"paso {self.id!r}: op {self.op} no admite {', '.join(sorted(sobran))}")
        return self


class AgenciaStep(_Paso):
    """Entrega una tarea a un departamento o agente de una agencia (`lymi agencia`).

    El paso no pide aprobacion: la piden los agentes, efecto por efecto, con el
    mismo aprobador del workflow. Por eso no se reintenta: una segunda corrida
    podria repetir efectos ya aprobados.
    """

    type: Literal["agencia"]
    archivo: str
    tarea: str = Field(min_length=1)
    agente: str | None = None
    """`departamento`, `departamento.agente` o `agente`. Sin esto, enruta la agencia."""

    @model_validator(mode="after")
    def _sin_reintentos(self) -> AgenciaStep:
        if self.retries:
            raise ValueError(f"paso {self.id!r}: un paso agencia no se reintenta (sus agentes pueden tener efectos)")
        return self


Step = Annotated[
    LlmStep | ToolStep | HttpStep | TransformStep | PcStep | WebStep | CodigoStep | AgenciaStep,
    Field(discriminator="type"),
]


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
