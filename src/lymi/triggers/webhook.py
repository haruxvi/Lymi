"""Disparo de workflows por webhook entrante: firma, frescura, repeticion y entradas.

Un webhook es una puerta abierta a internet que ejecuta un workflow. Por eso:

- **Firma HMAC-SHA256** del cuerpo con un secreto por webhook, comparada en
  tiempo constante.
- **Marca de tiempo firmada** con ventana de cinco minutos: una peticion
  capturada no sirve manana.
- **Deduplicacion** dentro de la ventana: tampoco sirve dos veces hoy.
- **Un solo mensaje para todo rechazo de firma.** Distinguir "firma invalida" de
  "fuera de ventana" le diria a quien prueba que parte acerto. El motivo real
  queda en `motivo`, para el registro local.
- **Cuerpo acotado** y JSON obligatorio, con solo las entradas que el workflow
  declara.

Tambien acepta el esquema de GitHub (`X-Hub-Signature-256`), que no firma marca
de tiempo: ahi la proteccion contra repeticion recae en el id de entrega.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections import OrderedDict
from typing import Any

from lymi.flows.schema import Workflow

CABECERA_FIRMA = "X-Lymi-Signature"
CABECERA_GITHUB = "X-Hub-Signature-256"
CABECERA_ENTREGA_GITHUB = "X-GitHub-Delivery"
VENTANA_SEGUNDOS = 300
LIMITE_CUERPO = 1_000_000
LARGO_MINIMO_SECRETO = 32

_FIRMA_INVALIDA = "firma invalida"


class WebhookError(ValueError):
    """Rechazo de un disparo. `estado` es el codigo HTTP a responder."""

    def __init__(self, estado: int, mensaje: str, motivo: str | None = None) -> None:
        super().__init__(mensaje)
        self.estado = estado
        self.motivo = motivo or mensaje


def _mac(secreto: bytes, datos: bytes) -> str:
    return hmac.new(secreto, datos, hashlib.sha256).hexdigest()


def _exigir_secreto(secreto: bytes) -> None:
    if len(secreto) < LARGO_MINIMO_SECRETO:
        raise WebhookError(500, "configuracion invalida del webhook", f"secreto de menos de {LARGO_MINIMO_SECRETO} bytes")


def firmar(secreto: bytes, cuerpo: bytes, marca: int | None = None) -> str:
    """Cabecera `X-Lymi-Signature` para `cuerpo`. Sirve a quien envia el webhook."""
    _exigir_secreto(secreto)
    marca = int(time.time()) if marca is None else marca
    return f"t={marca},v1={_mac(secreto, f'{marca}.'.encode() + cuerpo)}"


def verificar_firma(secreto: bytes, cuerpo: bytes, cabecera: str | None, *, ahora: int | None = None) -> str:
    """Verifica una firma de lymi. Devuelve la firma aceptada, util para deduplicar."""
    _exigir_secreto(secreto)
    if not cabecera:
        raise WebhookError(401, _FIRMA_INVALIDA, "falta la cabecera de firma")

    campos: dict[str, list[str]] = {}
    for parte in cabecera.split(","):
        clave, separador, valor = parte.strip().partition("=")
        if separador:
            campos.setdefault(clave, []).append(valor)

    try:
        marca = int(campos["t"][0])
    except (KeyError, IndexError, ValueError):
        raise WebhookError(401, _FIRMA_INVALIDA, "cabecera de firma mal formada") from None

    ahora = int(time.time()) if ahora is None else ahora
    if abs(ahora - marca) > VENTANA_SEGUNDOS:
        raise WebhookError(401, _FIRMA_INVALIDA, "marca de tiempo fuera de la ventana")

    esperada = _mac(secreto, f"{marca}.".encode() + cuerpo)
    # Varias v1 permiten rotar el secreto sin cortar el servicio.
    for candidata in campos.get("v1", []):
        if hmac.compare_digest(esperada, candidata):
            return candidata
    raise WebhookError(401, _FIRMA_INVALIDA, "la firma no coincide")


def verificar_github(secreto: bytes, cuerpo: bytes, cabecera: str | None) -> None:
    """Verifica `X-Hub-Signature-256` de GitHub."""
    _exigir_secreto(secreto)
    if not cabecera or not cabecera.startswith("sha256="):
        raise WebhookError(401, _FIRMA_INVALIDA, "falta sha256= en la cabecera de GitHub")
    if not hmac.compare_digest(f"sha256={_mac(secreto, cuerpo)}", cabecera):
        raise WebhookError(401, _FIRMA_INVALIDA, "la firma de GitHub no coincide")


class Deduplicador:
    """Recuerda entregas recientes para rechazar repeticiones.

    Vive en memoria: tras un reinicio se olvida. Para el esquema de lymi eso deja
    abierta, como mucho, la ventana de cinco minutos de la marca de tiempo.
    """

    def __init__(self, capacidad: int = 10_000) -> None:
        self._capacidad = capacidad
        self._vistas: OrderedDict[str, None] = OrderedDict()

    def registrar(self, clave: str) -> None:
        if clave in self._vistas:
            raise WebhookError(409, "entrega repetida")
        self._vistas[clave] = None
        if len(self._vistas) > self._capacidad:
            self._vistas.popitem(last=False)


def validar_tamano(cuerpo: bytes) -> None:
    if len(cuerpo) > LIMITE_CUERPO:
        raise WebhookError(413, f"el cuerpo supera {LIMITE_CUERPO} bytes")


def entradas(flujo: Workflow, cuerpo: bytes) -> dict[str, Any]:
    """Entradas del workflow a partir del cuerpo JSON del disparo."""
    validar_tamano(cuerpo)
    if not cuerpo.strip():
        return {}
    try:
        datos = json.loads(cuerpo)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise WebhookError(400, "el cuerpo debe ser JSON") from None
    if not isinstance(datos, dict):
        raise WebhookError(400, "el cuerpo debe ser un objeto JSON")
    desconocidas = sorted(set(datos) - set(flujo.inputs))
    if desconocidas:
        raise WebhookError(400, f"entradas desconocidas: {', '.join(desconocidas)}")
    return datos
