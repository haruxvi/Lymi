"""OAuth para MCP remoto: almacen de tokens y retorno del navegador.

Nada de esto toca el almacen real de credenciales ni la red: el almacen se
sustituye por uno en memoria que imita el limite de tamano de Windows, y el
retorno se prueba con sockets de loopback.
"""

from __future__ import annotations

import asyncio

import httpx
import keyring
import pytest
from keyring.backend import KeyringBackend
from keyring.errors import PasswordDeleteError, PasswordSetError
from mcp.shared.auth import OAuthToken

from lymi.flows import oauth


class AlmacenEnMemoria(KeyringBackend):
    """Imita el Credential Manager: rechaza secretos largos."""

    priority = 1  # type: ignore[assignment]
    LIMITE = 1000

    def __init__(self) -> None:
        super().__init__()
        self.datos: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.datos.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        if len(password) > self.LIMITE:
            raise PasswordSetError("secreto demasiado largo")
        self.datos[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        if (service, username) not in self.datos:
            raise PasswordDeleteError("no existe")
        del self.datos[(service, username)]


@pytest.fixture
def memoria():
    anterior = keyring.get_keyring()
    backend = AlmacenEnMemoria()
    keyring.set_keyring(backend)
    yield backend
    keyring.set_keyring(anterior)


def _token(largo: int) -> OAuthToken:
    return OAuthToken(access_token="a" * largo, token_type="Bearer", refresh_token="r" * 300, expires_in=3600)


class TestAlmacen:
    def test_guarda_y_recupera_un_token_largo(self, memoria: AlmacenEnMemoria) -> None:
        # Un JWT real con refresh supera con facilidad el limite por secreto.
        almacen = oauth.AlmacenKeyring("https://mcp.ejemplo.com/mcp")
        token = _token(5000)

        asyncio.run(almacen.set_tokens(token))
        recuperado = asyncio.run(almacen.get_tokens())

        assert recuperado == token
        assert all(len(v) <= AlmacenEnMemoria.LIMITE for v in memoria.datos.values())

    def test_reescribir_mas_corto_borra_los_trozos_sobrantes(self, memoria: AlmacenEnMemoria) -> None:
        almacen = oauth.AlmacenKeyring("https://mcp.ejemplo.com/mcp")
        asyncio.run(almacen.set_tokens(_token(5000)))
        asyncio.run(almacen.set_tokens(_token(10)))

        trozos = [u for (_, u) in memoria.datos if u.endswith(tuple(f"#{i}" for i in range(1, 20)))]
        assert trozos == []
        assert asyncio.run(almacen.get_tokens()) == _token(10)

    def test_sin_sesion_devuelve_none(self, memoria: AlmacenEnMemoria) -> None:
        almacen = oauth.AlmacenKeyring("https://mcp.ejemplo.com/mcp")
        assert asyncio.run(almacen.get_tokens()) is None
        assert almacen.tiene_sesion() is False

    def test_servidores_distintos_no_se_pisan(self, memoria: AlmacenEnMemoria) -> None:
        a = oauth.AlmacenKeyring("https://a.ejemplo.com/mcp")
        b = oauth.AlmacenKeyring("https://b.ejemplo.com/mcp")
        asyncio.run(a.set_tokens(_token(20)))
        assert asyncio.run(b.get_tokens()) is None

    def test_borrar_elimina_todo_rastro(self, memoria: AlmacenEnMemoria) -> None:
        almacen = oauth.AlmacenKeyring("https://mcp.ejemplo.com/mcp")
        asyncio.run(almacen.set_tokens(_token(3000)))
        almacen.borrar()
        assert memoria.datos == {}

    def test_indice_sin_trozos_se_reporta(self, memoria: AlmacenEnMemoria) -> None:
        memoria.datos[(oauth.SERVICIO, "https://x.com/mcp::tokens")] = "3"
        almacen = oauth.AlmacenKeyring("https://x.com/mcp")
        with pytest.raises(oauth.OAuthError, match="incompletas"):
            asyncio.run(almacen.get_tokens())


def _retorno(consulta: str, ruta: str = oauth.RUTA_RETORNO):
    async def _ir():
        servidor = oauth.ServidorRetorno(puerto=0)
        uri = await servidor.iniciar()
        base = uri.removesuffix(oauth.RUTA_RETORNO)
        async with httpx.AsyncClient() as cliente:
            respuesta = await cliente.get(f"{base}{ruta}?{consulta}")
        try:
            resultado = await servidor.esperar(timeout=0.5)
        except (TimeoutError, oauth.OAuthError) as exc:
            resultado = exc
        await servidor.cerrar()
        return respuesta, resultado

    return asyncio.run(_ir())


class TestRetorno:
    def test_recibe_el_codigo(self) -> None:
        respuesta, resultado = _retorno("code=abc123&state=xyz")
        assert respuesta.status_code == 200
        assert resultado.code == "abc123"
        assert resultado.state == "xyz"

    def test_error_del_servidor_de_autorizacion(self) -> None:
        respuesta, resultado = _retorno("error=access_denied&state=xyz")
        assert respuesta.status_code == 400
        assert isinstance(resultado, oauth.OAuthError)

    def test_no_refleja_nada_de_la_url(self) -> None:
        malicioso = "<script>alert(1)</script>"
        respuesta, _ = _retorno(f"error={malicioso}")
        assert "<script>" not in respuesta.text

    def test_ruta_equivocada_no_resuelve(self) -> None:
        respuesta, resultado = _retorno("code=abc", ruta="/otra")
        assert respuesta.status_code == 404
        assert isinstance(resultado, TimeoutError)

    def test_sin_codigo_no_resuelve(self) -> None:
        respuesta, resultado = _retorno("state=xyz")
        assert respuesta.status_code == 400
        assert isinstance(resultado, TimeoutError)


class TestNavegador:
    @pytest.mark.parametrize(
        "url",
        ["file:///C:/Windows/System32/calc.exe", "javascript:alert(1)", "http://evil.com/authorize", "ms-settings:"],
    )
    def test_solo_abre_https(self, url: str) -> None:
        abiertas: list[str] = []
        with pytest.raises(oauth.OAuthError, match="solo se abre https"):
            asyncio.run(oauth.abrir_autorizacion(url, abrir=abiertas.append))
        assert abiertas == []

    def test_abre_https_y_la_muestra(self) -> None:
        abiertas: list[str] = []
        mostradas: list[str] = []
        url = "https://auth.ejemplo.com/authorize?state=x"
        asyncio.run(oauth.abrir_autorizacion(url, abrir=abiertas.append, mostrar=mostradas.append))
        assert abiertas == [url]
        assert mostradas == [url]

    def test_una_corrida_nunca_abre_el_navegador(self) -> None:
        with pytest.raises(oauth.OAuthError, match="lymi integrations login"):
            asyncio.run(oauth.sin_navegador("https://auth.ejemplo.com/authorize"))
        with pytest.raises(oauth.OAuthError, match="lymi integrations login"):
            asyncio.run(oauth.sin_retorno())


class TestMetadatos:
    def test_cliente_publico_con_refresco(self) -> None:
        m = oauth.metadatos_cliente("http://127.0.0.1:33418/callback", ["leer", "buscar"])
        assert [str(u) for u in m.redirect_uris] == ["http://127.0.0.1:33418/callback"]
        assert m.token_endpoint_auth_method == "none"
        assert "refresh_token" in m.grant_types
        assert m.scope == "leer buscar"

    def test_redirect_uri_es_loopback(self) -> None:
        assert oauth.uri_retorno(33418).startswith("http://127.0.0.1:33418/")
