"""Subcomandos `lymi agencia`: validar, ver el organigrama y correr una tarea."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

import typer

from lymi.agencia import HERRAMIENTAS, AgenciaError, arbol, cargar_agencia, correr_agencia
from lymi.agencia.definicion import Agencia
from lymi.control import Detenido, PresupuestoAgotado
from lymi.flows.aprobaciones import (
    MemoriaAprobaciones,
    Politica,
    ReglaError,
    Solicitud,
    cargar_politica,
)
from lymi.ledger import Ledger
from lymi.privacidad import EgressBloqueado

agencia_app = typer.Typer(
    help="Departamentos de agentes que derivan tareas y crean ayudantes, con topes duros.",
    no_args_is_help=True,
    add_completion=False,
)

_ESTADOS = {
    "hecha": typer.colors.GREEN,
    "fallida": typer.colors.RED,
    "cancelada": typer.colors.YELLOW,
}


def _cargar(archivo: Path) -> Agencia:
    try:
        return cargar_agencia(archivo)
    except AgenciaError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1) from None


@agencia_app.command("validar")
def validar(archivo: Annotated[Path, typer.Argument(help="Agencia YAML.")]) -> None:
    """Comprueba la agencia sin ejecutar nada."""
    agencia = _cargar(archivo)
    typer.secho(
        f"  {agencia.name}: valida, {len(agencia.departamentos)} departamentos, {len(agencia.agentes())} agentes",
        fg=typer.colors.GREEN,
    )


@agencia_app.command("plan")
def plan(archivo: Annotated[Path, typer.Argument(help="Agencia YAML.")]) -> None:
    """El organigrama, quien puede pedirle trabajo a quien y los topes duros."""
    agencia = _cargar(archivo)
    typer.echo()
    typer.secho(f"  {agencia.name}", bold=True)
    if agencia.description:
        typer.echo(f"  {agencia.description.strip()}")
    for nombre_dep, dep in agencia.departamentos.items():
        typer.echo()
        typer.secho(f"  {nombre_dep}", bold=True, nl=False)
        typer.echo(f"  {dep.descripcion}" if dep.descripcion else "")
        for nombre_ag, agente in dep.agentes.items():
            completo = f"{nombre_dep}.{nombre_ag}"
            lider = "  (lider)" if nombre_ag == dep.jefe else ""
            tier = typer.style(agente.tier, fg=typer.colors.YELLOW if agente.tier == "remote" else typer.colors.GREEN)
            typer.echo(f"    {nombre_ag}{lider}  [{tier}]  {agente.descripcion}")
            for h in agente.herramientas:
                efectos = HERRAMIENTAS.get(h, (False, ""))[0] or h.startswith("workflow:")
                marca = typer.style("  pide aprobacion", fg=typer.colors.RED) if efectos else ""
                typer.echo(f"      usa {h}{marca}")
            for d in sorted(agencia.destinos(completo)):
                typer.echo(f"      delega a {d}")
            if agente.puede_crear:
                typer.echo("      crea ayudantes (con parte de sus herramientas, sin delegar)")
    lim = agencia.limites
    peor = min(lim.llamadas, lim.agentes_totales * lim.turnos_por_agente)
    typer.echo()
    typer.secho("  topes duros de cada corrida", bold=True)
    typer.echo(
        f"    profundidad {lim.profundidad}  |  agentes {lim.agentes_totales}  |  a la vez {lim.simultaneos}"
        f"  |  turnos por agente {lim.turnos_por_agente}"
    )
    tokens = f"{lim.tokens_remotos:,}" if lim.tokens_remotos else "sin tope (fija `tokens_remotos`)"
    typer.echo(f"    llamadas {lim.llamadas} (peor caso real: {peor})  |  tokens remotos {tokens}  |  {lim.segundos:g} s")


@agencia_app.command("evaluar")
def evaluar_cmd(
    modelo: Annotated[
        list[str] | None, typer.Option("--modelo", help="Modelo local de Ollama a evaluar; repetible.")
    ] = None,
    remoto: Annotated[bool, typer.Option("--remoto", help="Evalua tambien el modelo remoto (gasta tokens).")] = False,
    n: Annotated[int, typer.Option("-n", min=1, max=30, help="Preguntas.")] = 5,
    raiz: Annotated[Path, typer.Option(help="Repositorio del que salen las preguntas.")] = Path("."),
    db: Annotated[Path, typer.Option(help="Ruta del ledger.")] = Path("runs/lymi.sqlite3"),
) -> None:
    """Que modelo sirve como agente: preguntas del codigo corregidas contra el indice, sin juez."""
    from lymi.bench.agentes import evaluar, preguntas
    from lymi.bench.wiring import proveedores
    from lymi.providers.local import OllamaClient

    lista = preguntas(raiz, n)
    if not lista:
        typer.secho("  no hay funciones con llamadores confirmados para preguntar", fg=typer.colors.RED)
        raise typer.Exit(1)
    candidatos: list[tuple[str, str, object]] = [(m, "local", OllamaClient(model=m)) for m in (modelo or [])]
    if remoto:
        _, _, cliente_remoto, etiqueta = proveedores()
        if cliente_remoto is None:
            typer.secho("  no hay modelo remoto: corre `lymi setup`", fg=typer.colors.RED)
            raise typer.Exit(1)
        candidatos.append((etiqueta or "remoto", "remote", cliente_remoto))
    if not candidatos:
        typer.secho("  indica --modelo <ollama> y/o --remoto", fg=typer.colors.YELLOW)
        raise typer.Exit(1)

    typer.echo(f"\n  {len(lista)} preguntas de {raiz.resolve().name}:")
    for p in lista:
        typer.echo(f"    {p.simbolo}  ({p.ruta}:{p.linea}, {len(p.llamadores)} llamadores)")
    filas = []
    ledger = Ledger(db)
    try:
        for nombre, tier, cliente in candidatos:
            typer.echo()
            typer.secho(f"  {nombre}", bold=True)

            def mostrar(r) -> None:
                marca = typer.style("ok " if r.aprobada else "no ", fg=typer.colors.GREEN if r.aprobada else typer.colors.RED)
                typer.echo(f"    {marca} {r.pregunta.simbolo:<40} {r.segundos:5.0f} s  {r.motivo}")

            try:
                respuestas = asyncio.run(evaluar(cliente, tier, lista, ledger=ledger, al_responder=mostrar))
            except (Detenido, PresupuestoAgotado) as exc:
                typer.secho(f"    {exc}", fg=typer.colors.RED)
                break
            filas.append((nombre, respuestas))
    finally:
        ledger.close()

    typer.echo()
    typer.secho(f"  {'modelo':<32}{'aciertos':>10}{'inventa citas':>15}{'turnos':>8}{'tokens':>12}{'s/preg':>8}",
                bold=True)
    for nombre, respuestas in filas:
        total = len(respuestas)
        aciertos = sum(r.aprobada for r in respuestas)
        inventa = sum(bool(r.sin_respaldo) for r in respuestas)
        turnos = sum(r.turnos for r in respuestas) / total
        tokens = sum(r.tokens_locales + r.tokens_remotos for r in respuestas) / total
        segundos = sum(r.segundos for r in respuestas) / total
        typer.echo(f"  {nombre:<32}{f'{aciertos}/{total}':>10}{f'{inventa}/{total}':>15}{turnos:>8.1f}"
                   f"{tokens:>12,.0f}{segundos:>8.0f}")
    typer.secho("  tokens por pregunta; las corridas quedan en el ledger (lymi ledger)", fg=typer.colors.BRIGHT_BLACK)


@agencia_app.command("correr")
def correr(
    archivo: Annotated[Path, typer.Argument(help="Agencia YAML.")],
    tarea: Annotated[str, typer.Argument(help="La tarea. `@departamento ...` la dirige.")],
    agente: Annotated[str | None, typer.Option(help="departamento, departamento.agente o agente.")] = None,
    si: Annotated[bool, typer.Option("--yes", "-y", help="Aprueba lo que ninguna regla rechace.")] = False,
    politica_ruta: Annotated[Path | None, typer.Option("--politica", help="Reglas de aprobacion.")] = None,
    vencimiento: Annotated[float | None, typer.Option(help="Segundos para aprobar cada efecto.")] = None,
    db: Annotated[Path, typer.Option(help="Ruta del ledger.")] = Path("runs/lymi.sqlite3"),
) -> None:
    """Entrega una tarea a la agencia. Cada efecto de un agente pide aprobacion salvo con --yes."""
    from lymi.bench.wiring import proveedores

    agencia = _cargar(archivo)
    local, etiqueta_local, remoto, etiqueta_remota = proveedores()
    typer.secho(
        f"  local: {etiqueta_local or 'no disponible'}  |  remoto: {etiqueta_remota or 'no disponible'}",
        fg=typer.colors.CYAN,
    )
    try:
        politica = cargar_politica(politica_ruta, MemoriaAprobaciones("runs/aprobaciones.sqlite3")) \
            if politica_ruta else None
    except ReglaError as exc:
        typer.secho(f"  {exc}", fg=typer.colors.RED)
        raise typer.Exit(1) from None

    def aprobar(paso_id: str, vista: str, solicitud: Solicitud) -> bool:
        if si:
            return True
        typer.echo()
        for linea in vista.splitlines():
            typer.echo(f"    {linea}")
        respuesta = typer.prompt("  ¿Aprobar? [s]i / [n]o", default="n")
        return respuesta.strip().lower() in {"s", "si", "sí", "y", "yes"}

    ledger = Ledger(db)
    try:
        resultado = asyncio.run(correr_agencia(
            agencia, tarea, ledger=ledger, local=local, remote=remoto, agente=agente,
            aprobar=aprobar, politica=politica or Politica(), tiempo_aprobacion=vencimiento,
        ))
        totales = ledger.totals(resultado.run_id) or {}
    except (ValueError, Detenido, PresupuestoAgotado, EgressBloqueado) as exc:
        typer.secho(f"  {exc}", fg=typer.colors.RED)
        raise typer.Exit(1) from None
    finally:
        ledger.close()

    typer.echo()
    typer.secho(f"  recibe {resultado.agente} ({resultado.motivo_ruta})", fg=typer.colors.BRIGHT_BLACK)
    for linea in arbol(resultado.tareas):
        estado = next((e for e in _ESTADOS if f"  {e}" in linea), None)
        typer.secho(f"  {linea}", fg=_ESTADOS.get(estado) if estado else None)
    typer.echo()
    if resultado.ok:
        typer.echo(resultado.resultado or "")
    else:
        typer.secho(f"  la agencia no termino: {resultado.detalle}", fg=typer.colors.RED)
    typer.echo()
    typer.echo(
        f"  {len(resultado.tareas)} tareas, hasta {resultado.max_simultaneos} a la vez  |  tokens remotos "
        f"{totales.get('remote_tokens', 0):,}  |  locales {totales.get('local_tokens', 0):,}"
        f"  |  salieron de la maquina {totales.get('egress_calls', 0)}"
    )
    typer.secho(f"  corrida {resultado.run_id}  (traza en runs/agencia/{resultado.run_id}.jsonl)",
                fg=typer.colors.BRIGHT_BLACK)
    if not resultado.ok:
        raise typer.Exit(1)
