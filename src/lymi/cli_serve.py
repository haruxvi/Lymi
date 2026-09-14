"""Subcomandos `lymi schedule`, `lymi hooks` y `lymi serve`."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from lymi.cli_flow import _entradas as parsear_entradas
from lymi.triggers.agenda import Agenda, AgendaError
from lymi.triggers.cron import zona_horaria
from lymi.triggers.ganchos import GanchoError, Ganchos

DB_LEDGER = Path("runs/lymi.sqlite3")
DB_AGENDA = Path("runs/agenda.sqlite3")
DB_GANCHOS = Path("runs/ganchos.sqlite3")

schedule_app = typer.Typer(help="Workflows programados con cron.", no_args_is_help=True, add_completion=False)
hooks_app = typer.Typer(help="Webhooks entrantes que disparan workflows.", no_args_is_help=True, add_completion=False)


def _fallar(mensaje: str) -> typer.Exit:
    typer.secho(f"  {mensaje}", fg=typer.colors.RED)
    return typer.Exit(1)


# ---------------------------------------------------------------- schedule


@schedule_app.command("add")
def programar(
    workflow: Annotated[Path, typer.Argument(help="Workflow YAML.")],
    cron: Annotated[str, typer.Argument(help='Expresion cron, ej. "0 9 * * mon-fri" o @daily.')],
    zona: Annotated[str, typer.Option(help="Zona horaria IANA, ej. America/Santiago.")] = "UTC",
    entrada: Annotated[list[str] | None, typer.Option("--input", "-i", help="clave=valor o clave=@archivo")] = None,
    aprobar: Annotated[
        list[str] | None, typer.Option("--aprobar", help="Paso con efectos autorizado a correr sin nadie delante.")
    ] = None,
    db: Annotated[Path, typer.Option(help="Ruta de la agenda.")] = DB_AGENDA,
) -> None:
    """Programa un workflow. Todo se valida ahora, no a la hora de correr."""
    agenda = Agenda(db)
    try:
        prog = agenda.agregar(
            workflow, cron, zona=zona, entradas=parsear_entradas(entrada or []), aprobados=aprobar or []
        )
        sin_autorizar = agenda.efectos_sin_autorizar(prog)
    except AgendaError as exc:
        raise _fallar(str(exc)) from None
    finally:
        agenda.close()

    proxima = prog.proxima.astimezone(zona_horaria(prog.zona)).strftime("%Y-%m-%d %H:%M")
    typer.secho(f"  programado {prog.id}: proxima ejecucion {proxima} ({prog.zona})", fg=typer.colors.GREEN)
    if sin_autorizar:
        typer.secho(
            f"  Estos pasos con efectos se rechazaran al correr sin nadie delante: {', '.join(sin_autorizar)}."
            " Preapruebalos con --aprobar si corresponde.",
            fg=typer.colors.YELLOW,
        )
    typer.echo("  Las programaciones corren mientras `lymi serve` este activo.")


@schedule_app.command("list")
def listar_programaciones(db: Annotated[Path, typer.Option(help="Ruta de la agenda.")] = DB_AGENDA) -> None:
    """Lista las programaciones."""
    agenda = Agenda(db)
    try:
        programaciones = agenda.listar()
    finally:
        agenda.close()

    if not programaciones:
        typer.echo("  No hay programaciones. Crea una con: lymi schedule add <workflow> <cron>")
        return
    for p in programaciones:
        tz = zona_horaria(p.zona)
        proxima = p.proxima.astimezone(tz).strftime("%Y-%m-%d %H:%M")
        ultima = p.ultima.astimezone(tz).strftime("%Y-%m-%d %H:%M") if p.ultima else "nunca"
        estado = "activa" if p.activo else "pausada"
        typer.echo(f"  {p.id}  {p.workflow.name:<24}{p.cron:<18}{estado:<9}proxima {proxima}  ultima {ultima}  ({p.zona})")


@schedule_app.command("remove")
def quitar_programacion(
    id_: Annotated[str, typer.Argument(metavar="ID", help="Id de la programacion.")],
    db: Annotated[Path, typer.Option(help="Ruta de la agenda.")] = DB_AGENDA,
) -> None:
    """Elimina una programacion."""
    agenda = Agenda(db)
    try:
        agenda.quitar(id_)
    except AgendaError as exc:
        raise _fallar(str(exc)) from None
    finally:
        agenda.close()
    typer.secho(f"  eliminada {id_}", fg=typer.colors.GREEN)


@schedule_app.command("pause")
def pausar(
    id_: Annotated[str, typer.Argument(metavar="ID", help="Id de la programacion.")],
    db: Annotated[Path, typer.Option(help="Ruta de la agenda.")] = DB_AGENDA,
) -> None:
    """Pausa una programacion sin borrarla."""
    agenda = Agenda(db)
    try:
        agenda.pausar(id_)
    except AgendaError as exc:
        raise _fallar(str(exc)) from None
    finally:
        agenda.close()
    typer.secho(f"  pausada {id_}", fg=typer.colors.GREEN)


@schedule_app.command("resume")
def reanudar(
    id_: Annotated[str, typer.Argument(metavar="ID", help="Id de la programacion.")],
    db: Annotated[Path, typer.Option(help="Ruta de la agenda.")] = DB_AGENDA,
) -> None:
    """Reanuda una programacion. La siguiente ejecucion se calcula desde ahora."""
    agenda = Agenda(db)
    try:
        prog = agenda.reanudar(id_)
    except AgendaError as exc:
        raise _fallar(str(exc)) from None
    finally:
        agenda.close()
    proxima = prog.proxima.astimezone(zona_horaria(prog.zona)).strftime("%Y-%m-%d %H:%M")
    typer.secho(f"  reanudada {id_}: proxima ejecucion {proxima} ({prog.zona})", fg=typer.colors.GREEN)


# ---------------------------------------------------------------- hooks


@hooks_app.command("add")
def crear_gancho(
    nombre: Annotated[str, typer.Argument(help="Nombre del webhook; forma parte de la URL.")],
    workflow: Annotated[Path, typer.Argument(help="Workflow que dispara.")],
    github: Annotated[bool, typer.Option("--github", help="Firma de GitHub (X-Hub-Signature-256).")] = False,
    aprobar: Annotated[
        list[str] | None, typer.Option("--aprobar", help="Paso con efectos autorizado a correr sin nadie delante.")
    ] = None,
    db: Annotated[Path, typer.Option(help="Ruta del registro de webhooks.")] = DB_GANCHOS,
) -> None:
    """Crea un webhook. El secreto se muestra una sola vez."""
    ganchos = Ganchos(db)
    try:
        gancho, secreto = ganchos.crear(nombre, workflow, esquema="github" if github else "lymi", aprobados=aprobar or [])
    except GanchoError as exc:
        raise _fallar(str(exc)) from None
    finally:
        ganchos.close()

    typer.secho(f"  webhook creado: POST /hooks/{gancho.nombre}", fg=typer.colors.GREEN)
    typer.echo()
    typer.secho("  Secreto (se muestra una sola vez; configuralo en quien envia el webhook):", bold=True)
    typer.echo(f"  {secreto}")
    typer.echo()
    if gancho.esquema == "github":
        typer.echo("  Pegalo como Secret del webhook en GitHub, con Content type application/json.")
    else:
        typer.echo("  Cada peticion debe traer la cabecera:")
        typer.echo("    X-Lymi-Signature: t=<unix>,v1=<hex de HMAC-SHA256(secreto, '<unix>.' + cuerpo)>")


@hooks_app.command("list")
def listar_ganchos(db: Annotated[Path, typer.Option(help="Ruta del registro de webhooks.")] = DB_GANCHOS) -> None:
    """Lista los webhooks. Nunca muestra secretos."""
    ganchos = Ganchos(db)
    try:
        lista = ganchos.listar()
    finally:
        ganchos.close()
    if not lista:
        typer.echo("  No hay webhooks. Crea uno con: lymi hooks add <nombre> <workflow>")
        return
    for g in lista:
        estado = "activo" if g.activo else "inactivo"
        aprobados = ", ".join(sorted(g.aprobados)) or "ninguno"
        typer.echo(f"  {g.nombre:<20}{g.esquema:<8}{estado:<10}{g.workflow.name}  preaprobados: {aprobados}")


@hooks_app.command("rotate")
def rotar_gancho(
    nombre: Annotated[str, typer.Argument(help="Nombre del webhook.")],
    db: Annotated[Path, typer.Option(help="Ruta del registro de webhooks.")] = DB_GANCHOS,
) -> None:
    """Reemplaza el secreto. El anterior deja de servir al instante."""
    ganchos = Ganchos(db)
    try:
        secreto = ganchos.rotar(nombre)
    except GanchoError as exc:
        raise _fallar(str(exc)) from None
    finally:
        ganchos.close()
    typer.secho(f"  secreto de {nombre} rotado. El nuevo (se muestra una sola vez):", fg=typer.colors.GREEN)
    typer.echo(f"  {secreto}")


@hooks_app.command("remove")
def quitar_gancho(
    nombre: Annotated[str, typer.Argument(help="Nombre del webhook.")],
    db: Annotated[Path, typer.Option(help="Ruta del registro de webhooks.")] = DB_GANCHOS,
) -> None:
    """Elimina un webhook y su secreto."""
    ganchos = Ganchos(db)
    try:
        ganchos.quitar(nombre)
    except GanchoError as exc:
        raise _fallar(str(exc)) from None
    finally:
        ganchos.close()
    typer.secho(f"  eliminado {nombre}", fg=typer.colors.GREEN)


# ---------------------------------------------------------------- serve


def servir(
    host: Annotated[str, typer.Option(help="Interfaz de escucha.")] = "127.0.0.1",
    puerto: Annotated[int, typer.Option(help="Puerto.")] = 8765,
    intervalo: Annotated[float, typer.Option(help="Segundos entre revisiones de la agenda.")] = 20.0,
    max_corridas: Annotated[int, typer.Option(help="Corridas simultaneas maximas.")] = 4,
    ledger: Annotated[Path, typer.Option(help="Ruta del ledger.")] = DB_LEDGER,
    agenda: Annotated[Path, typer.Option(help="Ruta de la agenda.")] = DB_AGENDA,
    ganchos: Annotated[Path, typer.Option(help="Ruta del registro de webhooks.")] = DB_GANCHOS,
) -> None:
    """Corre la agenda y recibe webhooks. Solo escucha en esta maquina salvo que indiques otra cosa."""
    import uvicorn

    from lymi.bench.wiring import proveedores
    from lymi.triggers.servidor import ConfigServidor, crear_app

    if host not in {"127.0.0.1", "localhost", "::1"}:
        typer.secho(
            "  Atencion: lymi queda expuesto fuera de esta maquina. Ponle delante un proxy con TLS.",
            fg=typer.colors.RED,
            bold=True,
        )

    local, etiqueta_local, remoto, etiqueta_remota = proveedores()
    typer.secho(
        f"  local: {etiqueta_local or 'no disponible'}  |  remoto: {etiqueta_remota or 'no disponible'}",
        fg=typer.colors.CYAN,
    )
    typer.echo(f"  webhooks en http://{host}:{puerto}/hooks/<nombre>  |  agenda cada {intervalo:g} s")

    app = crear_app(
        ConfigServidor(
            ledger=ledger,
            agenda=agenda,
            ganchos=ganchos,
            max_corridas=max_corridas,
            intervalo_agenda=intervalo,
            local=local,
            remote=remoto,
        )
    )
    uvicorn.run(app, host=host, port=puerto, log_level="info")
