"""Pruebas del proveedor por suscripcion.

La mas importante es la primera clase: el CLI puede devolver `is_error: true`
junto con `subtype: "success"` y codigo de salida 0. Confiar en el subtipo
registraria fallos como exitos con 0 tokens y corromperia el ledger sin que nadie
se entere. Esta prueba existe para que ese fallo no vuelva.
"""

from __future__ import annotations

import pytest

from lymi.ledger import Billing
from lymi.providers.claude_code import (
    ClaudeCodeAuthError,
    _facturacion,
    _leer_usage,
    _modelo,
    _revisar_error,
)

#: Respuesta real del CLI ante una sesion caducada, recortada.
FALLO_AUTH = {
    "is_error": True,
    "subtype": "success",
    "stop_reason": "stop_sequence",
    "terminal_reason": "api_error",
    "total_cost_usd": 0,
    "usage": {"input_tokens": 0, "output_tokens": 0},
    "result": "Failed to authenticate: OAuth session expired and could not be refreshed",
}

EXITO = {
    "is_error": False,
    "subtype": "success",
    "total_cost_usd": 0,
    "usage": {
        "input_tokens": 1200,
        "output_tokens": 340,
        "cache_read_input_tokens": 800,
        "cache_creation_input_tokens": 120,
    },
    "result": "ok",
}


class TestDeteccionDeError:
    def test_is_error_manda_sobre_subtype(self) -> None:
        # subtype dice "success"; is_error dice la verdad.
        with pytest.raises(ClaudeCodeAuthError):
            _revisar_error(FALLO_AUTH)

    def test_el_fallo_de_auth_trae_el_arreglo(self) -> None:
        with pytest.raises(ClaudeCodeAuthError, match="/login"):
            _revisar_error(FALLO_AUTH)

    def test_otros_fallos_son_runtime_error(self) -> None:
        with pytest.raises(RuntimeError) as exc:
            _revisar_error({"is_error": True, "result": "rate limit exceeded"})
        assert not isinstance(exc.value, ClaudeCodeAuthError)

    def test_una_respuesta_sana_no_levanta(self) -> None:
        _revisar_error(EXITO)

    def test_sin_is_error_no_levanta(self) -> None:
        _revisar_error({"result": "ok"})


class TestFacturacion:
    def test_sin_clave_es_suscripcion(self) -> None:
        assert _facturacion({}) is Billing.SUBSCRIPTION

    def test_con_clave_de_api_es_api(self) -> None:
        assert _facturacion({"ANTHROPIC_API_KEY": "sk-ant-loquesea"}) is Billing.API

    def test_con_token_de_autenticacion_es_api(self) -> None:
        assert _facturacion({"ANTHROPIC_AUTH_TOKEN": "tok"}) is Billing.API

    def test_clave_vacia_no_cuenta(self) -> None:
        assert _facturacion({"ANTHROPIC_API_KEY": ""}) is Billing.SUBSCRIPTION

    def test_el_costo_reportado_no_decide(self, monkeypatch) -> None:
        # Regresion de la primera corrida real: con sesion pro y sin clave el CLI
        # reporta total_cost_usd > 0, y antes eso registraba la corrida como api.
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
        assert _facturacion() is Billing.SUBSCRIPTION


class TestModelo:
    def test_usa_model_si_viene(self) -> None:
        assert _modelo({"model": "claude-opus-5"}, "opus") == "claude-opus-5"

    def test_toma_el_id_real_de_model_usage(self) -> None:
        payload = {"model": None, "modelUsage": {"claude-haiku-4-5-20251001": {}}}
        assert _modelo(payload, "haiku") == "claude-haiku-4-5-20251001"

    def test_varios_modelos_quedan_todos(self) -> None:
        payload = {"modelUsage": {"claude-opus-5": {}, "claude-haiku-4-5-20251001": {}}}
        assert _modelo(payload, "opus") == "claude-haiku-4-5-20251001,claude-opus-5"

    def test_sin_datos_usa_el_alias(self) -> None:
        assert _modelo({}, "opus") == "opus"

    def test_model_usage_con_forma_rara_usa_el_alias(self) -> None:
        assert _modelo({"modelUsage": "no es un dict"}, "opus") == "opus"


class TestLecturaDeConsumo:
    def test_lee_los_cuatro_contadores(self) -> None:
        u = _leer_usage(EXITO)
        assert (u.input_tokens, u.output_tokens) == (1200, 340)
        assert (u.cache_read_tokens, u.cache_write_tokens) == (800, 120)

    def test_sin_usage_devuelve_ceros_no_excepcion(self) -> None:
        # Preferimos ceros -- que el reporte marca como sin telemetria -- antes
        # que reventar la corrida o inventar un numero.
        u = _leer_usage({"result": "ok"})
        assert (u.input_tokens, u.output_tokens) == (0, 0)

    def test_usage_con_forma_rara_devuelve_ceros(self) -> None:
        assert _leer_usage({"usage": "no es un dict"}).input_tokens == 0

    def test_campos_nulos_cuentan_como_cero(self) -> None:
        u = _leer_usage({"usage": {"input_tokens": None, "output_tokens": 12}})
        assert (u.input_tokens, u.output_tokens) == (0, 12)
