"""Subcomandos `lymi calendario`: tu agenda, leida de archivos .ics locales."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated

import typer

from lymi.calendario import Calendario, CalendarioError

calendario_app = typer.Typer(
    help="Tu agenda desde archivos .ics locales. Sin conexiones: lymi no habla con Google.",
    no_args_is_help=True,
    add_completion=False,
)


def _eventos(dias: int, carpeta: Path | None):
    calendario = Calendario(carpeta)
    inicio = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        return calendario, calendario.eventos(inicio, inicio + timedelta(days=dias))
    except CalendarioError as exc:
        typer.secho(f"  {exc}", fg=typer.colors.RED)
        raise typer.Exit(1) from None


@calendario_app.command("hoy")
def hoy(
    dias: Annotated[int, typer.Option(min=1, max=60, help="Dias a mostrar desde hoy.")] = 1,
    carpeta: Annotated[Path | None, typer.Option("--carpeta", help="Carpeta con los .ics.")] = None,
) -> None:
    """Lo que tienes agendado."""
    calendario, (eventos, avisos) = _eventos(dias, carpeta)
    typer.secho(f"  {len(calendario.archivos())} calendarios en {calendario.raiz}", fg=typer.colors.BRIGHT_BLACK)
    if not eventos:
        typer.echo("  Nada agendado.")
    for evento in eventos:
        typer.echo(f"  {evento.resumen()}")
    for aviso in avisos:
        typer.secho(f"  aviso: {aviso}", fg=typer.colors.MAGENTA, err=True)


@calendario_app.command("semana")
def semana(
    carpeta: Annotated[Path | None, typer.Option("--carpeta", help="Carpeta con los .ics.")] = None,
) -> None:
    """Los proximos siete dias."""
    hoy(dias=7, carpeta=carpeta)
