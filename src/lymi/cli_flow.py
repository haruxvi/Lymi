"""Subcomandos `lymi flow`: validar, planificar y correr workflows."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from lymi.flows.aprobaciones import (
    Decision,
    MemoriaAprobaciones,
    Politica,
    ReglaError,
    Solicitud,
    cargar_politica,
)
from lymi.flows.engine import EntradaError, correr
from lymi.flows.plan import planificar, resumir
from lymi.flows.schema import Workflow, WorkflowError, cargar
from lymi.ledger import Ledger

flow_app = typer.Typer(
    help="Workflows declarativos: validar, planificar y correr.",
    no_args_is_help=True,
    add_completion=False,
)

_COLOR_COSTO = {
    "gratis": typer.colors.GREEN,
    "tokens remotos": typer.colors.YELLOW,
    "externo": typer.colors.CYAN,
}
_ESTADOS = {
    "ok": ("+", typer.colors.GREEN),
    "omitido": ("-", typer.colors.BRIGHT_BLACK),
    "rechazado": ("x", typer.colors.YELLOW),
    "fallo": ("!", typer.colors.RED),
}


def _cargar(archivo: Path) -> Workflow:
    try:
        return cargar(archivo)
    except WorkflowError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1) from None


def _entradas(pares: list[str]) -> dict[str, str]:
    """Convierte `clave=valor` y `clave=@archivo` en un diccionario."""
    valores: dict[str, str] = {}
    for par in pares:
        clave, separador, valor = par.partition("=")
        if not separador or not clave:
            typer.secho(f"entrada invalida {par!r}: usa clave=valor o clave=@archivo", fg=typer.colors.RED)
            raise typer.Exit(1)
        if valor.startswith("@"):
            ruta = Path(valor[1:])
            try:
                valor = ruta.read_text(encoding="utf-8")
            except OSError as exc:
                typer.secho(f"no se pudo leer {ruta}: {exc}", fg=typer.colors.RED)
                raise typer.Exit(1) from None
        valores[clave] = valor
    return valores


@flow_app.command("validate")
def validar(archivo: Annotated[Path, typer.Argument(help="Workflow YAML.")]) -> None:
    """Comprueba el workflow sin ejecutar nada."""
    flujo = _cargar(archivo)
    typer.secho(f"  {flujo.name}: valido, {len(flujo.steps)} pasos", fg=typer.colors.GREEN)


@flow_app.command("plan")
def plan(archivo: Annotated[Path, typer.Argument(help="Workflow YAML.")]) -> None:
    """Muestra que haria el workflow, sin gastar un token."""
    flujo = _cargar(archivo)
    filas = planificar(flujo)
    resumen = resumir(filas)

    typer.echo()
    typer.secho(f"  {flujo.name}", bold=True)
    if flujo.description:
        typer.echo(f"  {flujo.description}")
    typer.echo()

    for fila in filas:
        costo = typer.style(f"{fila.costo:<16}", fg=_COLOR_COSTO.get(fila.costo))
        aprobacion = typer.style("  pide aprobacion", fg=typer.colors.RED, bold=True) if fila.efectos else ""
        typer.echo(f"  {fila.id:<14}{fila.tipo:<11}{costo}{fila.destino}{aprobacion}")
        if fila.condicion:
            typer.secho(f"  {'':<25}solo si {fila.condicion}", fg=typer.colors.BRIGHT_BLACK)

    typer.echo()
    typer.echo(
        f"  {resumen.total} pasos: {resumen.gratis} gratis, {resumen.remotos} con tokens remotos, "
        f"{resumen.externos} externos, {resumen.con_efectos} piden aprobacion"
    )


@flow_app.command("run")
def run(
    archivo: Annotated[Path, typer.Argument(help="Workflow YAML.")],
    entrada: Annotated[
        list[str] | None, typer.Option("--input", "-i", help="clave=valor o clave=@archivo")
    ] = None,
    si: Annotated[
        bool, typer.Option("--yes", "-y", help="Aprueba lo que ninguna regla rechace, sin preguntar.")
    ] = False,
    politica_ruta: Annotated[
        Path | None, typer.Option("--politica", help="YAML con reglas de aprobacion por paso, destino y metodo.")
    ] = None,
    vencimiento: Annotated[
        float | None, typer.Option("--vencimiento", help="Segundos para aprobar cada efecto; al vencer se rechaza.")
    ] = None,
    memoria_db: Annotated[
        Path, typer.Option("--memoria-aprobaciones", help="Decisiones 'siempre para este destino'.")
    ] = Path("runs/aprobaciones.sqlite3"),
    db: Annotated[Path, typer.Option(help="Ruta del ledger.")] = Path("runs/lymi.sqlite3"),
) -> None:
    """Ejecuta el workflow. Cada efecto pide aprobacion salvo con --yes."""
    from lymi.bench.wiring import proveedores

    flujo = _cargar(archivo)
    valores = _entradas(entrada or [])

    local, etiqueta_local, remoto, etiqueta_remota = proveedores()
    typer.secho(
        f"  local: {etiqueta_local or 'no disponible'}  |  remoto: {etiqueta_remota or 'no disponible'}",
        fg=typer.colors.CYAN,
    )

    memoria = MemoriaAprobaciones(memoria_db)
    try:
        politica = cargar_politica(politica_ruta, memoria) if politica_ruta else Politica(memoria=memoria)
    except ReglaError as exc:
        typer.secho(f"  {exc}", fg=typer.colors.RED)
        raise typer.Exit(1) from None

    def aprobar(paso_id: str, vista: str, solicitud: Solicitud) -> bool:
        # Las reglas de la politica ya se evaluaron antes de llegar aqui: --yes nunca
        # salta una regla que rechaza.
        if si:
            return True
        typer.echo()
        typer.secho(f"  {paso_id} quiere ejecutar:", fg=typer.colors.YELLOW, bold=True)
        for linea in vista.splitlines():
            typer.echo(f"    {linea}")
        metodo = f" {solicitud.metodo}" if solicitud.metodo else ""
        typer.echo(f"    destino: {solicitud.destino}{metodo}")
        respuesta = typer.prompt("  ¿Aprobar? [s]i / [n]o / [a] siempre para este destino", default="n")
        respuesta = respuesta.strip().lower()
        if respuesta in {"a", "siempre"}:
            try:
                hasta = memoria.recordar(solicitud.destino, solicitud.metodo, Decision.APROBAR)
            except ReglaError as exc:
                typer.secho(f"  aprobado solo esta vez: {exc}", fg=typer.colors.YELLOW)
                return True
            typer.secho(f"  recordado hasta {hasta:%Y-%m-%d}", fg=typer.colors.GREEN)
            return True
        return respuesta in {"s", "si", "sí", "y", "yes"}

    ledger = Ledger(db)
    try:
        resultado = correr(
            flujo, valores, ledger=ledger, local=local, remote=remoto,
            aprobar=aprobar, politica=politica, tiempo_aprobacion=vencimiento,
        )
        totales = ledger.totals(resultado.run_id) or {}
    except EntradaError as exc:
        typer.secho(f"  {exc}", fg=typer.colors.RED)
        raise typer.Exit(1) from None
    finally:
        ledger.close()

    typer.echo()
    for estado in resultado.pasos:
        simbolo, color = _ESTADOS[estado.status]
        marca = typer.style(f"[{simbolo}]", fg=color, bold=True)
        detalle = f"  {estado.detalle}" if estado.detalle else ""
        typer.echo(f"  {marca} {estado.id:<14}{estado.status:<10}{detalle}")

    typer.echo()
    typer.echo(
        f"  tokens remotos {totales.get('remote_tokens', 0):,}  |  locales {totales.get('local_tokens', 0):,}"
        f"  |  llamadas que salieron de la maquina {totales.get('egress_calls', 0)}"
    )
    typer.secho(f"  corrida {resultado.run_id}  (lymi ledger)", fg=typer.colors.BRIGHT_BLACK)

    if not resultado.ok:
        raise typer.Exit(1)
