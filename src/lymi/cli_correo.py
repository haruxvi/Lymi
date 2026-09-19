"""Subcomandos `lymi correo`: leer el buzon local de Thunderbird y resumirlo."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated

import typer

from lymi.bench.runner import Recorder
from lymi.correo import Buzon, CorreoError, render, resumir
from lymi.ledger import Ledger
from lymi.providers.base import Message

correo_app = typer.Typer(
    help="Tu correo, leido del buzon local de Thunderbird. Solo lectura: lymi no ve tus claves.",
    no_args_is_help=True,
    add_completion=False,
)

_DB = Path("runs/lymi.sqlite3")


def _buzon() -> Buzon:
    try:
        return Buzon()
    except CorreoError as exc:
        typer.secho(f"  {exc}", fg=typer.colors.RED)
        raise typer.Exit(1) from None


@correo_app.command("carpetas")
def carpetas() -> None:
    """Las carpetas que Thunderbird tiene descargadas en este equipo."""
    with _buzon() as buzon:
        try:
            datos = buzon.carpetas()
        except CorreoError as exc:
            typer.secho(f"  {exc}", fg=typer.colors.RED)
            raise typer.Exit(1) from None
        typer.secho(f"  perfil: {buzon.perfil}", fg=typer.colors.BRIGHT_BLACK)
        if not datos:
            typer.secho(
                "  no hay carpetas descargadas. En Thunderbird: Configuracion de la cuenta ->"
                " Sincronizacion y almacenamiento -> mantener los mensajes en este equipo",
                fg=typer.colors.YELLOW,
            )
            return
        for c in datos:
            tamano = f"{c['bytes'] / 1e6:.0f} MB"
            typer.echo(f"  {c['carpeta']:<40}{c['mensajes']:>7} mensajes{c['sin_leer']:>7} sin leer{tamano:>9}")


@correo_app.command("ver")
def ver(
    carpeta: Annotated[str, typer.Option(help="Carpeta; basta el nombre corto (INBOX).")] = "INBOX",
    n: Annotated[int, typer.Option("-n", min=1, max=200)] = 20,
    dias: Annotated[int | None, typer.Option(help="Solo los ultimos N dias.")] = None,
    sin_leer: Annotated[bool, typer.Option("--sin-leer", help="Solo los no leidos.")] = False,
) -> None:
    """Lista los mensajes mas recientes: fecha, remitente y asunto."""
    with _buzon() as buzon:
        try:
            mensajes = buzon.listar(carpeta, n=n, dias=dias, solo_sin_leer=sin_leer)
        except CorreoError as exc:
            typer.secho(f"  {exc}", fg=typer.colors.RED)
            raise typer.Exit(1) from None
    for mensaje in mensajes:
        color = typer.colors.BRIGHT_BLACK if mensaje.boletin else None
        typer.secho(f"  {mensaje.resumen()}", fg=color)
    if not mensajes:
        typer.echo("  Nada que mostrar con ese filtro.")


@correo_app.command("leer")
def leer(
    id_mensaje: Annotated[str, typer.Argument(help="Id del mensaje, como aparece en `ver` (INBOX:1234).")],
    carpeta: Annotated[str, typer.Option(help="Carpeta si el id es solo un numero.")] = "INBOX",
) -> None:
    """Muestra un mensaje como texto limpio."""
    if ":" in id_mensaje:
        carpeta, _, numero = id_mensaje.rpartition(":")
    else:
        numero = id_mensaje
    if not numero.isdigit():
        typer.secho("  el id es carpeta:numero, o un numero con --carpeta", fg=typer.colors.RED)
        raise typer.Exit(1)
    with _buzon() as buzon:
        try:
            mensaje = buzon.leer(carpeta, int(numero))
        except CorreoError as exc:
            typer.secho(f"  {exc}", fg=typer.colors.RED)
            raise typer.Exit(1) from None
    cuando = mensaje.fecha.strftime("%Y-%m-%d %H:%M") if mensaje.fecha else "sin fecha"
    typer.secho(f"De: {mensaje.de}", bold=True)
    typer.echo(f"Para: {mensaje.para}\nFecha: {cuando}\nAsunto: {mensaje.asunto}")
    if mensaje.adjuntos:
        typer.echo(f"Adjuntos: {', '.join(mensaje.adjuntos)}")
    typer.echo()
    typer.echo(mensaje.cuerpo or "(sin texto)")
    for aviso in mensaje.avisos:
        typer.secho(f"  aviso: {aviso}", fg=typer.colors.MAGENTA, err=True)


@correo_app.command("resumen")
def resumen(
    dias: Annotated[int, typer.Option(min=1, max=30, help="Ventana a resumir.")] = 1,
    carpeta: Annotated[str, typer.Option(help="Carpeta a resumir.")] = "INBOX",
    n: Annotated[int, typer.Option("-n", min=1, max=200, help="Tope de mensajes a mirar.")] = 60,
    remoto: Annotated[bool, typer.Option("--remoto", help="Anota el modelo remoto (gasta tokens).")] = False,
    db: Annotated[Path, typer.Option(help="Ruta del ledger.")] = _DB,
) -> None:
    """Resumen del correo reciente. Los datos salen del archivo; el modelo solo anota."""
    from lymi.bench.wiring import proveedores

    local, etiqueta_local, cliente_remoto, etiqueta_remota = proveedores()
    cliente = cliente_remoto if remoto else local
    if cliente is None:
        typer.secho(f"  no hay modelo {'remoto' if remoto else 'local'}: corre `lymi setup`", fg=typer.colors.RED)
        raise typer.Exit(1)
    typer.secho(f"  anota: {etiqueta_remota if remoto else etiqueta_local}", fg=typer.colors.CYAN, err=True)

    with _buzon() as buzon:
        try:
            mensajes = buzon.listar(carpeta, n=n, dias=dias)
        except CorreoError as exc:
            typer.secho(f"  {exc}", fg=typer.colors.RED)
            raise typer.Exit(1) from None
    if not mensajes:
        typer.echo(f"  No llego nada en {dias} dia(s).")
        return

    ledger = Ledger(db)
    try:
        with ledger.run("correo", "resumen", cliente.billing) as run:
            rec = Recorder(run)

            async def completar(sistema: str, texto: str) -> str:
                enviados, sistema_final, redactor = rec.preparar(cliente, [Message("user", texto)], sistema)
                completion = await asyncio.to_thread(
                    cliente.complete, enviados, system=sistema_final, max_tokens=1500
                )
                if redactor is not None:
                    completion.text = redactor.rehidratar(completion.text)
                rec.registrar(
                    completion, enviados, purpose="correo:resumen", system=sistema_final,
                    redacciones=redactor.total if redactor is not None else 0,
                )
                return completion.text

            informe = asyncio.run(resumir(
                mensajes, completar, desde=datetime.now(UTC) - timedelta(days=dias), hasta=datetime.now(UTC)
            ))
        totales = ledger.totals(run.run_id) or {}
    finally:
        ledger.close()

    typer.echo()
    typer.echo(render(informe))
    typer.echo()
    typer.secho(
        f"  tokens locales {totales.get('local_tokens', 0):,}  |  remotos {totales.get('remote_tokens', 0):,}"
        f"  |  corrida {run.run_id}",
        fg=typer.colors.BRIGHT_BLACK,
    )


@correo_app.command("borrador")
def borrador(
    id_mensaje: Annotated[str, typer.Argument(help="Mensaje a responder, como aparece en `ver`.")],
    instruccion: Annotated[str, typer.Option(help="Que quieres responder, en tus palabras.")] = "",
    carpeta: Annotated[str, typer.Option(help="Carpeta si el id es solo un numero.")] = "INBOX",
    remoto: Annotated[bool, typer.Option("--remoto", help="Redacta el modelo remoto (gasta tokens).")] = False,
    si: Annotated[bool, typer.Option("--yes", "-y", help="Guarda sin preguntar.")] = False,
    db: Annotated[Path, typer.Option(help="Ruta del ledger.")] = _DB,
) -> None:
    """Propone una respuesta y la deja como archivo .eml. lymi no envia correo: lo envias tu."""
    from lymi.bench.wiring import proveedores
    from lymi.correo import preparar, redactar
    from lymi.ejecutor import (
        CapacidadDenegada,
        Diario,
        Ejecutor,
        EjecutorError,
        cargar_perfil,
        raiz_diario,
    )

    if ":" in id_mensaje:
        carpeta, _, numero = id_mensaje.rpartition(":")
    else:
        numero = id_mensaje
    if not numero.isdigit():
        typer.secho("  el id es carpeta:numero, o un numero con --carpeta", fg=typer.colors.RED)
        raise typer.Exit(1)

    local, etiqueta_local, cliente_remoto, etiqueta_remota = proveedores()
    cliente = cliente_remoto if remoto else local
    if cliente is None:
        typer.secho(f"  no hay modelo {'remoto' if remoto else 'local'}: corre `lymi setup`", fg=typer.colors.RED)
        raise typer.Exit(1)
    typer.secho(f"  redacta: {etiqueta_remota if remoto else etiqueta_local}", fg=typer.colors.CYAN, err=True)

    with _buzon() as buzon:
        try:
            mensaje = buzon.leer(carpeta, int(numero))
        except CorreoError as exc:
            typer.secho(f"  {exc}", fg=typer.colors.RED)
            raise typer.Exit(1) from None
        mias = sorted(buzon.direcciones())

    ledger = Ledger(db)
    try:
        with ledger.run("correo", "borrador", cliente.billing) as run:
            rec = Recorder(run)

            async def completar(sistema: str, texto: str) -> str:
                enviados, sistema_final, redactor = rec.preparar(cliente, [Message("user", texto)], sistema)
                completion = await asyncio.to_thread(
                    cliente.complete, enviados, system=sistema_final, max_tokens=1200
                )
                if redactor is not None:
                    completion.text = redactor.rehidratar(completion.text)
                rec.registrar(
                    completion, enviados, purpose="correo:borrador", system=sistema_final,
                    redacciones=redactor.total if redactor is not None else 0,
                )
                return completion.text

            cuerpo = asyncio.run(redactar(mensaje, completar, instruccion))
    finally:
        ledger.close()

    if not cuerpo:
        typer.secho("  el modelo no escribio nada utilizable", fg=typer.colors.YELLOW)
        raise typer.Exit(1)
    propuesta = preparar(mensaje, cuerpo, de=mias[0] if mias else "")
    ruta = f"salidas/respuesta-{int(numero)}.eml"

    typer.echo()
    typer.secho(f"  Para: {propuesta.para}", bold=True)
    typer.echo(f"  Asunto: {propuesta.asunto}\n")
    for linea in propuesta.cuerpo.splitlines():
        typer.echo(f"    {linea}")
    typer.echo()
    if not si and not typer.confirm(f"  ¿Guardar como {ruta}?", default=False):
        typer.secho("  no se guardo nada", fg=typer.colors.YELLOW)
        raise typer.Exit(1)

    base = Path.cwd()
    ejecutor = Ejecutor(
        cargar_perfil(base / "ejecutor.yml", base), Diario(raiz_diario() / "borradores"), base=base
    )
    try:
        escrito = ejecutor.escribir(ruta, propuesta.como_eml().decode("utf-8"))
    except (CapacidadDenegada, EjecutorError, OSError) as exc:
        typer.secho(f"  {exc}", fg=typer.colors.RED)
        raise typer.Exit(1) from None
    typer.secho(f"  {escrito['ruta']}", fg=typer.colors.GREEN)
    typer.secho(
        "  Abrelo con doble clic en Thunderbird, revisalo y envialo tu. lymi no envia correo.",
        fg=typer.colors.BRIGHT_BLACK,
    )
