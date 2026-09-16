"""Peticiones web con guardia de red, robots.txt y registro de cada salto.

La defensa contra SSRF no es "rechazar localhost en la URL": un nombre publico
puede resolver a `10.0.0.5`, un DNS puede responder distinto la segunda vez, y
una redireccion puede apuntar a `169.254.169.254`. Por eso, en cada salto:

1. se resuelve el nombre y se exige que TODAS las direcciones sean publicas;
2. la conexion va a la IP ya comprobada (el nombre viaja en `Host` y en SNI, asi
   el certificado TLS se sigue validando contra el nombre);
3. las redirecciones se siguen a mano, repitiendo 1 y 2.
"""

from __future__ import annotations

import asyncio
import html
import ipaddress
import re
import socket
import time
from collections import deque
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import httpx

from lymi.privacidad import EgressBloqueado, Redactor, sanear
from lymi.web.markdown import Documento, html_a_markdown

AGENTE = "lymi/0.0.1 (agente local; respeta robots.txt)"
AGENTE_ROBOTS = "lymi"
MAX_BYTES = 2_000_000
MAX_CARACTERES = 60_000
LIMITE_URLS = 1000
TIPOS_TEXTO = frozenset({
    "text/html", "application/xhtml+xml", "text/plain", "text/markdown", "application/json",
    "application/xml", "text/xml",
})
_BINARIOS = re.compile(
    r"\.(?:pdf|zip|gz|tar|7z|rar|png|jpe?g|gif|webp|svg|ico|mp[34]|webm|avi|mov|exe|msi|dmg|woff2?|ttf|css|js)$",
    re.IGNORECASE,
)
_META_CHARSET = re.compile(rb"<meta[^>]+charset=[\"']?([A-Za-z0-9_-]+)", re.IGNORECASE)
_INYECCION = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"ignore\s+(?:all\s+|any\s+)?(?:the\s+)?(?:previous|prior|above|earlier)\s+(?:instructions|prompts?|messages?)",
        r"disregard\s+(?:all\s+|the\s+)?(?:previous|prior|above)",
        r"ignora\s+(?:todas\s+)?(?:las\s+)?instrucciones\s+(?:anteriores|previas)",
        r"olvida\s+(?:todas\s+)?(?:las\s+)?instrucciones",
        r"you\s+are\s+now\s+(?:a|an|in)\b",
        r"(?:new|updated)\s+system\s+prompt",
        r"<\s*/?\s*(?:system|assistant)\s*>",
        r"\bdo\s+not\s+tell\s+the\s+user\b",
        r"no\s+le\s+digas\s+al\s+usuario",
    )
)

Resolver = Callable[[str], list[str]]


class WebError(RuntimeError):
    """No se pudo leer. `reintentable` dice si otro intento podria cambiar el resultado."""

    def __init__(self, mensaje: str, *, reintentable: bool = False) -> None:
        super().__init__(mensaje)
        self.reintentable = reintentable


class DestinoBloqueado(WebError):
    """lymi se nego a hacer la peticion: red interna, dato sensible o robots.txt."""


def resolver_sistema(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(str(info[4][0]).split("%")[0] for info in infos))


def es_publica(ip_texto: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_texto.split("%")[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def revisar_saliente(texto: str, que: str) -> None:
    """Una URL o una consulta tambien es egress: si lleva un secreto, no sale."""
    redactor = Redactor()
    try:
        redactor.redactar(unquote(texto))
    except EgressBloqueado as exc:
        raise DestinoBloqueado(f"{que}: {exc}") from None
    if redactor.total:
        categorias = ", ".join(sorted(redactor.conteo)).lower().replace("_", " ")
        raise DestinoBloqueado(f"{que} lleva {categorias}: no sale de la maquina")


def senales_inyeccion(texto: str) -> list[str]:
    """Fragmentos que parecen ordenes dirigidas a un modelo."""
    hallazgos = []
    for patron in _INYECCION:
        m = patron.search(texto)
        if m:
            hallazgos.append(texto[max(0, m.start() - 20) : m.end() + 20].replace("\n", " "))
    return hallazgos


@dataclass(slots=True)
class EventoRed:
    tipo: str
    """web | buscar"""
    host: str
    payload: str
    """Lo que salio: la URL o la consulta."""
    latencia_ms: int
    ok: bool
    error: str | None = None


@dataclass(slots=True)
class Pagina:
    url: str
    estado: int
    tipo: str
    texto: str
    truncado: bool = False
    avisos: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Extraccion:
    url: str
    titulo: str
    descripcion: str
    markdown: str
    enlaces: list[str]
    truncado: bool
    avisos: list[str]

    def como_dict(self) -> dict:
        datos = asdict(self)
        datos["enlaces"] = self.enlaces[:100]
        return datos


@dataclass(slots=True)
class Mapa:
    urls: list[str]
    visitadas: int
    avisos: list[str]

    def como_dict(self) -> dict:
        return asdict(self)


def _normalizar(url: str) -> str:
    return urlunsplit(urlsplit(url)._replace(fragment=""))


class Web:
    """Cliente web de lymi. Acumula eventos: quien lo usa los lleva al ledger."""

    def __init__(
        self,
        cliente: httpx.AsyncClient,
        *,
        resolver: Resolver | None = None,
        respetar_robots: bool = True,
        max_bytes: int = MAX_BYTES,
        max_redirecciones: int = 5,
        timeout: float = 20.0,
    ) -> None:
        self._cliente = cliente
        self._resolver = resolver or resolver_sistema
        self.respetar_robots = respetar_robots
        self.max_bytes = max_bytes
        self.max_redirecciones = max_redirecciones
        self.timeout = timeout
        self.eventos: list[EventoRed] = []
        self._robots: dict[str, RobotFileParser] = {}

    def vaciar_eventos(self) -> list[EventoRed]:
        eventos, self.eventos = self.eventos, []
        return eventos

    # ------------------------------------------------------------ red

    async def _destino(self, url: str) -> tuple[object, str]:
        partes = urlsplit(url)
        if partes.scheme not in {"http", "https"}:
            raise DestinoBloqueado(f"esquema {partes.scheme or '(vacio)'!r} no permitido: solo http y https")
        if partes.username or partes.password:
            raise DestinoBloqueado("la URL lleva usuario o contrasena: no se envia")
        host = partes.hostname
        if not host:
            raise DestinoBloqueado("la URL no tiene host")
        try:
            _ = partes.port
        except ValueError:
            raise DestinoBloqueado("puerto invalido") from None
        try:
            # Una IP literal se juzga tal cual: no hay nombre que resolver, y pasar
            # por el DNS solo abriria la puerta a que el sistema la reescriba.
            ipaddress.ip_address(host)
        except ValueError:
            try:
                ips = await asyncio.to_thread(self._resolver, host)
            except OSError:
                raise WebError(f"no se pudo resolver {host}", reintentable=True) from None
        else:
            ips = [host]
        if not ips:
            raise WebError(f"{host} no tiene direcciones", reintentable=True)
        internas = [ip for ip in ips if not es_publica(ip)]
        if internas:
            raise DestinoBloqueado(
                f"{host} resuelve a una direccion no publica ({internas[0]}): lymi no lee la red interna"
            )
        return partes, ips[0]

    async def _peticion(self, partes, ip: str, url: str, tipos: frozenset[str] | None):
        host = partes.hostname
        red = f"[{ip}]" if ":" in ip else ip
        cabecera_host = host
        if partes.port:
            red += f":{partes.port}"
            cabecera_host += f":{partes.port}"
        fijada = urlunsplit((partes.scheme, red, partes.path or "/", partes.query, ""))
        extensiones = {"sni_hostname": host} if partes.scheme == "https" else {}
        cabeceras = {
            "Host": cabecera_host,
            "User-Agent": AGENTE,
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.1",
        }
        async with self._cliente.stream(
            "GET", fijada, headers=cabeceras, extensions=extensiones, timeout=self.timeout, follow_redirects=False
        ) as resp:
            if 300 <= resp.status_code < 400:
                destino = resp.headers.get("location")
                if not destino:
                    raise WebError(f"{host} redirige sin destino")
                return resp.status_code, destino, None
            tipo = resp.headers.get("content-type", "").split(";")[0].strip().lower()
            if resp.status_code < 400 and tipos is not None and tipo and tipo not in tipos:
                raise WebError(f"{host} devolvio {tipo}: lymi solo lee texto")
            datos = bytearray()
            truncado = False
            async for trozo in resp.aiter_bytes():
                datos.extend(trozo)
                if len(datos) > self.max_bytes:
                    del datos[self.max_bytes :]
                    truncado = True
                    break
            meta = _META_CHARSET.search(bytes(datos[:4096]))
            codificacion = resp.charset_encoding or (meta.group(1).decode() if meta else None) or "utf-8"
            try:
                texto = bytes(datos).decode(codificacion, errors="replace")
            except LookupError:
                texto = bytes(datos).decode("utf-8", errors="replace")
            return resp.status_code, None, Pagina(url, resp.status_code, tipo, texto, truncado)

    async def obtener(
        self,
        url: str,
        *,
        tipos: frozenset[str] | None = TIPOS_TEXTO,
        aceptar_error: bool = False,
        _robots: bool = True,
    ) -> Pagina:
        revisar_saliente(url, "la URL")
        actual = url
        for _ in range(self.max_redirecciones + 1):
            partes, ip = await self._destino(actual)
            if _robots and self.respetar_robots and not await self._permite_robots(partes, actual):
                raise DestinoBloqueado(f"robots.txt de {partes.hostname} no permite leer {partes.path or '/'}")
            inicio = time.perf_counter()
            try:
                estado, redireccion, pagina = await self._peticion(partes, ip, actual, tipos)
            except WebError as exc:
                self._anotar(partes.hostname, actual, inicio, False, str(exc))
                raise
            except httpx.HTTPError as exc:
                self._anotar(partes.hostname, actual, inicio, False, type(exc).__name__)
                raise WebError(f"{partes.hostname}: {type(exc).__name__}", reintentable=True) from None
            self._anotar(partes.hostname, actual, inicio, estado < 400, None if estado < 400 else f"HTTP {estado}")

            if redireccion is not None:
                actual = _normalizar(urljoin(actual, redireccion))
                revisar_saliente(actual, "la redireccion")
                continue
            if estado >= 400 and not aceptar_error:
                raise WebError(f"{partes.hostname}: HTTP {estado}", reintentable=estado >= 500 or estado == 429)
            if partes.scheme == "http":
                pagina.avisos.append(f"{partes.hostname} se leyo sin cifrar (http)")
            return pagina
        raise WebError(f"mas de {self.max_redirecciones} redirecciones")

    def _anotar(self, host: str, url: str, inicio: float, ok: bool, error: str | None) -> None:
        latencia = int((time.perf_counter() - inicio) * 1000)
        self.eventos.append(EventoRed("web", host, url, latencia, ok, error))

    async def _permite_robots(self, partes, url: str) -> bool:
        origen = f"{partes.scheme}://{partes.netloc}"
        parser = self._robots.get(origen)
        if parser is None:
            parser = RobotFileParser()
            try:
                pagina = await self.obtener(f"{origen}/robots.txt", tipos=None, aceptar_error=True, _robots=False)
            except WebError:
                parser.allow_all = True
            else:
                if pagina.estado in {401, 403}:
                    parser.disallow_all = True
                elif pagina.estado >= 400:
                    parser.allow_all = True
                else:
                    parser.parse(pagina.texto.splitlines())
            self._robots[origen] = parser
        return parser.can_fetch(AGENTE_ROBOTS, url)

    # ------------------------------------------------------------ operaciones

    async def extraer(self, url: str, *, max_caracteres: int = MAX_CARACTERES) -> Extraccion:
        """Una pagina como markdown limpio, con titulo, descripcion y enlaces."""
        pagina = await self.obtener(url)
        es_html = pagina.tipo in {"text/html", "application/xhtml+xml"} or (
            not pagina.tipo and "<html" in pagina.texto[:1000].lower()
        )
        documento = html_a_markdown(pagina.texto, pagina.url) if es_html else Documento("", "", pagina.texto)
        texto = sanear(documento.markdown).texto
        avisos = list(pagina.avisos)
        truncado = pagina.truncado
        if len(texto) > max_caracteres:
            texto, truncado = texto[:max_caracteres], True
        if truncado:
            avisos.append("contenido truncado")
        senales = senales_inyeccion(texto)
        if senales:
            avisos.append(f"la pagina intenta dar instrucciones a un modelo: {senales[0]!r}")
        return Extraccion(
            url=pagina.url,
            titulo=sanear(documento.titulo).texto,
            descripcion=sanear(documento.descripcion).texto,
            markdown=texto,
            enlaces=documento.enlaces,
            truncado=truncado,
            avisos=avisos,
        )

    async def mapear(self, url: str, *, max_paginas: int = 20, profundidad: int = 1) -> Mapa:
        """URLs de un sitio: su sitemap y lo enlazado, sin salir del mismo host."""
        inicio = urlsplit(url)
        host = (inicio.hostname or "").lower()
        encontradas: dict[str, None] = {}
        avisos: list[str] = []

        def mismo_host(enlace: str) -> bool:
            return (urlsplit(enlace).hostname or "").lower() == host and not _BINARIOS.search(urlsplit(enlace).path)

        try:
            sitemap = await self.obtener(f"{inicio.scheme}://{inicio.netloc}/sitemap.xml", tipos=None, aceptar_error=True)
        except WebError as exc:
            avisos.append(f"sitemap: {exc}")
        else:
            if sitemap.estado == 200:
                for loc in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", sitemap.texto):
                    enlace = _normalizar(html.unescape(loc))
                    if mismo_host(enlace) and len(encontradas) < LIMITE_URLS:
                        encontradas[enlace] = None

        cola = deque([(_normalizar(url), 0)])
        encoladas = {_normalizar(url)}
        visitadas = 0
        primer_error: WebError | None = None
        while cola and visitadas < max_paginas:
            actual, nivel = cola.popleft()
            try:
                extraccion = await self.extraer(actual)
            except WebError as exc:
                primer_error = primer_error or exc
                avisos.append(f"{actual}: {exc}")
                continue
            visitadas += 1
            encontradas[actual] = None
            if nivel >= profundidad:
                continue
            for enlace in extraccion.enlaces:
                if mismo_host(enlace) and enlace not in encoladas and len(encontradas) < LIMITE_URLS:
                    encoladas.add(enlace)
                    encontradas[enlace] = None
                    cola.append((enlace, nivel + 1))

        if not visitadas and not encontradas and primer_error is not None:
            raise primer_error
        return Mapa(list(encontradas), visitadas, avisos)
