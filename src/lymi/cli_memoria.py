"""Subcomandos `lymi memoria`: anotar, buscar y revisar lo que anotaron los agentes."""

from __future__ import annotations

from typing import Annotated

import typer

from lymi.memoria import Memoria, MemoriaError, formato

memoria_app = typer.Typer(
    help="Memoria entre sesiones: afirmaciones de agentes, hechos que revisas tu.",
    no_args_is_help=True,
    add_completion=False,
)


def _error(exc: Exception) -> None:
    typer.secho(f"  {exc}", fg=typer.colors.RED)
    raise typer.Exit(1) from None


@memoria_app.command("anotar")
def anotar(
    texto: Annotated[str, typer.Argument(help="Lo que hay que recordar.")],
    fuente: Annotated[str, typer.Option(help="De donde sale: una URL, una reunion, un documento.")] = "usuario",
    hecho: Annotated[bool, typer.Option("--hecho", help="Lo afirmas tu: entra como hecho, sin revision.")] = False,
) -> None:
    """Anota algo. Sin --hecho queda como afirmacion por revisar."""
    try:
        nota = Memoria().anotar(texto, fuente=fuente, hecho=hecho)
    except MemoriaError as exc:
        _error(exc)
    typer.secho(f"  {nota.estado} {nota.id}  ({nota.ruta.as_posix()})", fg=typer.colors.GREEN)


@memoria_app.command("buscar")
def buscar(
    consulta: Annotated[str, typer.Argument(help="Que buscar.")],
    n: Annotated[int, typer.Option("-n", min=1, max=20)] = 5,
    solo_hechos: Annotated[bool, typer.Option("--solo-hechos", help="Ignora lo que nadie reviso.")] = False,
) -> None:
    """Busca en hechos, notas propias y (salvo --solo-hechos) afirmaciones sin revisar."""
    memoria = Memoria()
    try:
        typer.echo(formato(memoria.buscar(consulta, n, solo_hechos=solo_hechos), memoria.raiz))
    except MemoriaError as exc:
        _error(exc)


@memoria_app.command("pendientes")
def pendientes() -> None:
    """Afirmaciones que anotaron los agentes y esperan tu revision."""
    notas = Memoria().listar("afirmaciones")
    if not notas:
        typer.echo("  No hay afirmaciones por revisar.")
        return
    for nota in notas:
        typer.secho(f"  {nota.id}  {nota.agente}  fuente: {nota.fuente or '-'}", bold=True)
        for linea in nota.texto.splitlines()[:6]:
            typer.echo(f"    {linea}")
    typer.secho("  lymi memoria promover <id>  |  lymi memoria descartar <id>", fg=typer.colors.BRIGHT_BLACK)


@memoria_app.command("promover")
def promover(nota_id: Annotated[str, typer.Argument(help="Id de la afirmacion.")]) -> None:
    """La afirmacion pasa a hecho: desde ahora los agentes la ven como verdad."""
    try:
        nota = Memoria().promover(nota_id)
    except MemoriaError as exc:
        _error(exc)
    typer.secho(f"  hecho {nota.id}", fg=typer.colors.GREEN)


@memoria_app.command("descartar")
def descartar(nota_id: Annotated[str, typer.Argument(help="Id de la afirmacion.")]) -> None:
    """La afirmacion se descarta. No se borra: queda en descartadas/ para auditar."""
    try:
        nota = Memoria().descartar(nota_id)
    except MemoriaError as exc:
        _error(exc)
    typer.secho(f"  descartada {nota.id}", fg=typer.colors.YELLOW)
