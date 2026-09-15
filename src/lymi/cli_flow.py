"""Subcomandos `lymi flow`: validar, planificar y correr workflows."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from lymi.control import Presupuesto
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
from lymi.privacidad.etiquetas import (
    EtiquetaError,
    Etiquetas,
    Nivel,
    cargar_etiquetas,
    fragmentos_protegidos,
)

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
    return _entradas_etiquetadas(pares, Etiquetas())[0]


def _entradas_etiquetadas(
    pares: list[str], etiquetas: Etiquetas
) -> tuple[dict[str, str], tuple[str, ...], list[str]]:
    """Como `_entradas`, mas lo que no puede salir y los avisos para mostrar.

    Devuelve (valores, fragmentos protegidos, avisos). Solo los archivos tienen
    etiqueta: un valor escrito a mano en la terminal no viene de ninguna ruta.
    """
    valores: dict[str, str] = {}
    protegidos: list[str] = []
    avisos: list[str] = []
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
            nivel = etiquetas.nivel_de(ruta)
            if nivel is Nivel.NUNCA_SALE:
                protegidos.extend(fragmentos_protegidos(valor))
                avisos.append(
                    f"{clave}: {ruta} es nunca-sale; su texto no llegara a ningun proveedor remoto ni integracion"
                )
        valores[clave] = valor
    return valores, tuple(protegidos), avisos


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
    max_tokens_remotos: Annotated[
        int | None, typer.Option(min=1, help="Tope de tokens remotos; al alcanzarlo no empieza otro paso.")
    ] = None,
    max_llamadas: Annotated[int | None, typer.Option(min=1, help="Tope de llamadas a modelos.")] = None,
    sensibilidad: Annotated[
        Path, typer.Option(help="Reglas de sensibilidad por ruta para los archivos de entrada.")
    ] = Path("sensibilidad.yml"),
    db: Annotated[Path, typer.Option(help="Ruta del ledger.")] = Path("runs/lymi.sqlite3"),
) -> None:
    """Ejecuta el workflow. Cada efecto pide aprobacion salvo con --yes."""
    from lymi.bench.wiring import proveedores

    flujo = _cargar(archivo)
    try:
        etiquetas = cargar_etiquetas(sensibilidad)
    except EtiquetaError as exc:
        typer.secho(f"  {exc}", fg=typer.colors.RED)
        raise typer.Exit(1) from None
    valores, protegidos, avisos = _entradas_etiquetadas(entrada or [], etiquetas)
    for aviso in avisos:
        typer.secho(f"  {aviso}", fg=typer.colors.MAGENTA)

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
            presupuesto=Presupuesto(max_tokens_remotos, max_llamadas)
            if max_tokens_remotos or max_llamadas
            else None,
            protegidos=protegidos,
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


aprobaciones_app = typer.Typer(
    help="Decisiones recordadas con 'siempre para este destino'.",
    no_args_is_help=True,
    add_completion=False,
)
flow_app.add_typer(aprobaciones_app, name="approvals")

_MEMORIA_POR_DEFECTO = Path("runs/aprobaciones.sqlite3")


@aprobaciones_app.command("list")
def listar_aprobaciones(
    memoria_db: Annotated[
        Path, typer.Option("--memoria-aprobaciones", help="Ruta de las decisiones recordadas.")
    ] = _MEMORIA_POR_DEFECTO,
) -> None:
    """Lista las decisiones vigentes. Las vencidas no se muestran: ya no deciden nada."""
    from datetime import UTC, datetime

    ahora = datetime.now(UTC)
    vigentes = [
        f for f in MemoriaAprobaciones(memoria_db).listar() if datetime.fromisoformat(f["hasta"]) > ahora
    ]
    if not vigentes:
        typer.echo("  No hay decisiones recordadas.")
        return
    for f in vigentes:
        metodo = f["metodo"] or "*"
        typer.echo(f"  {f['decision']:<10}{f['destino']:<40}{metodo:<8}hasta {f['hasta'][:10]}")


@aprobaciones_app.command("forget")
def olvidar_aprobacion(
    destino: Annotated[str, typer.Argument(help="Destino recordado, ej. hooks.slack.com")],
    metodo: Annotated[str | None, typer.Option(help="Solo este metodo HTTP.")] = None,
    memoria_db: Annotated[
        Path, typer.Option("--memoria-aprobaciones", help="Ruta de las decisiones recordadas.")
    ] = _MEMORIA_POR_DEFECTO,
) -> None:
    """Olvida las decisiones de un destino: la proxima vez se vuelve a preguntar."""
    olvidadas = MemoriaAprobaciones(memoria_db).olvidar(destino, metodo)
    if not olvidadas:
        typer.secho(f"  No habia decisiones recordadas para {destino}.", fg=typer.colors.YELLOW)
        raise typer.Exit(1)
    typer.secho(f"  olvidadas {olvidadas} decisiones para {destino}", fg=typer.colors.GREEN)
