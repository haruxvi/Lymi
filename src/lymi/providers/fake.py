"""Proveedor guionado, para pruebas y demostraciones.

Permite ejercitar el sistema completo -- runner, ledger, recibo -- sin gastar
un centavo ni depender de la red. Es determinista: la misma corrida produce
los mismos numeros, que es justo lo que exige el criterio de reproducibilidad
de la Fase 0.

No simula calidad: entrega las respuestas que se le guionan. Sirve para validar
la tuberia de medicion, nunca para afirmar nada sobre ahorro real.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from lymi.ledger import Billing
from lymi.providers.base import Completion, Message, Usage


@dataclass(slots=True)
class ScriptedTurn:
    """Una respuesta guionada, con el consumo que debe reportar."""

    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    latency_ms: int = 0


class ScriptedClient:
    """Cliente que devuelve turnos guionados en orden."""

    def __init__(
        self,
        turns: list[ScriptedTurn],
        *,
        provider: str = "scripted",
        model: str = "claude-opus-5",
        billing: Billing = Billing.API,
        tier: str = "frontier",
    ) -> None:
        if not turns:
            raise ValueError("ScriptedClient necesita al menos un turno")
        self._turns = list(turns)
        self._i = 0
        self.provider = provider
        self.model = model
        self.billing = billing
        self.tier = tier

    @property
    def exhausted(self) -> bool:
        return self._i >= len(self._turns)

    def complete(
        self,
        messages: list[Message],
        *,
        system: str | None = None,
        max_tokens: int = 4096,
        cache_system: bool = False,
    ) -> Completion:
        if self.exhausted:
            raise RuntimeError(
                f"El guion se agoto tras {len(self._turns)} turnos: el agente pidio mas "
                "llamadas de las previstas."
            )
        turn = self._turns[self._i]
        self._i += 1

        # Sin cache_system el guion no puede reportar lecturas de cache: seria
        # mentir sobre la palanca que estamos midiendo.
        cache_read = turn.cache_read_tokens if cache_system else 0
        cache_write = turn.cache_write_tokens if cache_system else 0
        extra_input = 0 if cache_system else cache_read + cache_write

        return Completion(
            text=turn.text,
            usage=Usage(
                input_tokens=turn.input_tokens + extra_input,
                output_tokens=turn.output_tokens,
                cache_read_tokens=cache_read,
                cache_write_tokens=cache_write,
            ),
            model=self.model,
            provider=self.provider,
            billing=self.billing,
            tier=self.tier,
            latency_ms=turn.latency_ms,
            stop_reason="end_turn",
        )


@dataclass(slots=True)
class ScriptedLocalClient:
    """Tier local guionado: consume muchos tokens y no cuesta nada.

    Existe para que el recibo muestre la asimetria que define al proyecto --
    volumen alto en la maquina, volumen bajo hacia afuera.
    """

    turns: list[ScriptedTurn] = field(default_factory=list)
    provider: str = "ollama"
    model: str = "qwen3:4b"
    billing: Billing = Billing.LOCAL
    tier: str = "local"
    _i: int = 0

    def complete(
        self,
        messages: list[Message],
        *,
        system: str | None = None,
        max_tokens: int = 4096,
        cache_system: bool = False,
    ) -> Completion:
        if self._i >= len(self.turns):
            raise RuntimeError("El guion local se agoto")
        turn = self.turns[self._i]
        self._i += 1
        return Completion(
            text=turn.text,
            usage=Usage(input_tokens=turn.input_tokens, output_tokens=turn.output_tokens),
            model=self.model,
            provider=self.provider,
            billing=self.billing,
            tier=self.tier,
            latency_ms=turn.latency_ms,
            stop_reason="end_turn",
        )
