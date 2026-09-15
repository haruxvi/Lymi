"""Busqueda web a traves de un buscador que controlas tu.

El buscador por defecto es SearXNG, software libre que corre en tu maquina y
consulta a varios motores sin cuenta ni clave. lymi no trae un buscador de pago
incorporado: la consulta es egress, y quien la recibe lo decides tu con
`LYMI_BUSCADOR_URL`.
"""

from __future__ import annotations

import ipaddress
import time
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Protocol
from urllib.parse import urlsplit

import httpx

from lymi.privacidad import sanear
from lymi.web.red import EventoRed, WebError, revisar_saliente


@dataclass(slots=True)
class Resultado:
    titulo: str
    url: str
    fragmento: str

    def como_dict(self) -> dict:
        return asdict(self)


class Buscador(Protocol):
    nombre: str
    eventos: list[EventoRed]

    async def buscar(self, consulta: str, n: int = 5) -> list[Resultado]: ...

    def vaciar_eventos(self) -> list[EventoRed]: ...


def _host_propio(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private


class SearxNG:
    """Cliente de la API JSON de SearXNG (`search.formats` debe incluir `json`)."""

    nombre = "searxng"

    def __init__(self, base_url: str, cliente: httpx.AsyncClient, *, timeout: float = 20.0) -> None:
        partes = urlsplit(base_url)
        host = (partes.hostname or "").lower()
        if partes.scheme not in {"http", "https"} or not host:
            raise ValueError(f"LYMI_BUSCADOR_URL invalida: {base_url!r}")
        if partes.scheme == "http" and not _host_propio(host):
            raise ValueError("LYMI_BUSCADOR_URL: http solo hacia tu maquina o tu red; afuera usa https")
        self.base = base_url.rstrip("/")
        self.host = host
        self._cliente = cliente
        self.timeout = timeout
        self.eventos: list[EventoRed] = []

    def vaciar_eventos(self) -> list[EventoRed]:
        eventos, self.eventos = self.eventos, []
        return eventos

    async def buscar(self, consulta: str, n: int = 5) -> list[Resultado]:
        consulta = consulta.strip()
        if not consulta:
            raise WebError("consulta vacia")
        revisar_saliente(consulta, "la consulta")
        inicio = time.perf_counter()

        def anotar(ok: bool, error: str | None = None) -> None:
            latencia = int((time.perf_counter() - inicio) * 1000)
            self.eventos.append(EventoRed("buscar", self.host, consulta, latencia, ok, error))

        try:
            resp = await self._cliente.get(
                f"{self.base}/search",
                params={"q": consulta, "format": "json"},
                timeout=self.timeout,
                follow_redirects=False,
            )
        except httpx.HTTPError as exc:
            anotar(False, type(exc).__name__)
            raise WebError(f"buscador {self.host}: {type(exc).__name__}", reintentable=True) from None
        anotar(resp.status_code < 400, None if resp.status_code < 400 else f"HTTP {resp.status_code}")
        if resp.status_code == 403:
            raise WebError("SearXNG rechazo format=json: agrega `json` a search.formats en su settings.yml")
        if resp.status_code >= 400:
            raise WebError(f"buscador {self.host}: HTTP {resp.status_code}", reintentable=resp.status_code >= 500)
        try:
            datos = resp.json()
        except ValueError:
            raise WebError("el buscador no devolvio JSON") from None

        resultados: list[Resultado] = []
        vistas: set[str] = set()
        for item in datos.get("results", []) if isinstance(datos, dict) else []:
            url = item.get("url") if isinstance(item, dict) else None
            if not isinstance(url, str) or not url.startswith(("http://", "https://")) or url in vistas:
                continue
            vistas.add(url)
            resultados.append(
                Resultado(
                    titulo=sanear(str(item.get("title", ""))).texto[:300],
                    url=url,
                    fragmento=sanear(str(item.get("content", ""))).texto[:500],
                )
            )
            if len(resultados) >= n:
                break
        return resultados


def buscador_configurado(entorno: Mapping[str, str], cliente: httpx.AsyncClient) -> SearxNG | None:
    url = entorno.get("LYMI_BUSCADOR_URL", "").strip()
    return SearxNG(url, cliente) if url else None
