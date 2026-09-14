"""OAuth por codigo de dispositivo (RFC 8628) contra un servidor de autorizacion simulado."""

from __future__ import annotations

import asyncio
from urllib.parse import parse_qs

import httpx
import pytest

from lymi.flows import oauth_dispositivo as od
from lymi.flows.oauth import AlmacenKeyring, OAuthError

MCP = "https://mcp.ejemplo.com/mcp"
AS = "https://auth.ejemplo.com"
CODIGO_SECRETO = "DEVICE-CODE-NO-DEBE-SALIR"


class Servidor:
    """Servidor de autorizacion simulado con respuestas de token en cola."""

    def __init__(self, tokens: list[tuple[int, dict]], *, dispositivo: bool = True, registro: bool = True,
                 verificacion: str = "https://auth.ejemplo.com/device") -> None:
        self.tokens = list(tokens)
        self.dispositivo = dispositivo
        self.registro = registro
        self.verificacion = verificacion
        self.sondeos = 0
        self.formularios: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == "https://mcp.ejemplo.com/.well-known/oauth-protected-resource":
            return httpx.Response(200, json={"authorization_servers": [AS]})
        if url == f"{AS}/.well-known/oauth-authorization-server":
            meta = {"issuer": AS, "token_endpoint": f"{AS}/token"}
            if self.dispositivo:
                meta["device_authorization_endpoint"] = f"{AS}/device_authorization"
            if self.registro:
                meta["registration_endpoint"] = f"{AS}/register"
            return httpx.Response(200, json=meta)
        if url == f"{AS}/register":
            return httpx.Response(201, json={"client_id": "cliente-registrado"})
        if url == f"{AS}/device_authorization":
            return httpx.Response(200, json={
                "device_code": CODIGO_SECRETO, "user_code": "WDJB-MJHT",
                "verification_uri": self.verificacion, "expires_in": 900, "interval": 5,
            })
        if url == f"{AS}/token":
            self.sondeos += 1
            self.formularios.append({k: v[0] for k, v in parse_qs(request.content.decode()).items()})
            estado, cuerpo = self.tokens.pop(0)
            return httpx.Response(estado, json=cuerpo)
        return httpx.Response(404)


def _correr(servidor: Servidor, **opciones):
    esperas: list[float] = []

    async def dormir(segundos: float) -> None:
        esperas.append(segundos)

    async def _ir():
        async with httpx.AsyncClient(transport=httpx.MockTransport(servidor)) as cliente:
            return await od.iniciar_sesion_dispositivo(
                MCP, ["leer"], http_client=cliente, dormir=dormir, listar=False, **opciones
            )

    return asyncio.run(_ir()), esperas


PENDIENTE = (400, {"error": "authorization_pending"})
LENTO = (400, {"error": "slow_down"})
TOKEN = (200, {"access_token": "acceso", "token_type": "Bearer", "refresh_token": "refresco", "expires_in": 3600})


class TestFlujo:
    def test_espera_hasta_autorizar_y_guarda_el_token(self, keyring_memoria) -> None:
        servidor = Servidor([PENDIENTE, LENTO, TOKEN])
        mostrados: list[od.CodigoDispositivo] = []

        _, esperas = _correr(servidor, mostrar=mostrados.append)

        assert servidor.sondeos == 3
        assert esperas == [5, 5, 10]  # slow_down suma 5 segundos
        assert mostrados[0].user_code == "WDJB-MJHT"
        assert servidor.formularios[0]["grant_type"] == od.GRANT_DISPOSITIVO
        assert servidor.formularios[0]["client_id"] == "cliente-registrado"

        almacen = AlmacenKeyring(MCP)
        token = asyncio.run(almacen.get_tokens())
        cliente = asyncio.run(almacen.get_client_info())
        assert token is not None and token.access_token == "acceso"
        assert cliente is not None and cliente.client_id == "cliente-registrado"

    def test_client_id_explicito_no_registra(self, keyring_memoria) -> None:
        servidor = Servidor([TOKEN], registro=False)
        _correr(servidor, client_id="mi-cliente")
        assert servidor.formularios[0]["client_id"] == "mi-cliente"

    def test_sin_registro_ni_client_id(self, keyring_memoria) -> None:
        with pytest.raises(OAuthError, match="--client-id"):
            _correr(Servidor([TOKEN], registro=False))

    def test_rechazo(self, keyring_memoria) -> None:
        with pytest.raises(OAuthError, match="rechazada"):
            _correr(Servidor([PENDIENTE, (400, {"error": "access_denied"})]))

    def test_codigo_vencido(self, keyring_memoria) -> None:
        with pytest.raises(OAuthError, match="vencio"):
            _correr(Servidor([(400, {"error": "expired_token"})]))

    def test_servidor_sin_flujo_de_dispositivo(self, keyring_memoria) -> None:
        with pytest.raises(OAuthError, match="navegador"):
            _correr(Servidor([TOKEN], dispositivo=False))

    def test_url_de_verificacion_no_https(self, keyring_memoria) -> None:
        with pytest.raises(OAuthError, match="https"):
            _correr(Servidor([TOKEN], verificacion="http://evil.com/device"))

    def test_nada_se_guarda_si_falla(self, keyring_memoria) -> None:
        with pytest.raises(OAuthError):
            _correr(Servidor([(400, {"error": "access_denied"})]))
        assert keyring_memoria.datos == {}


class TestSecretoDelCodigo:
    def test_no_aparece_en_repr(self) -> None:
        codigo = od.CodigoDispositivo(CODIGO_SECRETO, "ABCD", "https://x.com", None, 60, 5)
        assert CODIGO_SECRETO not in repr(codigo)

    def test_no_aparece_en_errores(self, keyring_memoria) -> None:
        with pytest.raises(OAuthError) as exc:
            _correr(Servidor([(400, {"error": "invalid_grant"})]))
        assert CODIGO_SECRETO not in str(exc.value)


class TestPlazo:
    def test_respeta_el_tope_de_espera(self) -> None:
        reloj = [0.0]

        async def dormir(segundos: float) -> None:
            reloj[0] += segundos

        async def _ir():
            meta = od.MetadatosDispositivo(AS, f"{AS}/device_authorization", f"{AS}/token")
            codigo = od.CodigoDispositivo("x", "ABCD", f"{AS}/device", None, expires_in=12, interval=5)
            servidor = Servidor([PENDIENTE] * 10)
            async with httpx.AsyncClient(transport=httpx.MockTransport(servidor)) as cliente:
                await od.esperar_token(cliente, meta, "c", codigo, dormir=dormir, reloj=lambda: reloj[0])

        with pytest.raises(OAuthError, match="vencio"):
            asyncio.run(_ir())


class TestHttps:
    @pytest.mark.parametrize("url", ["http://evil.com/x", "ftp://x.com", "no-es-url"])
    def test_rechaza(self, url: str) -> None:
        with pytest.raises(OAuthError):
            od.exigir_https(url, "prueba")

    @pytest.mark.parametrize("url", ["https://x.com/a", "http://127.0.0.1:9000/a", "http://localhost/a"])
    def test_acepta(self, url: str) -> None:
        assert od.exigir_https(url, "prueba") == url
