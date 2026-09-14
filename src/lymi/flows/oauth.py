"""OAuth para servidores MCP remotos.

Tres decisiones de seguridad:

1. **Los tokens van al almacen de credenciales del sistema** (Credential Manager
   en Windows, Keychain en macOS, Secret Service en Linux) via `keyring`. Nunca a
   un archivo del proyecto, nunca al ledger, nunca a un log.
2. **El retorno del navegador lo recibe un servidor efimero en 127.0.0.1** que no
   refleja nada de la URL en la pagina que devuelve.
3. **Solo se abren URLs de autorizacion https.** Un servidor MCP malicioso podria
   devolver una URL `file:` o de un esquema propio para que el navegador abra
   otra cosa.

Una corrida de workflow nunca abre un navegador: si falta la sesion, falla con
la instruccion para iniciarla con `lymi integrations login`.
"""

from __future__ import annotations

import asyncio
import os
import webbrowser
from collections.abc import Callable
from urllib.parse import parse_qs, urlparse

import keyring
from keyring.errors import KeyringError, PasswordDeleteError
from mcp.client.auth import OAuthClientProvider
from mcp.shared.auth import (
    AuthorizationCodeResult,
    OAuthClientInformationFull,
    OAuthClientMetadata,
    OAuthToken,
)

SERVICIO = "lymi-mcp"

PUERTO_RETORNO = int(os.getenv("LYMI_OAUTH_PORT", "33418"))
"""Puerto fijo a proposito. Un cliente registrado dinamicamente queda atado a su
redirect_uri: con un puerto aleatorio, el registro de ayer no serviria hoy."""

RUTA_RETORNO = "/callback"
TIEMPO_LOGIN = 300.0

TROZO = 900
"""Caracteres por trozo al guardar un secreto. El Credential Manager de Windows
limita cada secreto a 2560 bytes y los guarda en UTF-16: poco mas de 1200
caracteres. Un token de acceso con su token de refresco lo supera con facilidad."""

_INSTRUCCION = "corre `lymi integrations login <workflow> <integracion>`"


class OAuthError(RuntimeError):
    """Fallo de autorizacion. El mensaje dice como arreglarlo."""


def uri_retorno(puerto: int = PUERTO_RETORNO) -> str:
    return f"http://127.0.0.1:{puerto}{RUTA_RETORNO}"


# ---------------------------------------------------------------- almacen


def _leer(servicio: str, clave: str) -> str | None:
    try:
        return keyring.get_password(servicio, clave)
    except KeyringError as exc:
        raise OAuthError(f"no se pudo leer el almacen de credenciales ({type(exc).__name__})") from None


def _escribir(servicio: str, clave: str, valor: str) -> None:
    try:
        keyring.set_password(servicio, clave, valor)
    except KeyringError as exc:
        raise OAuthError(f"no se pudo escribir en el almacen de credenciales ({type(exc).__name__})") from None


def _borrar(servicio: str, clave: str) -> None:
    try:
        keyring.delete_password(servicio, clave)
    except PasswordDeleteError:
        pass
    except KeyringError as exc:
        raise OAuthError(f"no se pudo borrar del almacen de credenciales ({type(exc).__name__})") from None


def _cantidad(servicio: str, clave: str) -> int:
    crudo = _leer(servicio, clave)
    try:
        return int(crudo) if crudo is not None else 0
    except ValueError:
        return 0


def guardar_troceado(servicio: str, clave: str, valor: str) -> None:
    """Guarda un secreto largo en trozos bajo `clave#0`, `clave#1`..."""
    trozos = [valor[i : i + TROZO] for i in range(0, len(valor), TROZO)] or [""]
    anteriores = _cantidad(servicio, clave)
    # Trozos primero, indice al final: una escritura interrumpida no deja un
    # indice apuntando a trozos que no existen.
    for i, trozo in enumerate(trozos):
        _escribir(servicio, f"{clave}#{i}", trozo)
    _escribir(servicio, clave, str(len(trozos)))
    for i in range(len(trozos), anteriores):
        _borrar(servicio, f"{clave}#{i}")


def cargar_troceado(servicio: str, clave: str) -> str | None:
    crudo = _leer(servicio, clave)
    if crudo is None:
        return None
    try:
        cantidad = int(crudo)
    except ValueError:
        raise OAuthError(f"credenciales corruptas: {_INSTRUCCION}") from None
    partes: list[str] = []
    for i in range(cantidad):
        trozo = _leer(servicio, f"{clave}#{i}")
        if trozo is None:
            raise OAuthError(f"credenciales incompletas: {_INSTRUCCION}")
        partes.append(trozo)
    return "".join(partes)


def borrar_troceado(servicio: str, clave: str) -> None:
    for i in range(_cantidad(servicio, clave)):
        _borrar(servicio, f"{clave}#{i}")
    _borrar(servicio, clave)


class AlmacenKeyring:
    """`TokenStorage` del SDK de MCP sobre el almacen de credenciales del sistema."""

    def __init__(self, servidor_url: str, *, servicio: str = SERVICIO) -> None:
        self._servicio = servicio
        self._tokens = f"{servidor_url}::tokens"
        self._cliente = f"{servidor_url}::cliente"

    async def get_tokens(self) -> OAuthToken | None:
        crudo = await asyncio.to_thread(cargar_troceado, self._servicio, self._tokens)
        return None if crudo is None else OAuthToken.model_validate_json(crudo)

    async def set_tokens(self, tokens: OAuthToken) -> None:
        await asyncio.to_thread(guardar_troceado, self._servicio, self._tokens, tokens.model_dump_json())

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        crudo = await asyncio.to_thread(cargar_troceado, self._servicio, self._cliente)
        return None if crudo is None else OAuthClientInformationFull.model_validate_json(crudo)

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        await asyncio.to_thread(
            guardar_troceado, self._servicio, self._cliente, client_info.model_dump_json()
        )

    def tiene_sesion(self) -> bool:
        return _leer(self._servicio, self._tokens) is not None

    def borrar(self) -> None:
        borrar_troceado(self._servicio, self._tokens)
        borrar_troceado(self._servicio, self._cliente)


def almacen_para(servidor_url: str) -> AlmacenKeyring:
    return AlmacenKeyring(servidor_url)


# ---------------------------------------------------------------- retorno del navegador


class ServidorRetorno:
    """Servidor efimero en 127.0.0.1 que recibe el codigo de autorizacion."""

    def __init__(self, *, puerto: int = PUERTO_RETORNO) -> None:
        self._puerto = puerto
        self._servidor: asyncio.Server | None = None
        self._futuro: asyncio.Future[AuthorizationCodeResult] | None = None
        self.redirect_uri = ""

    async def iniciar(self) -> str:
        self._futuro = asyncio.get_running_loop().create_future()
        try:
            self._servidor = await asyncio.start_server(self._atender, "127.0.0.1", self._puerto)
        except OSError:
            raise OAuthError(
                f"el puerto {self._puerto} esta ocupado: elige otro con --puerto o LYMI_OAUTH_PORT"
            ) from None
        puerto = self._servidor.sockets[0].getsockname()[1]
        self.redirect_uri = uri_retorno(puerto)
        return self.redirect_uri

    @staticmethod
    async def _responder(escritor: asyncio.StreamWriter, estado: int, texto: str) -> None:
        # `texto` es siempre una cadena fija de este modulo: nada de la URL se
        # refleja en la pagina, asi que no hay XSS posible en el retorno.
        cuerpo = (
            "<!doctype html><meta charset=utf-8><title>lymi</title>"
            f"<p style='font:16px system-ui;margin:48px'>{texto}</p>"
        ).encode()
        razones = {200: "OK", 400: "Bad Request", 404: "Not Found", 405: "Method Not Allowed"}
        cabecera = (
            f"HTTP/1.1 {estado} {razones.get(estado, 'OK')}\r\n"
            "Content-Type: text/html; charset=utf-8\r\n"
            f"Content-Length: {len(cuerpo)}\r\n"
            "Cache-Control: no-store\r\n"
            "Connection: close\r\n\r\n"
        ).encode()
        escritor.write(cabecera + cuerpo)
        await escritor.drain()

    async def _atender(self, lector: asyncio.StreamReader, escritor: asyncio.StreamWriter) -> None:
        try:
            primera = await asyncio.wait_for(lector.readline(), 10)
            while (linea := await asyncio.wait_for(lector.readline(), 10)) not in (b"\r\n", b"\n", b""):
                del linea
            partes = primera.decode("latin-1").split()
            if len(partes) < 2 or partes[0] != "GET":
                await self._responder(escritor, 405, "Metodo no admitido.")
                return
            destino = urlparse(partes[1])
            if destino.path != RUTA_RETORNO:
                await self._responder(escritor, 404, "No encontrado.")
                return

            consulta = parse_qs(destino.query)
            futuro = self._futuro
            if "error" in consulta:
                if futuro is not None and not futuro.done():
                    futuro.set_exception(OAuthError(f"la autorizacion fue rechazada: {consulta['error'][0]}"))
                await self._responder(escritor, 400, "La autorizacion fue rechazada. Puedes cerrar esta pestana.")
                return
            if "code" not in consulta:
                await self._responder(escritor, 400, "Falta el codigo de autorizacion.")
                return

            if futuro is not None and not futuro.done():
                futuro.set_result(
                    AuthorizationCodeResult(
                        code=consulta["code"][0],
                        state=(consulta.get("state") or [None])[0],
                        iss=(consulta.get("iss") or [None])[0],
                    )
                )
            await self._responder(escritor, 200, "Listo: lymi recibio la autorizacion. Puedes cerrar esta pestana.")
        except (TimeoutError, ConnectionError, UnicodeDecodeError):
            pass
        finally:
            escritor.close()

    async def esperar(self, timeout: float = TIEMPO_LOGIN) -> AuthorizationCodeResult:
        if self._futuro is None:
            raise OAuthError("el servidor de retorno no esta iniciado")
        return await asyncio.wait_for(asyncio.shield(self._futuro), timeout)

    async def cerrar(self) -> None:
        if self._servidor is not None:
            self._servidor.close()
            await self._servidor.wait_closed()
        if self._futuro is not None and self._futuro.done() and not self._futuro.cancelled():
            self._futuro.exception()  # evita el aviso de excepcion nunca recuperada


# ---------------------------------------------------------------- proveedores


def metadatos_cliente(redirect_uri: str, scopes: list[str]) -> OAuthClientMetadata:
    return OAuthClientMetadata(
        client_name="lymi",
        redirect_uris=[redirect_uri],
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        scope=" ".join(scopes) if scopes else None,
        # Cliente publico con PKCE: no hay secreto de cliente que proteger.
        token_endpoint_auth_method="none",
    )


async def abrir_autorizacion(
    url: str,
    *,
    abrir: Callable[[str], object] = webbrowser.open,
    mostrar: Callable[[str], None] | None = None,
) -> None:
    """Abre la pagina de autorizacion. Solo https."""
    esquema = urlparse(url).scheme
    if esquema != "https":
        raise OAuthError(f"url de autorizacion con esquema {esquema!r}: solo se abre https")
    if mostrar is not None:
        mostrar(url)
    await asyncio.to_thread(abrir, url)


async def sin_navegador(_url: str) -> None:
    raise OAuthError(f"no hay sesion iniciada con este servidor: {_INSTRUCCION}")


async def sin_retorno() -> AuthorizationCodeResult:
    raise OAuthError(f"no hay sesion iniciada con este servidor: {_INSTRUCCION}")


def proveedor_no_interactivo(
    servidor_url: str,
    scopes: list[str],
    almacen: AlmacenKeyring | None = None,
    *,
    puerto: int = PUERTO_RETORNO,
) -> OAuthClientProvider:
    """Proveedor para corridas: usa y refresca tokens guardados, jamas abre un navegador."""
    return OAuthClientProvider(
        server_url=servidor_url,
        client_metadata=metadatos_cliente(uri_retorno(puerto), scopes),
        storage=almacen or almacen_para(servidor_url),
        redirect_handler=sin_navegador,
        callback_handler=sin_retorno,
    )


async def iniciar_sesion(
    servidor_url: str,
    scopes: list[str],
    *,
    almacen: AlmacenKeyring | None = None,
    abrir: Callable[[str], object] = webbrowser.open,
    mostrar: Callable[[str], None] | None = None,
    puerto: int = PUERTO_RETORNO,
    timeout: float = TIEMPO_LOGIN,
) -> list[str]:
    """Autoriza a lymi ante el servidor y devuelve las herramientas que ofrece."""
    from mcp import ClientSession
    from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

    retorno = ServidorRetorno(puerto=puerto)
    uri = await retorno.iniciar()
    almacen = almacen or almacen_para(servidor_url)

    async def redirigir(url: str) -> None:
        await abrir_autorizacion(url, abrir=abrir, mostrar=mostrar)

    async def recibir() -> AuthorizationCodeResult:
        try:
            return await retorno.esperar(timeout)
        except TimeoutError:
            raise OAuthError(f"no llego la autorizacion en {timeout:g} s") from None

    proveedor = OAuthClientProvider(
        server_url=servidor_url,
        client_metadata=metadatos_cliente(uri, scopes),
        storage=almacen,
        redirect_handler=redirigir,
        callback_handler=recibir,
    )
    try:
        async with (
            create_mcp_http_client(auth=proveedor) as cliente,
            streamable_http_client(servidor_url, http_client=cliente) as (lectura, escritura),
            ClientSession(lectura, escritura) as sesion,
        ):
            await sesion.initialize()
            resultado = await sesion.list_tools()
    finally:
        await retorno.cerrar()
    return sorted(herramienta.name for herramienta in resultado.tools)
