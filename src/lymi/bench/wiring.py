"""Cableado de proveedores reales.

Arma las dos estrategias con lo que el usuario tenga instalado, en un orden de
preferencia explicito, y declara cual eligio. Si el sistema eligiera un proveedor
en silencio, el recibo diria "lymi" sin que nadie sepa contra que corrio.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from lymi.bench.strategies import BaselineAgent, LymiAgent
from lymi.providers.base import LLMClient


class SinProveedorRemotoError(RuntimeError):
    """No hay ningun proveedor remoto utilizable: no hay nada que medir."""


@dataclass(slots=True)
class Cableado:
    """Las estrategias listas, mas la constancia de con que se armaron."""

    base: BaselineAgent
    lymi: LymiAgent
    remoto: str
    local: str | None

    @property
    def resumen(self) -> str:
        tier = self.local or "sin tier local (solo cache)"
        return f"remoto: {self.remoto} · local: {tier}"


def _remoto() -> tuple[LLMClient, str]:
    """Elige proveedor remoto. Orden: suscripcion, Anthropic, OpenAI.

    La suscripcion va primera porque no tiene costo marginal: es lo que permite
    correr el banco de pruebas muchas veces sin que la factura decida cuanto se
    puede medir.
    """
    from lymi.providers import claude_code

    if claude_code.disponible():
        return claude_code.ClaudeCodeClient(model="opus"), "claude code (suscripcion)"

    if os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"):
        from lymi.providers.anthropic_client import AnthropicClient

        cliente = AnthropicClient()
        return cliente, f"anthropic api ({cliente.model})"

    raise SinProveedorRemotoError(
        "No hay proveedor remoto. Opciones:\n"
        "  - instala Claude Code y autentica con /login\n"
        "  - o define ANTHROPIC_API_KEY en .env\n"
        "Mientras tanto: lymi bench snake --demo"
    )


def _local() -> tuple[LLMClient, str] | tuple[None, None]:
    """Devuelve el tier local si esta utilizable. Nunca falla la corrida por su
    ausencia: sin el, lymi corre con la palanca de cache y lo declara."""
    import httpx

    from lymi.providers.local import OllamaClient

    try:
        cliente = OllamaClient()
        # Comprobar que responde: un cliente que no conecta convertiria cada
        # destilacion en una excepcion a mitad de corrida.
        httpx.get(f"{cliente.url}/api/tags", timeout=3.0).raise_for_status()
    except Exception:  # noqa: BLE001 - cualquier fallo aqui significa "no hay tier local"
        return None, None
    return cliente, f"ollama ({cliente.model})"


def cablear() -> Cableado:
    """Arma las estrategias con los proveedores disponibles."""
    remoto, etiqueta_remota = _remoto()
    local, etiqueta_local = _local()

    return Cableado(
        base=BaselineAgent(remoto),
        lymi=LymiAgent(remoto, local),
        remoto=etiqueta_remota,
        local=etiqueta_local,
    )


def proveedores() -> tuple[LLMClient | None, str | None, LLMClient | None, str | None]:
    """Local y remoto disponibles, sin exigir ninguno.

    A diferencia de `cablear`, no falla si falta el remoto: un workflow que solo
    usa pasos locales o integraciones no lo necesita, y si algun paso si, el motor
    lo reporta en ese paso con el arreglo.
    """
    local, etiqueta_local = _local()
    try:
        remoto, etiqueta_remota = _remoto()
    except SinProveedorRemotoError:
        remoto, etiqueta_remota = None, None
    return local, etiqueta_local, remoto, etiqueta_remota
