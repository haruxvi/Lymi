"""Que haria un workflow, sin ejecutar nada y sin gastar un token.

Responde las preguntas que conviene hacerse antes de darle al boton: cuantos
pasos se pagan, cuales tocan cosas fuera de lymi, y cuales dependen de una
condicion.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from lymi.flows.schema import (
    AgenciaStep,
    CodigoStep,
    HttpStep,
    LlmStep,
    PcStep,
    ToolStep,
    TransformStep,
    WebStep,
    Workflow,
)


@dataclass(frozen=True, slots=True)
class FilaPlan:
    id: str
    tipo: str
    destino: str
    condicion: str | None
    efectos: bool
    costo: str
    """gratis | tokens remotos | externo"""


@dataclass(frozen=True, slots=True)
class ResumenPlan:
    total: int
    locales: int
    remotos: int
    externos: int
    gratis: int
    con_efectos: int
    condicionales: int


def _costo_agencia(archivo: str) -> str:
    """Lee la agencia para decir si algun agente usa el modelo remoto. Sin ejecutar nada."""
    from lymi.agencia import AgenciaError, cargar_agencia

    try:
        agencia = cargar_agencia(archivo)
    except AgenciaError:
        return "externo"  # no se pudo leer: el lado prudente
    remotos = any(a.tier == "remote" for a in agencia.agentes().values())
    webs = any(h.startswith("web.") for a in agencia.agentes().values() for h in a.herramientas)
    return "tokens remotos" if remotos else "externo" if webs else "gratis"


def planificar(flujo: Workflow) -> list[FilaPlan]:
    filas: list[FilaPlan] = []
    for paso in flujo.steps:
        if isinstance(paso, LlmStep):
            destino = "modelo local" if paso.tier == "local" else "modelo remoto"
            costo = "gratis" if paso.tier == "local" else "tokens remotos"
        elif isinstance(paso, TransformStep):
            destino, costo = "en memoria", "gratis"
        elif isinstance(paso, ToolStep):
            destino, costo = f"mcp {paso.integration}.{paso.tool}", "externo"
        elif isinstance(paso, HttpStep):
            host = urlparse(paso.url).hostname or "?"
            destino, costo = f"{paso.method} {host}", "externo"
        elif isinstance(paso, AgenciaStep):
            costo = _costo_agencia(paso.archivo)
            destino = f"agencia {paso.archivo} -> {paso.agente or 'enrutada'} (sus agentes piden aprobacion)"
        elif isinstance(paso, CodigoStep):
            objetivo = paso.consulta or paso.nombre or paso.ruta or ""
            destino, costo = f"este PC: codigo {paso.op} {objetivo}".rstrip(), "gratis"
        elif isinstance(paso, WebStep):
            objetivo = paso.url or paso.consulta or paso.pregunta or "?"
            destino = f"web: {paso.op} {objetivo}"[:90]
            costo = "tokens remotos" if paso.op == "investigar" and paso.tier == "remote" else "externo"
        elif isinstance(paso, PcStep):
            objetivo = paso.comando if paso.op == "ejecutar" else paso.ruta
            destino, costo = f"este PC: {paso.op} {objetivo}", "gratis"
        else:  # pragma: no cover - el esquema no admite otros tipos
            destino, costo = "?", "?"
        filas.append(FilaPlan(paso.id, paso.type, destino, paso.when, paso.efectos, costo))
    return filas


def resumir(filas: list[FilaPlan]) -> ResumenPlan:
    return ResumenPlan(
        total=len(filas),
        locales=sum(1 for f in filas if f.destino == "modelo local"),
        remotos=sum(1 for f in filas if f.costo == "tokens remotos"),
        externos=sum(1 for f in filas if f.costo == "externo"),
        gratis=sum(1 for f in filas if f.costo == "gratis"),
        con_efectos=sum(1 for f in filas if f.efectos),
        condicionales=sum(1 for f in filas if f.condicion),
    )
