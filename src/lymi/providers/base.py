"""Contratos de proveedor.

Hay DOS contratos distintos, deliberadamente:

- `LLMClient`  : nivel mensaje. lymi arma el contexto. Es el unico modo en el que
                 podemos demostrar ahorro, porque controlamos lo que se envia.
- `AgentBackend`: nivel tarea. Delegamos a un harness externo (Claude Code via
                 Agent SDK). Comodo y usa tu suscripcion, pero NO controlamos el
                 prompt: ahi el ahorro solo puede venir de entregarle menos trabajo.

Mezclarlos en una sola interfaz seria mentir sobre lo que el sistema controla.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from lymi.ledger import Billing


@dataclass(frozen=True, slots=True)
class Message:
    """Un turno de conversacion, agnostico de proveedor."""

    role: str  # "user" | "assistant"
    content: str


@dataclass(slots=True)
class Usage:
    """Consumo reportado por el proveedor. Los campos de cache son la telemetria
    central de la Fase 2: si `cache_read` no sube, el caché no esta funcionando."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


@dataclass(slots=True)
class Completion:
    """Respuesta de un modelo, mas todo lo que el ledger necesita registrar."""

    text: str
    usage: Usage
    model: str
    provider: str
    billing: Billing
    tier: str
    latency_ms: int
    stop_reason: str | None = None
    raw: Any = field(default=None, repr=False)


@runtime_checkable
class LLMClient(Protocol):
    """Proveedor a nivel mensaje: nosotros armamos el contexto."""

    provider: str
    model: str
    billing: Billing
    tier: str

    def complete(
        self,
        messages: list[Message],
        *,
        system: str | None = None,
        max_tokens: int = 4096,
        cache_system: bool = False,
    ) -> Completion:
        """Ejecuta una llamada.

        `cache_system` pide cachear el prefijo estable (sistema + herramientas).
        Los proveedores que no soportan cache lo ignoran y reportan cache_* = 0,
        que es exactamente lo que el reporte debe mostrar.
        """
        ...


@runtime_checkable
class AgentBackend(Protocol):
    """Harness externo a nivel tarea: el contexto lo maneja el, no nosotros."""

    provider: str
    billing: Billing

    def run_task(self, prompt: str, *, cwd: str | None = None) -> Completion:
        """Delega una tarea completa y devuelve el resultado con su consumo."""
        ...
