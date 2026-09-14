"""Pruebas del cliente del tier local.

La propiedad que importa: un modelo lento pero vivo tiene que llegar hasta el
final, y uno mudo tiene que fallar con una frase, no con una traza.
"""

from __future__ import annotations

import json

import httpx
import pytest

from lymi.providers.base import Message
from lymi.providers.local import LocalTimeoutError, OllamaClient


def _cliente(handler) -> OllamaClient:
    transporte = httpx.MockTransport(handler)
    return OllamaClient(client=httpx.Client(transport=transporte), allow_remote=False)


def _jsonl(*trozos: dict) -> bytes:
    return b"".join(json.dumps(t).encode() + b"\n" for t in trozos)


class TestStreaming:
    def test_junta_los_trozos_y_las_cuentas(self) -> None:
        cuerpo = _jsonl(
            {"message": {"content": "def suma"}, "done": False},
            {"message": {"content": "(a, b):"}, "done": False},
            {
                "message": {"content": " return a + b"},
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": 25,
                "eval_count": 12,
            },
        )
        c = _cliente(lambda _req: httpx.Response(200, content=cuerpo))

        r = c.complete([Message("user", "suma")])

        assert r.text == "def suma(a, b): return a + b"
        assert r.usage.input_tokens == 25
        assert r.usage.output_tokens == 12
        assert r.stop_reason == "stop"
        assert r.tier == "local"

    def test_pide_streaming(self) -> None:
        # Sin streaming, el timeout mide la generacion completa y corta
        # respuestas sanas de un modelo lento.
        visto: dict = {}

        def _handler(req: httpx.Request) -> httpx.Response:
            visto.update(json.loads(req.content))
            return httpx.Response(200, content=_jsonl({"message": {"content": "ok"}, "done": True}))

        _cliente(_handler).complete([Message("user", "hola")])
        assert visto["stream"] is True

    def test_lineas_vacias_no_molestan(self) -> None:
        cuerpo = b"\n" + _jsonl({"message": {"content": "ok"}, "done": True}) + b"\n"
        r = _cliente(lambda _req: httpx.Response(200, content=cuerpo)).complete([Message("user", "x")])
        assert r.text == "ok"

    def test_error_del_servidor_en_el_stream(self) -> None:
        cuerpo = _jsonl({"error": "model not found"})
        c = _cliente(lambda _req: httpx.Response(200, content=cuerpo))
        with pytest.raises(RuntimeError, match="model not found"):
            c.complete([Message("user", "x")])


class TestSilencio:
    def test_silencio_es_un_error_explicado(self) -> None:
        def _mudo(_req: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timed out")

        c = _cliente(_mudo)
        with pytest.raises(LocalTimeoutError, match="ollama ps"):
            c.complete([Message("user", "x")])

    def test_el_error_dice_cuanto_alcanzo_a_llegar(self) -> None:
        def _corta(_req: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timed out")

        c = _cliente(_corta)
        with pytest.raises(LocalTimeoutError, match="0 caracteres"):
            c.complete([Message("user", "x")])
