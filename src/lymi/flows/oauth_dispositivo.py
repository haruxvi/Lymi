"""OAuth por codigo de dispositivo (RFC 8628) para servidores MCP remotos.

Para cuando no hay navegador en la maquina que corre lymi (un servidor, un VPS,
una sesion SSH): lymi muestra un codigo corto y una URL, la persona autoriza desde
cualquier otro dispositivo, y lymi recibe el token esperando en segundo plano.

El SDK de MCP no implementa este flujo, asi que vive aqui. Seguridad:

- El `device_code` es un secreto de portador mientras dura la espera: nunca se
  imprime, no aparece en `repr` ni en mensajes de error.
- Solo se aceptan endpoints y URLs de verificacion https (http solo hacia loopback).
- Se respeta el intervalo del servidor y `slow_down` suma 5 segundos, como exige
  el RFC; lymi nunca martilla el servidor de tokens.
- Los tokens van al almacen de credenciales del sistema, igual que en el login con
  navegador, asi las corridas los usan y refrescan sin cambios.
"""

from __future__ import annotations

import asyncio
import ipaddress
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from lymi.flows.oauth import AlmacenKeyring, OAuthError, almacen_para, proveedor_no_interactivo

GRANT_DISPOSITIVO = "urn:ietf:params:oauth:grant-type:device_code"
INTERVALO_POR_DEFECTO = 5
INCREMENTO_SLOW_DOWN = 5
ESPERA_MAXIMA = 1800
"""Tope propio, aunque el servidor ofrezca un codigo mas largo."""


def _es_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def exigir_https(url: str, que: str) -> str:
    partes = urlparse(url)
    host = (partes.hostname or "").lower()
    if not host:
        raise OAuthError(f"{que}: url sin host")
    if partes.scheme == "https" or (partes.scheme == "http" and _es_loopback(host)):
        return url
    raise OAuthError(f"{que}: solo se admite https (http solo hacia loopback)")


def _origen(url: str) -> str:
    partes = urlparse(url)
    return f"{partes.scheme}://{partes.netloc}"


def _error_oauth(respuesta: httpx.Response) -> str:
    try:
        datos = respuesta.json()
    except ValueError:
        return "respuesta_invalida"
    return str(datos.get("error", "respuesta_invalida")) if isinstance(datos, dict) else "respuesta_invalida"


@dataclass(frozen=True, slots=True)
class MetadatosDispositivo:
    emisor: str
    device_authorization_endpoint: str
    token_endpoint: str
    registration_endpoint: str | None = None


@dataclass(frozen=True, slots=True)
class CodigoDispositivo:
    device_code: str = field(repr=False)
    user_code: str
    verification_uri: str
    verification_uri_complete: str | None
    expires_in: int
    interval: int


async def descubrir(cliente: httpx.AsyncClient, servidor_url: str) -> MetadatosDispositivo:
    """Encuentra los endpoints de dispositivo y de token del servidor de autorizacion."""
    exigir_https(servidor_url, "servidor MCP")

    emisores: list[str] = []
    # MCP publica en el recurso protegido cual es su servidor de autorizacion.
    try:
        respuesta = await cliente.get(f"{_origen(servidor_url)}/.well-known/oauth-protected-resource")
        if respuesta.status_code == 200:
            datos = respuesta.json()
            if isinstance(datos, dict) and isinstance(datos.get("authorization_servers"), list):
                emisores.extend(str(e) for e in datos["authorization_servers"] if isinstance(e, str))
    except (httpx.HTTPError, ValueError):
        pass
    emisores.append(_origen(servidor_url))

    for emisor in dict.fromkeys(emisores):
        exigir_https(emisor, "servidor de autorizacion")
        base = emisor.rstrip("/")
        for ruta in ("/.well-known/oauth-authorization-server", "/.well-known/openid-configuration"):
            try:
                respuesta = await cliente.get(base + ruta)
                datos = respuesta.json() if respuesta.status_code == 200 else None
            except (httpx.HTTPError, ValueError):
                continue
            if not isinstance(datos, dict) or not datos.get("token_endpoint"):
                continue
            dispositivo = datos.get("device_authorization_endpoint")
            if not dispositivo:
                raise OAuthError(
                    f"{emisor} no ofrece el flujo por codigo de dispositivo: usa el login con navegador"
                )
            registro = datos.get("registration_endpoint")
            return MetadatosDispositivo(
                emisor=emisor,
                device_authorization_endpoint=exigir_https(str(dispositivo), "endpoint de dispositivo"),
                token_endpoint=exigir_https(str(datos["token_endpoint"]), "endpoint de token"),
                registration_endpoint=exigir_https(str(registro), "endpoint de registro") if registro else None,
            )
    raise OAuthError("no se encontraron metadatos OAuth para este servidor")


async def registrar_cliente(
    cliente: httpx.AsyncClient, metadatos: MetadatosDispositivo, scopes: list[str]
) -> tuple[str, str | None]:
    """Registro dinamico (RFC 7591). Devuelve (client_id, client_secret o None)."""
    if not metadatos.registration_endpoint:
        raise OAuthError("el servidor no permite registro dinamico de clientes: indica --client-id")
    cuerpo: dict[str, object] = {
        "client_name": "lymi",
        "grant_types": [GRANT_DISPOSITIVO, "refresh_token"],
        "token_endpoint_auth_method": "none",
    }
    if scopes:
        cuerpo["scope"] = " ".join(scopes)
    try:
        respuesta = await cliente.post(metadatos.registration_endpoint, json=cuerpo)
    except httpx.HTTPError as exc:
        raise OAuthError(f"no se pudo registrar el cliente ({type(exc).__name__})") from None
    if respuesta.status_code not in (200, 201):
        raise OAuthError(f"el servidor rechazo el registro del cliente (HTTP {respuesta.status_code})")
    try:
        datos = respuesta.json()
    except ValueError:
        raise OAuthError("respuesta de registro invalida") from None
    client_id = datos.get("client_id") if isinstance(datos, dict) else None
    if not isinstance(client_id, str) or not client_id:
        raise OAuthError("el registro no devolvio client_id")
    secreto = datos.get("client_secret")
    return client_id, secreto if isinstance(secreto, str) and secreto else None


async def pedir_codigo(
    cliente: httpx.AsyncClient, metadatos: MetadatosDispositivo, client_id: str, scopes: list[str]
) -> CodigoDispositivo:
    datos = {"client_id": client_id}
    if scopes:
        datos["scope"] = " ".join(scopes)
    try:
        respuesta = await cliente.post(metadatos.device_authorization_endpoint, data=datos)
    except httpx.HTTPError as exc:
        raise OAuthError(f"no se pudo pedir el codigo de dispositivo ({type(exc).__name__})") from None
    if respuesta.status_code != 200:
        raise OAuthError(
            f"el servidor rechazo la solicitud de codigo: {_error_oauth(respuesta)} (HTTP {respuesta.status_code})"
        )
    try:
        cuerpo = respuesta.json()
    except ValueError:
        raise OAuthError("respuesta de codigo de dispositivo invalida") from None
    if not isinstance(cuerpo, dict):
        raise OAuthError("respuesta de codigo de dispositivo invalida")
    for campo in ("device_code", "user_code", "verification_uri"):
        if not isinstance(cuerpo.get(campo), str) or not cuerpo[campo]:
            raise OAuthError(f"la respuesta no trae {campo}")

    completa = cuerpo.get("verification_uri_complete")
    try:
        expira = int(cuerpo.get("expires_in") or 600)
        intervalo = int(cuerpo.get("interval") or INTERVALO_POR_DEFECTO)
    except (TypeError, ValueError):
        raise OAuthError("la respuesta trae expires_in o interval invalidos") from None
    return CodigoDispositivo(
        device_code=cuerpo["device_code"],
        user_code=cuerpo["user_code"],
        verification_uri=exigir_https(cuerpo["verification_uri"], "url de verificacion"),
        verification_uri_complete=exigir_https(completa, "url de verificacion") if isinstance(completa, str) and completa else None,
        expires_in=max(expira, 1),
        interval=max(intervalo, 1),
    )


async def esperar_token(
    cliente: httpx.AsyncClient,
    metadatos: MetadatosDispositivo,
    client_id: str,
    codigo: CodigoDispositivo,
    *,
    client_secret: str | None = None,
    dormir: Callable[[float], object] = asyncio.sleep,
    reloj: Callable[[], float] = time.monotonic,
) -> OAuthToken:
    """Sondea el endpoint de token hasta que la persona autoriza, rechaza o vence."""
    limite = reloj() + min(codigo.expires_in, ESPERA_MAXIMA)
    intervalo = codigo.interval
    datos = {"grant_type": GRANT_DISPOSITIVO, "device_code": codigo.device_code, "client_id": client_id}
    if client_secret:
        datos["client_secret"] = client_secret

    while True:
        await dormir(intervalo)
        if reloj() > limite:
            raise OAuthError("el codigo vencio antes de que autorizaras; vuelve a intentarlo")
        try:
            respuesta = await cliente.post(metadatos.token_endpoint, data=datos)
        except httpx.HTTPError:
            continue  # red intermitente: se reintenta dentro del mismo plazo
        if respuesta.status_code == 200:
            try:
                return OAuthToken.model_validate(respuesta.json())
            except ValueError:
                raise OAuthError("el servidor devolvio un token invalido") from None
        error = _error_oauth(respuesta)
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            intervalo += INCREMENTO_SLOW_DOWN
            continue
        if error == "access_denied":
            raise OAuthError("la autorizacion fue rechazada")
        if error == "expired_token":
            raise OAuthError("el codigo vencio antes de que autorizaras; vuelve a intentarlo")
        raise OAuthError(f"el servidor de tokens respondio {error} (HTTP {respuesta.status_code})")


async def listar_herramientas(servidor_url: str, scopes: list[str], almacen: AlmacenKeyring) -> list[str]:
    """Conecta con los tokens guardados y lista las herramientas del servidor."""
    from mcp import ClientSession
    from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

    proveedor = proveedor_no_interactivo(servidor_url, scopes, almacen)
    async with (
        create_mcp_http_client(auth=proveedor) as cliente,
        streamable_http_client(servidor_url, http_client=cliente) as (lectura, escritura),
        ClientSession(lectura, escritura) as sesion,
    ):
        await sesion.initialize()
        resultado = await sesion.list_tools()
    return sorted(h.name for h in resultado.tools)


async def iniciar_sesion_dispositivo(
    servidor_url: str,
    scopes: list[str],
    *,
    client_id: str | None = None,
    almacen: AlmacenKeyring | None = None,
    mostrar: Callable[[CodigoDispositivo], None] | None = None,
    http_client: httpx.AsyncClient | None = None,
    dormir: Callable[[float], object] = asyncio.sleep,
    listar: bool = True,
) -> list[str]:
    """Autoriza a lymi por codigo de dispositivo. Devuelve las herramientas del servidor."""
    almacen = almacen or almacen_para(servidor_url)
    cliente = http_client or httpx.AsyncClient(timeout=30.0, follow_redirects=False)
    try:
        metadatos = await descubrir(cliente, servidor_url)
        secreto: str | None = None
        if client_id is None:
            client_id, secreto = await registrar_cliente(cliente, metadatos, scopes)
        codigo = await pedir_codigo(cliente, metadatos, client_id, scopes)
        if mostrar is not None:
            mostrar(codigo)
        token = await esperar_token(cliente, metadatos, client_id, codigo, client_secret=secreto, dormir=dormir)
    finally:
        if http_client is None:
            await cliente.aclose()

    await almacen.set_client_info(
        OAuthClientInformationFull(
            client_id=client_id,
            client_secret=secreto,
            token_endpoint_auth_method="client_secret_post" if secreto else "none",
        )
    )
    await almacen.set_tokens(token)
    return await listar_herramientas(servidor_url, scopes, almacen) if listar else []
