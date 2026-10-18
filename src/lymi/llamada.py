"""Una llamada a un modelo que queda en el ledger, redactada y medida.

Lo usan las funciones que no son un paso de workflow pero si llaman a un modelo
(el resumen y los borradores de correo, desde la terminal o desde la app): pasan
por la misma pasarela que todo lo demas. Redactar antes de salir, rehidratar al
volver y anotar tokens, costo y hash es una sola cosa, no tres que recordar.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from lymi.bench.runner import Recorder
from lymi.providers.base import LLMClient, Message

Completar = Callable[[str, str], Awaitable[str]]
"""(sistema, texto) -> respuesta del modelo."""


def completador(rec: Recorder, cliente: LLMClient, proposito: str, *, max_tokens: int = 1500) -> Completar:
    async def completar(sistema: str, texto: str) -> str:
        enviados, sistema_final, redactor = rec.preparar(cliente, [Message("user", texto)], sistema)
        completion = await asyncio.to_thread(cliente.complete, enviados, system=sistema_final, max_tokens=max_tokens)
        if redactor is not None:
            completion.text = redactor.rehidratar(completion.text)
        rec.registrar(
            completion, enviados, purpose=proposito, system=sistema_final,
            redacciones=redactor.total if redactor is not None else 0,
        )
        return completion.text

    return completar
