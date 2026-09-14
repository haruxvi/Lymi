"""Webhook entrante: firma, ventana, repeticion y entradas."""

from __future__ import annotations

import hashlib
import hmac

import pytest

from lymi.flows.schema import Workflow
from lymi.triggers.webhook import (
    LIMITE_CUERPO,
    Deduplicador,
    WebhookError,
    entradas,
    firmar,
    verificar_firma,
    verificar_github,
)

SECRETO = b"s" * 32
CUERPO = b'{"correo": "hola"}'
MARCA = 1_789_000_000


def _flujo() -> Workflow:
    return Workflow.model_validate(
        {"name": "hook", "inputs": {"correo": {}}, "steps": [{"id": "a", "type": "transform", "set": {}}]}
    )


class TestFirma:
    def test_firma_valida(self) -> None:
        cabecera = firmar(SECRETO, CUERPO, MARCA)
        assert verificar_firma(SECRETO, CUERPO, cabecera, ahora=MARCA + 10)

    def test_cuerpo_alterado(self) -> None:
        cabecera = firmar(SECRETO, CUERPO, MARCA)
        with pytest.raises(WebhookError) as exc:
            verificar_firma(SECRETO, b'{"correo": "otro"}', cabecera, ahora=MARCA)
        assert exc.value.estado == 401
        assert exc.value.motivo == "la firma no coincide"

    def test_secreto_distinto(self) -> None:
        cabecera = firmar(b"x" * 32, CUERPO, MARCA)
        with pytest.raises(WebhookError, match="firma invalida"):
            verificar_firma(SECRETO, CUERPO, cabecera, ahora=MARCA)

    def test_marca_vieja_no_sirve(self) -> None:
        cabecera = firmar(SECRETO, CUERPO, MARCA)
        with pytest.raises(WebhookError) as exc:
            verificar_firma(SECRETO, CUERPO, cabecera, ahora=MARCA + 301)
        assert exc.value.motivo == "marca de tiempo fuera de la ventana"

    def test_marca_futura_tampoco(self) -> None:
        cabecera = firmar(SECRETO, CUERPO, MARCA)
        with pytest.raises(WebhookError):
            verificar_firma(SECRETO, CUERPO, cabecera, ahora=MARCA - 301)

    def test_la_marca_va_firmada(self) -> None:
        # Cambiar la marca para meterse en la ventana invalida la firma.
        cabecera = firmar(SECRETO, CUERPO, MARCA).replace(f"t={MARCA}", f"t={MARCA + 1000}")
        with pytest.raises(WebhookError):
            verificar_firma(SECRETO, CUERPO, cabecera, ahora=MARCA + 1000)

    @pytest.mark.parametrize("cabecera", [None, "", "basura", "v1=abc", "t=no-numero,v1=abc"])
    def test_cabeceras_ausentes_o_mal_formadas(self, cabecera: str | None) -> None:
        with pytest.raises(WebhookError) as exc:
            verificar_firma(SECRETO, CUERPO, cabecera, ahora=MARCA)
        assert exc.value.estado == 401

    def test_todo_rechazo_responde_el_mismo_mensaje(self) -> None:
        # Mensajes distintos le dirian a quien prueba que parte acerto.
        casos = [
            (CUERPO, None, MARCA),
            (b"otro", firmar(SECRETO, CUERPO, MARCA), MARCA),
            (CUERPO, firmar(SECRETO, CUERPO, MARCA), MARCA + 999),
        ]
        mensajes = set()
        for cuerpo, cabecera, ahora in casos:
            with pytest.raises(WebhookError) as exc:
                verificar_firma(SECRETO, cuerpo, cabecera, ahora=ahora)
            mensajes.add(str(exc.value))
        assert mensajes == {"firma invalida"}

    def test_rotacion_de_secreto_con_varias_firmas(self) -> None:
        nueva = firmar(SECRETO, CUERPO, MARCA)
        vieja = firmar(b"v" * 32, CUERPO, MARCA).split(",")[1]
        assert verificar_firma(SECRETO, CUERPO, f"{vieja},{nueva}", ahora=MARCA)

    def test_secreto_corto_se_rechaza(self) -> None:
        with pytest.raises(WebhookError) as exc:
            firmar(b"corto", CUERPO, MARCA)
        assert exc.value.estado == 500


class TestGithub:
    def _firma(self, cuerpo: bytes) -> str:
        return "sha256=" + hmac.new(SECRETO, cuerpo, hashlib.sha256).hexdigest()

    def test_valida(self) -> None:
        verificar_github(SECRETO, CUERPO, self._firma(CUERPO))

    def test_invalida(self) -> None:
        with pytest.raises(WebhookError, match="firma invalida"):
            verificar_github(SECRETO, CUERPO, self._firma(b"otro"))

    def test_sin_prefijo(self) -> None:
        with pytest.raises(WebhookError):
            verificar_github(SECRETO, CUERPO, self._firma(CUERPO).removeprefix("sha256="))


class TestDeduplicador:
    def test_rechaza_la_repeticion(self) -> None:
        d = Deduplicador()
        d.registrar("entrega-1")
        with pytest.raises(WebhookError) as exc:
            d.registrar("entrega-1")
        assert exc.value.estado == 409

    def test_olvida_lo_mas_antiguo_al_llenarse(self) -> None:
        d = Deduplicador(capacidad=2)
        for clave in ("a", "b", "c"):
            d.registrar(clave)
        d.registrar("a")  # ya expulsada: se acepta de nuevo


class TestEntradas:
    def test_objeto_con_entradas_declaradas(self) -> None:
        assert entradas(_flujo(), CUERPO) == {"correo": "hola"}

    def test_cuerpo_vacio(self) -> None:
        assert entradas(_flujo(), b"") == {}

    @pytest.mark.parametrize(("cuerpo", "estado"), [(b"no es json", 400), (b"[1, 2]", 400), (b'{"intruso": 1}', 400)])
    def test_cuerpos_invalidos(self, cuerpo: bytes, estado: int) -> None:
        with pytest.raises(WebhookError) as exc:
            entradas(_flujo(), cuerpo)
        assert exc.value.estado == estado

    def test_cuerpo_demasiado_grande(self) -> None:
        with pytest.raises(WebhookError) as exc:
            entradas(_flujo(), b" " * (LIMITE_CUERPO + 1))
        assert exc.value.estado == 413
