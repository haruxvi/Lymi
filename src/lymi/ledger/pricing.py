"""Tarificacion de modelos.

Regla del proyecto: si no conocemos la tarifa de un modelo, el costo es None y el
reporte lo declara como "sin tarifa". Nunca se inventa un precio, porque un
numero inventado contamina exactamente la metrica que este proyecto existe para
hacer verificable.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class Billing(StrEnum):
    """Como se paga una llamada. Determina si el costo en dolares tiene sentido."""

    API = "api"
    """Se paga por token. El costo en dolares es real y comparable."""

    SUBSCRIPTION = "subscription"
    """Cuota fija (Claude Code, ChatGPT Plus...). Se mide en tokens; los dolares
    marginales son cero y NO son comparables contra el modo API."""

    LOCAL = "local"
    """Corre en la maquina del usuario. Sin costo monetario; el costo real es
    latencia y VRAM, que se miden aparte."""

    NONE = "none"
    """No es una llamada a un modelo: una integracion (HTTP, herramienta MCP).
    No consume tokens ni tiene tarifa, pero se registra igual porque puede sacar
    datos de la maquina y el log de egress tiene que verla."""


@dataclass(frozen=True, slots=True)
class ModelPrice:
    """Tarifa por millon de tokens, mas los multiplicadores de cache."""

    input_per_mtok: float
    output_per_mtok: float
    context_window: int
    cache_write_multiplier: float = 1.25
    cache_read_multiplier: float = 0.10

    def cost(
        self,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
    ) -> float:
        m = 1_000_000
        return (
            input_tokens * self.input_per_mtok
            + output_tokens * self.output_per_mtok
            + cache_read_tokens * self.input_per_mtok * self.cache_read_multiplier
            + cache_write_tokens * self.input_per_mtok * self.cache_write_multiplier
        ) / m


# Tarifas directas de Anthropic, en USD por millon de tokens.
# Fuente: referencia oficial de la API. Ver PRICES_UPDATED.
PRICES_UPDATED = "2026-06-24"

ANTHROPIC_PRICES: dict[str, ModelPrice] = {
    "claude-fable-5-1": ModelPrice(10.00, 50.00, 1_000_000),
    "claude-fable-5": ModelPrice(10.00, 50.00, 1_000_000),
    "claude-opus-5": ModelPrice(5.00, 25.00, 1_000_000),
    "claude-opus-4-8": ModelPrice(5.00, 25.00, 1_000_000),
    "claude-opus-4-7": ModelPrice(5.00, 25.00, 1_000_000),
    "claude-opus-4-6": ModelPrice(5.00, 25.00, 1_000_000),
    "claude-sonnet-5": ModelPrice(2.00, 10.00, 1_000_000),
    "claude-sonnet-4-6": ModelPrice(3.00, 15.00, 1_000_000),
    "claude-haiku-4-5": ModelPrice(1.00, 5.00, 200_000),
}

# Deliberadamente vacio. Las tarifas de otros proveedores cambian seguido y no
# las vamos a adivinar: se cargan desde prices.json (ver load_overrides).
OTHER_PRICES: dict[str, ModelPrice] = {}

_OVERRIDES: dict[str, ModelPrice] = {}


def load_overrides(path: str | Path | None = None) -> int:
    """Carga tarifas desde JSON: {"modelo": {"input_per_mtok": 1.0, ...}}.

    Permite tarificar proveedores que no traemos cableados sin tocar el codigo.
    Devuelve cuantas tarifas se cargaron.
    """
    p = Path(path or os.getenv("LYMI_PRICES", "prices.json"))
    if not p.exists():
        return 0
    data = json.loads(p.read_text(encoding="utf-8"))
    for model, fields in data.items():
        _OVERRIDES[model] = ModelPrice(**fields)
    return len(_OVERRIDES)


_SUFIJO_FECHA = re.compile(r"-\d{8}$")


def price_for(model: str) -> ModelPrice | None:
    """Tarifa de un modelo, o None si no la conocemos.

    Acepta el id con fecha que reportan los proveedores
    (`claude-haiku-4-5-20251001`) ademas del id base de la tabla. Solo se quita
    un sufijo de fecha exacto: nunca se adivina una familia por parecido.
    """
    for nombre in dict.fromkeys((model, _SUFIJO_FECHA.sub("", model))):
        precio = _OVERRIDES.get(nombre) or ANTHROPIC_PRICES.get(nombre) or OTHER_PRICES.get(nombre)
        if precio is not None:
            return precio
    return None


def compute_cost(
    model: str,
    billing: Billing,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> float | None:
    """Costo en USD, o None si no aplica o no se conoce la tarifa.

    None no es cero: significa "no comparable". El reporte los distingue.
    """
    if billing is Billing.LOCAL or billing is Billing.NONE:
        return 0.0
    if billing is Billing.SUBSCRIPTION:
        # Marginal cero, pero NO comparable contra el modo API. Se reporta como
        # ausente para que nadie sume peras con manzanas.
        return None
    p = price_for(model)
    if p is None:
        return None
    return p.cost(input_tokens, output_tokens, cache_read_tokens, cache_write_tokens)
