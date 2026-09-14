"""Pruebas del tarificador.

Lo critico aqui no es que el calculo sea correcto (lo es trivialmente), sino que
el sistema NUNCA invente un precio: un numero fabricado contamina exactamente la
metrica que el proyecto existe para hacer verificable.
"""

from __future__ import annotations

import json

import pytest

from lymi.ledger.pricing import (
    ANTHROPIC_PRICES,
    Billing,
    ModelPrice,
    compute_cost,
    load_overrides,
    price_for,
)


class TestModelPrice:
    def test_costo_entrada_y_salida(self) -> None:
        p = ModelPrice(input_per_mtok=5.0, output_per_mtok=25.0, context_window=1_000_000)
        # 1M de entrada + 1M de salida = 5 + 25
        assert p.cost(input_tokens=1_000_000, output_tokens=1_000_000) == pytest.approx(30.0)

    def test_lectura_de_cache_cuesta_una_decima(self) -> None:
        p = ModelPrice(5.0, 25.0, 1_000_000)
        completo = p.cost(input_tokens=1_000_000)
        cacheado = p.cost(cache_read_tokens=1_000_000)
        assert cacheado == pytest.approx(completo * 0.10)

    def test_escritura_de_cache_cuesta_un_cuarto_mas(self) -> None:
        p = ModelPrice(5.0, 25.0, 1_000_000)
        assert p.cost(cache_write_tokens=1_000_000) == pytest.approx(6.25)

    def test_cero_tokens_cuesta_cero(self) -> None:
        assert ModelPrice(5.0, 25.0, 1_000_000).cost() == 0.0


class TestTarifasConocidas:
    def test_opus_5_tiene_tarifa(self) -> None:
        p = price_for("claude-opus-5")
        assert p is not None
        assert (p.input_per_mtok, p.output_per_mtok) == (5.00, 25.00)

    def test_modelo_desconocido_no_tiene_tarifa(self) -> None:
        assert price_for("modelo-que-no-existe") is None

    def test_ids_sin_sufijo_de_fecha(self) -> None:
        # Un ID con fecha seria un ID inventado y tarificaria mal.
        assert all(not k[-1].isdigit() or "-20" not in k for k in ANTHROPIC_PRICES)


class TestComputeCost:
    def test_local_cuesta_cero(self) -> None:
        assert compute_cost("qwen3:4b", Billing.LOCAL, input_tokens=999_999) == 0.0

    def test_suscripcion_no_es_comparable(self) -> None:
        # None, no 0.0: el marginal es cero pero NO se puede sumar con el modo api.
        assert compute_cost("claude-opus-5", Billing.SUBSCRIPTION, input_tokens=1000) is None

    def test_acepta_el_id_con_fecha_del_proveedor(self) -> None:
        # Claude Code reporta `claude-haiku-4-5-20251001`; la tabla usa el id base.
        con_fecha = compute_cost("claude-haiku-4-5-20251001", Billing.API, input_tokens=1_000_000)
        assert con_fecha == compute_cost("claude-haiku-4-5", Billing.API, input_tokens=1_000_000)

    def test_no_adivina_familias_por_parecido(self) -> None:
        # Solo se quita un sufijo de fecha exacto: un alias no es un id.
        assert compute_cost("opus", Billing.API, input_tokens=1_000) is None
        assert compute_cost("claude-haiku-4-5-beta", Billing.API, input_tokens=1_000) is None

    def test_modelo_sin_tarifa_devuelve_none_no_cero(self) -> None:
        assert compute_cost("modelo-fantasma", Billing.API, input_tokens=1_000_000) is None

    def test_api_con_tarifa_conocida(self) -> None:
        costo = compute_cost("claude-opus-5", Billing.API, input_tokens=1_000_000)
        assert costo == pytest.approx(5.0)


class TestOverrides:
    def test_carga_tarifas_desde_json(self, tmp_path, monkeypatch) -> None:
        f = tmp_path / "prices.json"
        f.write_text(
            json.dumps(
                {"mi-modelo": {"input_per_mtok": 2.0, "output_per_mtok": 8.0,
                               "context_window": 128_000}}
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr("lymi.ledger.pricing._OVERRIDES", {})
        assert load_overrides(f) == 1
        p = price_for("mi-modelo")
        assert p is not None and p.input_per_mtok == 2.0

    def test_sin_archivo_no_falla(self, tmp_path) -> None:
        assert load_overrides(tmp_path / "no-existe.json") == 0
