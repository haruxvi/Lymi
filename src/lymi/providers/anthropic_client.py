"""Proveedor Anthropic via SDK oficial.

Este adaptador existe en vez de un shim normalizador porque la telemetria de
cache (`cache_read_input_tokens` / `cache_creation_input_tokens`) es la metrica
central de la Fase 2, y una capa que la aplane nos deja ciegos justo donde
tenemos que medir.
"""

from __future__ import annotations

import os
import time
from typing import Any

import anthropic

from lymi.ledger import Billing
from lymi.providers.base import Completion, Message, Usage

DEFAULT_MODEL = "claude-opus-5"


class AnthropicClient:
    """Cliente a nivel mensaje. lymi controla el contexto, asi que aqui es donde
    el ahorro es demostrable."""

    provider = "anthropic"
    tier = "frontier"

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        *,
        effort: str = "high",
        thinking: bool = True,
        client: anthropic.Anthropic | None = None,
    ) -> None:
        self.model = model
        self.effort = effort
        self.thinking = thinking
        # El SDK resuelve credenciales solo: ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN,
        # o un perfil de `ant auth login`. No pedimos ni guardamos la clave.
        self._client = client or anthropic.Anthropic()
        self.billing = Billing.API

    def complete(
        self,
        messages: list[Message],
        *,
        system: str | None = None,
        max_tokens: int = 16000,
        cache_system: bool = False,
    ) -> Completion:
        params: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "output_config": {"effort": self.effort},
        }
        if self.thinking:
            params["thinking"] = {"type": "adaptive"}

        if system is not None:
            if cache_system:
                # El prefijo estable se cachea; lo volatil va en `messages`, despues
                # del breakpoint. Cualquier byte que cambie aqui invalida todo.
                params["system"] = [
                    {
                        "type": "text",
                        "text": system,
                        "cache_control": {"type": "ephemeral", "ttl": "1h"},
                    }
                ]
            else:
                params["system"] = system

        started = time.perf_counter()
        # Los errores del SDK ya vienen tipados (RateLimitError, APIStatusError...):
        # suben intactos para que quien llama distinga lo reintentable de lo fatal.
        resp = self._client.messages.create(**params)
        latency_ms = int((time.perf_counter() - started) * 1000)

        text = "".join(b.text for b in resp.content if b.type == "text")
        u = resp.usage
        return Completion(
            text=text,
            usage=Usage(
                input_tokens=u.input_tokens,
                output_tokens=u.output_tokens,
                cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
                cache_write_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
            ),
            model=resp.model,
            provider=self.provider,
            billing=self.billing,
            tier=self.tier,
            latency_ms=latency_ms,
            stop_reason=resp.stop_reason,
            raw=resp,
        )


def available() -> bool:
    """True si hay alguna credencial de Anthropic utilizable."""
    return bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))
