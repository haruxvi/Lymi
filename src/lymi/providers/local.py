"""Tier local via Ollama.

Seguridad: un tier llamado "local" que apunte a un host remoto seria una fuga
silenciosa disfrazada de privacidad. Por eso la URL se valida contra loopback y
salir de ahi exige un opt-in explicito y ruidoso.
"""

from __future__ import annotations

import ipaddress
import json
import os
import socket
import time
from urllib.parse import urlparse

import httpx

from lymi.ledger import Billing
from lymi.providers.base import Completion, Message, Usage

DEFAULT_URL = "http://localhost:11434"
DEFAULT_MODEL = "qwen2.5:3b"
"""Medido el 2026-09-13 en un portatil con 4 GB de VRAM, mismo prompt de resumen:
qwen2.5:3b cabe entero en la GPU y responde en 0.4 s con 20 tokens; qwen3:4b
reparte 33/67 CPU/GPU, razona 700 tokens y no llega a responder en 64 s. Para
destilar y clasificar gana el modelo que contesta directo."""
SILENCIO_MAXIMO = 120.0
"""Segundos sin recibir un solo token antes de dar el servidor por muerto.

La respuesta se lee en streaming, asi que este limite mide SILENCIO, no
duracion. Un modelo lento pero vivo nunca lo alcanza; uno colgado, enseguida.
Con un timeout sobre la respuesta completa habria que adivinar cuanto tarda un
modelo en una maquina desconocida, y adivinar de menos corta generaciones sanas.
"""
TIMEOUT = httpx.Timeout(connect=5.0, read=SILENCIO_MAXIMO, write=30.0, pool=5.0)


class NonLocalEndpointError(RuntimeError):
    """La URL del tier 'local' no resuelve a loopback."""


class LocalTimeoutError(RuntimeError):
    """El servidor local dejo de enviar tokens."""


def assert_loopback(url: str, *, allow_remote: bool = False) -> None:
    """Verifica que `url` apunte a esta maquina.

    Resuelve el hostname en vez de compararlo como texto: 'localhost' se puede
    reapuntar en el archivo hosts, y un chequeo por string no lo detectaria.
    """
    if allow_remote:
        return
    host = urlparse(url).hostname
    if not host:
        raise NonLocalEndpointError(f"URL sin host: {url!r}")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise NonLocalEndpointError(f"No se pudo resolver {host!r}: {exc}") from exc

    for *_, sockaddr in infos:
        if not ipaddress.ip_address(sockaddr[0]).is_loopback:
            raise NonLocalEndpointError(
                f"El tier local apunta a {host!r} -> {sockaddr[0]}, que no es loopback. "
                "Tus datos saldrian de la maquina. Si es intencional, pasa "
                "allow_remote=True o LYMI_ALLOW_REMOTE_LOCAL=1."
            )


class OllamaClient:
    """Cliente del tier local. Costo monetario cero; el costo real es latencia."""

    provider = "ollama"
    billing = Billing.LOCAL
    tier = "local"

    def __init__(
        self,
        model: str | None = None,
        url: str | None = None,
        *,
        allow_remote: bool | None = None,
        client: httpx.Client | None = None,
        think: bool | None = None,
    ) -> None:
        # Los modelos de razonamiento (qwen3 entre ellos) gastan el presupuesto
        # de tokens en el bloque de pensamiento y devuelven contenido vacio si se
        # corta antes. En el tier local el pensamiento casi nunca paga lo que
        # cuesta: aqui se destila y se clasifica, no se razona.
        self.think = think if think is not None else os.getenv("LYMI_LOCAL_THINK") == "1"
        self.model = model or os.getenv("LYMI_LOCAL_MODEL", DEFAULT_MODEL)
        self.url = (url or os.getenv("LYMI_OLLAMA_URL", DEFAULT_URL)).rstrip("/")
        if allow_remote is None:
            allow_remote = os.getenv("LYMI_ALLOW_REMOTE_LOCAL") == "1"
        assert_loopback(self.url, allow_remote=allow_remote)
        self._client = client or httpx.Client(timeout=TIMEOUT)

    def complete(
        self,
        messages: list[Message],
        *,
        system: str | None = None,
        max_tokens: int = 4096,
        cache_system: bool = False,
    ) -> Completion:
        payload: dict = {
            "model": self.model,
            "messages": (
                ([{"role": "system", "content": system}] if system else [])
                + [{"role": m.role, "content": m.content} for m in messages]
            ),
            "stream": True,
            "think": self.think,
            "options": {"num_predict": max_tokens},
        }
        started = time.perf_counter()
        partes: list[str] = []
        pensamiento: list[str] = []
        data: dict = {}
        try:
            with self._client.stream("POST", f"{self.url}/api/chat", json=payload) as resp:
                resp.raise_for_status()
                for linea in resp.iter_lines():
                    if not linea.strip():
                        continue
                    trozo = json.loads(linea)
                    if error := trozo.get("error"):
                        raise RuntimeError(f"ollama: {error}")
                    mensaje = trozo.get("message", {})
                    partes.append(mensaje.get("content", ""))
                    pensamiento.append(mensaje.get("thinking") or "")
                    if trozo.get("done"):
                        data = trozo
        except httpx.TimeoutException as exc:
            corridos = time.perf_counter() - started
            raise LocalTimeoutError(
                f"{self.model} no envio nada en {SILENCIO_MAXIMO:g} s "
                f"(llevaba {corridos:.0f} s y {len(''.join(partes))} caracteres). "
                "Revisa que el servidor siga vivo: ollama ps"
            ) from exc
        latency_ms = int((time.perf_counter() - started) * 1000)

        return Completion(
            text="".join(partes),
            usage=Usage(
                input_tokens=data.get("prompt_eval_count", 0),
                output_tokens=data.get("eval_count", 0),
            ),
            model=self.model,
            provider=self.provider,
            billing=self.billing,
            tier=self.tier,
            latency_ms=latency_ms,
            stop_reason=data.get("done_reason"),
            # El pensamiento gasta tokens igual que el texto: queda contado, no
            # escondido, aunque no se use.
            raw={**data, "thinking_chars": len("".join(pensamiento))},
        )

    def close(self) -> None:
        self._client.close()
