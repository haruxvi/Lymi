"""Subcomandos `lymi web`: leer, mapear, buscar e investigar, todo en el ledger."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Annotated, Any

import httpx
import typer

from lymi.bench.runner import Recorder
from lymi.ledger import Billing, Ledger
from lymi.privacidad import EgressBloqueado
from lymi.providers.base import Message
from lymi.web import Buscador, Web, WebError, buscador_configurado, investigar

web_app = typer.Typer(
    help="La web leida por lymi: pagina a markdown, mapa de un sitio, busqueda e investigacion con citas verificadas.",
    no_args_is_help=True,
    add_completion=False,
)

_DB = Path("runs/lymi.sqlite3")


def _registrar(rec: Recorder, web: Web, buscador: Buscador | None, proposito: str) -> None:
    eventos = web.vaciar_eventos() + (buscador.vaciar_eventos() if buscador is not None else [])
    for ev in eventos:
        rec.integracion(
            tipo=ev.tipo, destino=ev.host, proposito=proposito, payload=ev.payload,
            latencia_ms=ev.latencia_ms, ok=ev.ok, error=ev.error,
        )


def _correr(
    operacion: str,
    db: Path,
    trabajo: Callable[[Web, Buscador | None, Recorder], Awaitable[Any]],
    *,
    billing: Billing = Billing.NONE,
    robots: bool = True,
) -> tuple[Any, str]:
    """Abre ledger, cliente y corrida; ejecuta; lleva cada peticion al ledger."""
    ledger = Ledger(db)
    try:
        with ledger.run("web", operacion, billing) as run:
            rec = Recorder(run)

            async def principal() -> tuple[Any, Web, Buscador | None]:
                async with httpx.AsyncClient(follow_redirects=False) as cliente:
                    web = Web(cliente, respetar_robots=robots)
                    buscador = buscador_configurado(os.environ, cliente)
                    try:
                        return await trabajo(web, buscador, rec), web, buscador
                    finally:
                        _registrar(rec, web, buscador, f"web:{operacion}")

            try:
                resultado, _, _ = asyncio.run(principal())
            except (WebError, EgressBloqueado, ValueError) as exc:
                run.fail(str(exc)[:300])
                typer.secho(f"  {exc}", fg=typer.colors.RED, err=True)
                raise typer.Exit(1) from None
        return resultado, run.run_id
    finally:
        ledger.close()


def _avisos(avisos: list[str]) -> None:
    for aviso in avisos:
        typer.secho(f"  aviso: {aviso}", fg=typer.colors.MAGENTA, err=True)


@web_app.command("leer")
def leer(
    url: Annotated[str, typer.Argument(help="Pagina a leer.")],
    max_caracteres: Annotated[int, typer.Option(min=500, help="Largo maximo del markdown.")] = 60_000,
    db: Annotated[Path, typer.Option(help="Ruta del ledger.")] = _DB,
) -> None:
    """Una pagina como markdown limpio (sin menus, scripts ni texto oculto)."""

    async def trabajo(web: Web, _b: Buscador | None, _r: Recorder):
        return await web.extraer(url, max_caracteres=max_caracteres)

    extraccion, run_id = _correr("leer", db, trabajo)
    # El titulo solo se imprime si el markdown no empieza ya con el mismo encabezado.
    if extraccion.titulo and not extraccion.markdown.lstrip().startswith(f"# {extraccion.titulo}"):
        typer.secho(f"# {extraccion.titulo}", bold=True)
        typer.echo()
    typer.echo(extraccion.markdown)
    _avisos(extraccion.avisos)
    typer.secho(f"  {len(extraccion.enlaces)} enlaces  |  corrida {run_id}", fg=typer.colors.BRIGHT_BLACK, err=True)


@web_app.command("mapear")
def mapear(
    url: Annotated[str, typer.Argument(help="Pagina de inicio del sitio.")],
    max_paginas: Annotated[int, typer.Option(min=1, max=200, help="Paginas que se leen como maximo.")] = 20,
    profundidad: Annotated[int, typer.Option(min=0, max=3, help="Saltos de enlace desde el inicio.")] = 1,
    db: Annotated[Path, typer.Option(help="Ruta del ledger.")] = _DB,
) -> None:
    """URLs de un sitio (sitemap y enlaces), sin salir del mismo host."""

    async def trabajo(web: Web, _b: Buscador | None, _r: Recorder):
        return await web.mapear(url, max_paginas=max_paginas, profundidad=profundidad)

    mapa, run_id = _correr("mapear", db, trabajo)
    for encontrada in mapa.urls:
        typer.echo(encontrada)
    _avisos(mapa.avisos)
    typer.secho(
        f"  {len(mapa.urls)} URLs, {mapa.visitadas} paginas leidas  |  corrida {run_id}",
        fg=typer.colors.BRIGHT_BLACK, err=True,
    )


@web_app.command("buscar")
def buscar(
    consulta: Annotated[str, typer.Argument(help="Que buscar.")],
    n: Annotated[int, typer.Option("-n", min=1, max=20, help="Resultados.")] = 5,
    db: Annotated[Path, typer.Option(help="Ruta del ledger.")] = _DB,
) -> None:
    """Busca con tu buscador (LYMI_BUSCADOR_URL, ej. SearXNG local)."""

    async def trabajo(_w: Web, buscador: Buscador | None, _r: Recorder):
        if buscador is None:
            raise WebError("no hay buscador: define LYMI_BUSCADOR_URL (por ejemplo http://127.0.0.1:8888)")
        return await buscador.buscar(consulta, n)

    resultados, run_id = _correr("buscar", db, trabajo)
    for i, r in enumerate(resultados, start=1):
        typer.secho(f"  [{i}] {r.titulo}", bold=True)
        typer.secho(f"      {r.url}", fg=typer.colors.CYAN)
        if r.fragmento:
            typer.echo(f"      {r.fragmento[:200]}")
    typer.secho(f"  corrida {run_id}", fg=typer.colors.BRIGHT_BLACK, err=True)


@web_app.command("investigar")
def investigar_cmd(
    pregunta: Annotated[str, typer.Argument(help="La pregunta.")],
    url: Annotated[list[str] | None, typer.Option("--url", help="Fuente fija; repetible. Sin esto, se busca.")] = None,
    remoto: Annotated[bool, typer.Option("--remoto", help="Redacta el modelo remoto (pasa por la pasarela).")] = False,
    max_fuentes: Annotated[int, typer.Option(min=1, max=10, help="Fuentes que se leen.")] = 5,
    db: Annotated[Path, typer.Option(help="Ruta del ledger.")] = _DB,
) -> None:
    """Responde con fuentes numeradas y comprueba cada cita textual en su fuente."""
    from lymi.bench.wiring import proveedores

    local, etiqueta_local, cliente_remoto, etiqueta_remota = proveedores()
    cliente = cliente_remoto if remoto else local
    if cliente is None:
        typer.secho(f"  no hay modelo {'remoto' if remoto else 'local'}: corre `lymi setup`", fg=typer.colors.RED)
        raise typer.Exit(1)
    typer.secho(f"  redacta: {etiqueta_remota if remoto else etiqueta_local}", fg=typer.colors.CYAN, err=True)

    async def trabajo(web: Web, buscador: Buscador | None, rec: Recorder):
        async def completar(sistema: str, mensaje: str) -> str:
            enviados, sistema_final, redactor = rec.preparar(cliente, [Message("user", mensaje)], sistema)
            completion = await asyncio.to_thread(cliente.complete, enviados, system=sistema_final, max_tokens=2048)
            if redactor is not None:
                completion.text = redactor.rehidratar(completion.text)
            rec.registrar(
                completion, enviados, purpose="web:investigar", system=sistema_final,
                redacciones=redactor.total if redactor is not None else 0,
            )
            return completion.text

        return await investigar(
            pregunta, web=web, buscador=buscador, urls=url or [], completar=completar, max_fuentes=max_fuentes
        )

    informe, run_id = _correr("investigar", db, trabajo, billing=cliente.billing)
    typer.echo()
    typer.echo(informe.respuesta)
    typer.echo()
    for fuente in informe.fuentes:
        if fuente.titulo:
            typer.secho(f"  [{fuente.n}] {fuente.titulo}", bold=True)
            typer.secho(f"      {fuente.url}", fg=typer.colors.CYAN)
        else:
            typer.secho(f"  [{fuente.n}] {fuente.url}", fg=typer.colors.CYAN)
    typer.echo()
    v = informe.verificacion
    color = typer.colors.GREEN if not v.problemas else typer.colors.YELLOW
    typer.secho(f"  verificacion: {v.resumen()}", fg=color)
    for cita in v.citas:
        if cita.estado != "verificada":
            typer.secho(f"    [{cita.fuente}] «{cita.frase[:120]}»  -> {cita.estado}", fg=typer.colors.YELLOW)
    _avisos(informe.avisos)
    typer.secho(f"  corrida {run_id}  (lymi ledger)", fg=typer.colors.BRIGHT_BLACK, err=True)
