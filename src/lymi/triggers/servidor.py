"""Servidor de disparadores: webhooks entrantes y ejecucion de la agenda.

Escucha en 127.0.0.1 por defecto. Exponerlo a internet es una decision explicita
de quien lo lanza, detras de su propio proxy o tunel con TLS.

Defensas:

- Un webhook inexistente o inactivo responde igual que una firma invalida: nadie
  puede enumerar que nombres existen.
- El cuerpo se lee con tope: una peticion gigante no llega entera a memoria.
- La firma se verifica antes de registrar la entrega: un atacante sin secreto no
  puede envenenar la deduplicacion.
- Hay un maximo de corridas simultaneas; por encima, 429.
- La agenda marca cada programacion como ejecutada ANTES de correrla: si el
  proceso cae a mitad, no la repite en bucle al volver.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from lymi.flows.engine import EntradaError, ejecutar_flujo, preparar_inputs
from lymi.flows.schema import WorkflowError, cargar
from lymi.ledger import Ledger
from lymi.providers.base import LLMClient
from lymi.triggers import webhook
from lymi.triggers.agenda import Agenda
from lymi.triggers.ganchos import SERVICIO, Ganchos
from lymi.triggers.politica import aprobador_desatendido

log = logging.getLogger("lymi.serve")


@dataclass(slots=True)
class ConfigServidor:
    ledger: Path
    agenda: Path
    ganchos: Path
    max_corridas: int = 4
    intervalo_agenda: float | None = 20.0
    """Segundos entre revisiones de la agenda. `None` la desactiva."""
    local: LLMClient | None = None
    remote: LLMClient | None = None
    servicio_secretos: str = SERVICIO


@dataclass(slots=True)
class EstadoServidor:
    config: ConfigServidor
    ledger: Ledger
    agenda: Agenda
    ganchos: Ganchos
    dedup: webhook.Deduplicador = field(default_factory=webhook.Deduplicador)
    en_curso: int = 0
    tareas: set[asyncio.Task[None]] = field(default_factory=set)


def abrir_estado(config: ConfigServidor) -> EstadoServidor:
    """Abre los almacenes. Debe llamarse en el hilo del bucle: SQLite no cruza hilos."""
    return EstadoServidor(
        config=config,
        ledger=Ledger(config.ledger),
        agenda=Agenda(config.agenda),
        ganchos=Ganchos(config.ganchos, servicio=config.servicio_secretos),
    )


async def cerrar_estado(estado: EstadoServidor, *, espera: float = 30.0) -> None:
    """Espera las corridas en curso y cierra los almacenes."""
    if estado.tareas:
        await asyncio.wait(set(estado.tareas), timeout=espera)
    estado.ledger.close()
    estado.agenda.close()
    estado.ganchos.close()


def lanzar(
    estado: EstadoServidor,
    workflow: Path,
    entradas: dict[str, Any],
    aprobados: frozenset[str],
    origen: str,
) -> bool:
    """Lanza una corrida en segundo plano si hay cupo. Devuelve False si no lo hay."""
    # Un solo hilo de bucle: comprobar e incrementar no tiene carrera.
    if estado.en_curso >= estado.config.max_corridas:
        return False
    estado.en_curso += 1

    async def correr() -> None:
        try:
            flujo = cargar(workflow)  # se relee: el archivo pudo cambiar desde que se programo
            resultado = await ejecutar_flujo(
                flujo,
                entradas,
                ledger=estado.ledger,
                local=estado.config.local,
                remote=estado.config.remote,
                aprobar=aprobador_desatendido(aprobados),
                variante=origen,
            )
            log.info("%s: corrida %s %s", origen, resultado.run_id, "ok" if resultado.ok else resultado.detalle)
        except (WorkflowError, EntradaError) as exc:
            log.warning("%s: no se pudo correr %s: %s", origen, workflow, exc)
        except Exception:
            log.exception("%s: fallo inesperado", origen)
        finally:
            estado.en_curso -= 1

    tarea = asyncio.create_task(correr(), name=origen)
    estado.tareas.add(tarea)
    tarea.add_done_callback(estado.tareas.discard)
    return True


async def revisar_agenda(estado: EstadoServidor, ahora: datetime | None = None) -> list[str]:
    """Lanza las programaciones vencidas. Devuelve los ids lanzados."""
    ahora = ahora or datetime.now(UTC)
    lanzadas: list[str] = []
    for prog in estado.agenda.vencidas(ahora):
        if estado.en_curso >= estado.config.max_corridas:
            break  # las que quedan siguen vencidas y se reintentan en la proxima revision
        # Primero se marca, despues se corre: una caida a mitad no provoca repeticiones en bucle.
        estado.agenda.marcar_ejecutada(prog.id, ahora)
        lanzar(estado, prog.workflow, prog.entradas, prog.aprobados, f"agenda:{prog.id}")
        lanzadas.append(prog.id)
    return lanzadas


async def _bucle_agenda(estado: EstadoServidor, intervalo: float) -> None:
    while True:
        try:
            await revisar_agenda(estado)
        except Exception:
            log.exception("fallo revisando la agenda")
        await asyncio.sleep(intervalo)


async def _leer_cuerpo(request: Request) -> bytes:
    partes: list[bytes] = []
    total = 0
    async for trozo in request.stream():
        total += len(trozo)
        if total > webhook.LIMITE_CUERPO:
            raise webhook.WebhookError(413, f"el cuerpo supera {webhook.LIMITE_CUERPO} bytes")
        partes.append(trozo)
    return b"".join(partes)


async def recibir_webhook(request: Request) -> JSONResponse:
    estado: EstadoServidor = request.app.state.lymi
    nombre = request.path_params["nombre"]

    try:
        cuerpo = await _leer_cuerpo(request)
        gancho = estado.ganchos.obtener(nombre)
        secreto = estado.ganchos.secreto(nombre) if gancho is not None else None
        if gancho is None or not gancho.activo or secreto is None:
            raise webhook.WebhookError(401, "firma invalida", "webhook inexistente, inactivo o sin secreto")

        if gancho.esquema == "github":
            webhook.verificar_github(secreto, cuerpo, request.headers.get(webhook.CABECERA_GITHUB))
            entrega = request.headers.get(webhook.CABECERA_ENTREGA_GITHUB) or request.headers.get(
                webhook.CABECERA_GITHUB, ""
            )
        else:
            entrega = webhook.verificar_firma(secreto, cuerpo, request.headers.get(webhook.CABECERA_FIRMA))
        estado.dedup.registrar(f"{nombre}:{entrega}")

        flujo = cargar(gancho.workflow)
        entradas = webhook.entradas(flujo, cuerpo)
        preparar_inputs(flujo, entradas)
    except webhook.WebhookError as exc:
        log.info("webhook %s rechazado (%s): %s", nombre, exc.estado, exc.motivo)
        return JSONResponse({"error": str(exc)}, status_code=exc.estado)
    except EntradaError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except WorkflowError as exc:
        log.error("webhook %s: su workflow no es valido: %s", nombre, exc)
        return JSONResponse({"error": "el workflow de este webhook no es valido"}, status_code=500)

    if not lanzar(estado, gancho.workflow, entradas, gancho.aprobados, f"webhook:{nombre}"):
        return JSONResponse({"error": "ocupado, reintenta mas tarde"}, status_code=429, headers={"Retry-After": "30"})
    return JSONResponse({"aceptado": True}, status_code=202)


async def salud(_request: Request) -> JSONResponse:
    return JSONResponse({"ok": True})


def crear_app(config: ConfigServidor) -> Starlette:
    """Aplicacion ASGI con webhooks, salud y el bucle de la agenda."""

    @asynccontextmanager
    async def ciclo(app: Starlette) -> AsyncIterator[None]:
        estado = abrir_estado(config)
        app.state.lymi = estado
        bucle = None
        if config.intervalo_agenda:
            bucle = asyncio.create_task(_bucle_agenda(estado, config.intervalo_agenda), name="agenda")
        try:
            yield
        finally:
            if bucle is not None:
                bucle.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await bucle
            await cerrar_estado(estado)

    return Starlette(
        routes=[
            Route("/salud", salud, methods=["GET"]),
            Route("/hooks/{nombre}", recibir_webhook, methods=["POST"]),
        ],
        lifespan=ciclo,
    )
