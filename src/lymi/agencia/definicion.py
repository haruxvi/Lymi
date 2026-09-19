"""La agencia: departamentos, agentes y quien puede pedirle trabajo a quien.

Se declara en YAML, como un workflow. Todo lo que se puede comprobar sin correr
se comprueba al cargar: herramientas que no existen, delegaciones hacia agentes
que no estan, roles en archivos fuera de la carpeta de la agencia.

Las aristas de delegacion son explicitas (`delega_a`). Un agente no puede
pedirle trabajo a otro que no este en su lista: la organizacion la dibuja quien
escribe el archivo, no el modelo.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from lymi.flows.schema import ID, WorkflowError, cargar

HERRAMIENTAS: dict[str, tuple[bool, str]] = {
    "web.extraer": (False, 'lee una pagina como markdown. args: {"url"}'),
    "web.buscar": (False, 'busca en la web con tu buscador. args: {"consulta"}'),
    "web.investigar": (False, 'responde con fuentes y citas verificadas. args: {"pregunta", "urls"?}'),
    "web.mapear": (False, 'URLs de un sitio. args: {"url"}'),
    "codigo.buscar": (False, 'busca funciones y clases por nombre. args: {"consulta", "raiz"?}'),
    "codigo.esqueleto": (False, 'firmas de un archivo sin cuerpos. args: {"ruta", "raiz"?}'),
    "codigo.fragmento": (False, 'codigo de una funcion o clase. args: {"nombre", "raiz"?}'),
    "codigo.llamadores": (False, 'quien llama a una funcion. args: {"nombre", "raiz"?}'),
    "codigo.impacto": (False, 'que codigo y pruebas toca un cambio. args: {"nombre", "raiz"?}'),
    "codigo.mapa": (False, 'archivos y dependencias. args: {"ruta"?, "raiz"?}'),
    "correo.listar": (False, 'tus correos recientes. args: {"carpeta"?, "n"?, "dias"?}'),
    "correo.leer": (False, 'un correo completo. args: {"mensaje": <numero>, "carpeta"?}'),
    "correo.resumen": (False, 'resumen del correo reciente, anotado por el modelo. args: {"dias"?, "n"?}'),
    "memoria.buscar": (False, 'busca en la memoria; marca lo SIN REVISAR. args: {"consulta"}'),
    "memoria.anotar": (
        False,
        (
            "anota algo para recordarlo; queda SIN REVISAR hasta que una persona lo promueva. "
            'args: {"texto", "fuente"}'
        ),
    ),
    "pc.leer": (False, 'lee un archivo permitido. args: {"ruta"}'),
    "pc.listar": (False, 'lista una carpeta permitida. args: {"ruta"}'),
    "pc.escribir": (True, 'escribe un archivo (pide aprobacion). args: {"ruta", "contenido"}'),
    "pc.mover": (True, 'mueve un archivo (pide aprobacion). args: {"ruta", "destino"}'),
    "pc.borrar": (True, 'borra un archivo al diario (pide aprobacion). args: {"ruta"}'),
    "pc.ejecutar": (True, 'corre un comando de la lista blanca (pide aprobacion). args: {"comando", "args"}'),
}
"""Nombre -> (tiene efectos, descripcion para el modelo). `workflow:<ruta>` se agrega aparte."""

MAX_BYTES_ROL = 20_000


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Limites(_Base):
    """Topes duros de una corrida. Todo el arbol de agentes los comparte."""

    profundidad: int = Field(3, ge=1, le=6)
    """Niveles de delegacion bajo la tarea inicial."""
    simultaneos: int = Field(3, ge=1, le=16)
    """Agentes llamando al modelo o a una herramienta al mismo tiempo."""
    agentes_totales: int = Field(12, ge=1, le=100)
    turnos_por_agente: int = Field(8, ge=1, le=50)
    llamadas: int = Field(60, ge=1, le=2000)
    """Llamadas a modelos de toda la corrida."""
    tokens_remotos: int | None = Field(None, gt=0)
    segundos: float = Field(900, gt=0, le=86_400)


class AgenteDef(_Base):
    descripcion: str = Field(min_length=1, max_length=500)
    rol: str = Field(min_length=1, max_length=MAX_BYTES_ROL)
    """El prompt del agente: que hace, que recibe, que entrega, sus reglas."""
    tier: Literal["local", "remote"] = "local"
    herramientas: list[str] = []
    delega_a: list[str] = []
    """`agente` (mismo departamento), `departamento.agente` o `departamento` (su lider)."""
    puede_crear: bool = False
    """Si puede crear ayudantes temporales, con un subconjunto de sus herramientas."""
    max_turnos: int | None = Field(None, ge=1, le=50)
    modelo: str | None = Field(None, pattern=r"^[\w.:/-]{1,80}$")
    """Solo tier local: el modelo de Ollama de este agente (ej. `qwen3:4b`). Sin esto, el de lymi."""
    respaldo: Literal["local"] | None = None
    """Solo tier remote: si la suscripcion o la API agotan su cuota, sigue con el local.
    El cambio queda avisado en la tarea: nunca se baja de modelo en silencio."""

    @model_validator(mode="after")
    def _modelo_segun_tier(self) -> AgenteDef:
        if self.modelo is not None and self.tier != "local":
            raise ValueError("`modelo` elige un modelo local; el remoto es el configurado en lymi")
        if self.respaldo is not None and self.tier != "remote":
            raise ValueError("`respaldo: local` solo tiene sentido en un agente remote")
        return self


class Departamento(_Base):
    descripcion: str = ""
    lider: ID | None = None
    """Quien recibe el trabajo dirigido al departamento. Por defecto, el primer agente."""
    agentes: dict[ID, AgenteDef] = Field(min_length=1)

    @property
    def jefe(self) -> str:
        return self.lider or next(iter(self.agentes))


class Agencia(_Base):
    name: ID
    description: str | None = None
    limites: Limites = Limites()
    departamentos: dict[ID, Departamento] = Field(min_length=1)
    workflows: dict[str, str] = {}
    """`workflow:<ruta>` usado por algun agente -> ruta resuelta. Lo llena el cargador."""

    @model_validator(mode="after")
    def _coherencia(self) -> Agencia:
        for nombre_dep, dep in self.departamentos.items():
            if dep.lider is not None and dep.lider not in dep.agentes:
                raise ValueError(f"departamento {nombre_dep!r}: el lider {dep.lider!r} no es uno de sus agentes")
        for nombre, agente in self.agentes().items():
            for herramienta in agente.herramientas:
                if herramienta not in HERRAMIENTAS and herramienta not in self.workflows:
                    raise ValueError(f"{nombre}: herramienta desconocida {herramienta!r}")
            for destino in agente.delega_a:
                resuelto = self.resolver(destino, desde=nombre)
                if resuelto is None:
                    raise ValueError(f"{nombre}: delega_a {destino!r} no es un agente ni un departamento")
                if resuelto == nombre:
                    raise ValueError(f"{nombre}: no puede delegarse a si mismo")
        return self

    def agentes(self) -> dict[str, AgenteDef]:
        """Todos los agentes por nombre completo: `departamento.agente`."""
        return {f"{d}.{a}": agente for d, dep in self.departamentos.items() for a, agente in dep.agentes.items()}

    def resolver(self, destino: str, *, desde: str | None = None) -> str | None:
        """`agente`, `departamento.agente` o `departamento` -> nombre completo, o None."""
        destino = destino.strip().lstrip("@")
        if "." in destino:
            dep, _, agente = destino.partition(".")
            return destino if dep in self.departamentos and agente in self.departamentos[dep].agentes else None
        if destino in self.departamentos:
            return f"{destino}.{self.departamentos[destino].jefe}"
        if desde is not None:
            dep_origen = desde.split(".")[0]
            if destino in self.departamentos[dep_origen].agentes:
                return f"{dep_origen}.{destino}"
        coincidencias = [n for n in self.agentes() if n.split(".")[1] == destino]
        return coincidencias[0] if len(coincidencias) == 1 else None

    def destinos(self, nombre: str) -> frozenset[str]:
        agente = self.agentes()[nombre]
        return frozenset(r for d in agente.delega_a if (r := self.resolver(d, desde=nombre)) is not None)


class AgenciaError(ValueError):
    """El archivo no es una agencia valida. El mensaje dice donde y por que."""


def _cargar_rol(valor: Any, carpeta: Path, donde: str) -> Any:
    """`rol: archivo:roles/x.md` lee el rol de un archivo dentro de la carpeta de la agencia."""
    if not isinstance(valor, str) or not valor.startswith("archivo:"):
        return valor
    ruta = (carpeta / valor.removeprefix("archivo:").strip()).resolve()
    if not ruta.is_relative_to(carpeta.resolve()):
        raise AgenciaError(f"{donde}: el rol {ruta} esta fuera de la carpeta de la agencia")
    try:
        datos = ruta.read_bytes()
    except OSError as exc:
        raise AgenciaError(f"{donde}: no se pudo leer el rol {ruta}: {exc}") from None
    if len(datos) > MAX_BYTES_ROL:
        raise AgenciaError(f"{donde}: el rol {ruta} supera {MAX_BYTES_ROL} bytes")
    return datos.decode("utf-8", errors="replace")


def cargar_agencia(ruta: str | Path) -> Agencia:
    p = Path(ruta)
    try:
        datos = yaml.safe_load(p.read_text(encoding="utf-8"))
    except OSError as exc:
        raise AgenciaError(f"no se pudo leer {p}: {exc}") from None
    except yaml.YAMLError as exc:
        raise AgenciaError(f"{p} no es YAML valido: {exc}") from None
    if not isinstance(datos, dict):
        raise AgenciaError(f"{p}: se esperaba un mapa en la raiz")
    if "workflows" in datos:
        raise AgenciaError(f"{p}: `workflows` lo calcula lymi; usa `workflow:<ruta>` en las herramientas")

    carpeta = p.parent
    workflows: dict[str, str] = {}
    for nombre_dep, dep in (datos.get("departamentos") or {}).items():
        for nombre_ag, agente in ((dep or {}).get("agentes") or {}).items():
            if not isinstance(agente, dict):
                continue
            donde = f"{nombre_dep}.{nombre_ag}"
            agente["rol"] = _cargar_rol(agente.get("rol"), carpeta, donde)
            for herramienta in agente.get("herramientas") or []:
                if isinstance(herramienta, str) and herramienta.startswith("workflow:"):
                    archivo = (carpeta / herramienta.removeprefix("workflow:").strip()).resolve()
                    try:
                        cargar(archivo)
                    except WorkflowError as exc:
                        raise AgenciaError(f"{donde}: {herramienta}: {exc}") from None
                    workflows[herramienta] = str(archivo)
    datos["workflows"] = workflows

    try:
        return Agencia.model_validate(datos)
    except ValidationError as exc:
        lineas = []
        for e in exc.errors():
            donde = ".".join(str(x) for x in e["loc"]) or "(raiz)"
            lineas.append(f"  {donde}: {e['msg']}")
        raise AgenciaError(f"{p} no es una agencia valida:\n" + "\n".join(lineas)) from None
