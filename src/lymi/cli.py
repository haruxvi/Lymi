"""Interfaz de linea de comandos de lymi."""

from __future__ import annotations

import sys
import webbrowser
from pathlib import Path
from typing import Annotated

import typer

from lymi.bench.demo import construir_demo
from lymi.bench.report import Receipt, render_card_html, render_terminal
from lymi.bench.runner import calentar_cache, run_task
from lymi.bench.strategies import SISTEMA
from lymi.bench.wiring import SinProveedorRemotoError, cablear
from lymi.cli_flow import flow_app
from lymi.cli_integraciones import integ_app
from lymi.cli_serve import hooks_app, schedule_app, servir
from lymi.control import Detenido, PresupuestoAgotado, detener, reanudar
from lymi.doctor import SIMBOLO, Estado, diagnosticar
from lymi.ledger import Ledger
from lymi.ledger.pricing import PRICES_UPDATED, load_overrides
from lymi.privacidad import EgressBloqueado
from lymi.providers.claude_code import ClaudeCodeAuthError, ClaudeCodeLimiteError
from lymi.providers.local import LocalTimeoutError


def _consola_utf8() -> None:
    """La consola de Windows arranca en cp1252 y no puede imprimir el recibo.
    Si no se puede cambiar, render_terminal cae solo a ASCII."""
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, OSError, ValueError):
            pass


_consola_utf8()

app = typer.Typer(
    name="lymi",
    help="Orquestador de agentes con contabilidad de tokens y egress auditables.",
    no_args_is_help=True,
    add_completion=False,
)


@app.command()
def bench(
    tarea: Annotated[str, typer.Argument(help="Tarea a medir: snake | research")] = "snake",
    demo: Annotated[bool, typer.Option("--demo", help="Respuestas guionadas: no gasta dinero.")] = False,
    db: Annotated[Path, typer.Option(help="Ruta del ledger.")] = Path("runs/lymi.sqlite3"),
    card: Annotated[Path | None, typer.Option(help="Exporta el recibo como tarjeta HTML.")] = None,
    abrir: Annotated[bool, typer.Option("--abrir", help="Abre la tarjeta al terminar.")] = False,
    calentar: Annotated[
        bool,
        typer.Option(
            "--calentar/--sin-calentar",
            help="Calienta la cache del proveedor antes de medir (llamada minima, registrada aparte).",
        ),
    ] = True,
) -> None:
    """Corre una tarea con la linea base y con lymi, y muestra el recibo."""
    if tarea != "snake":
        typer.secho(f"Por ahora solo esta la tarea 'snake', no {tarea!r}.", fg=typer.colors.RED)
        raise typer.Exit(1)

    load_overrides()

    if demo:
        objetivo, linea_base, lymi = construir_demo()
        procedencia = "respuestas guionadas"
    else:
        try:
            cab = cablear()
        except SinProveedorRemotoError as exc:
            typer.secho(str(exc), fg=typer.colors.YELLOW)
            raise typer.Exit(1) from exc
        from lymi.bench.demo import MATERIAL_DEMO
        from lymi.bench.tasks import SnakeTask

        objetivo = SnakeTask()
        objetivo.material = MATERIAL_DEMO
        linea_base, lymi = cab.base, cab.lymi
        procedencia = cab.resumen
        typer.secho(f"  {procedencia}", fg=typer.colors.CYAN)
        typer.echo()

    ledger = Ledger(db)
    try:
        # Sin calentar, la linea base escribe el prefijo en cache y lymi lo hereda:
        # el recibo se negaria a anunciar ahorro. En demo no hay cache que calentar.
        if calentar and not demo:
            typer.echo("  [0/2] calentando la cache del proveedor (llamada minima, registrada aparte)...")
            calentar_cache(ledger, objetivo, linea_base.remote, system=SISTEMA)
        # Cada corrida espera al modelo remoto sin imprimir nada: sin estas lineas
        # la terminal parece colgada durante minutos.
        typer.echo("  [1/2] linea base: esperando al modelo remoto...")
        r_base = run_task(ledger, objetivo, linea_base)
        typer.echo(f"        {r_base.gate.detail}")
        typer.echo("  [2/2] lymi: destilando en local y consultando al remoto...")
        r_lymi = run_task(ledger, objetivo, lymi)
        typer.echo(f"        {r_lymi.gate.detail}")
        typer.echo()
        recibo = Receipt(
            task_id=objetivo.id,
            task_title=objetivo.title,
            base=r_base,
            test=r_lymi,
            demo=demo,
        )
    except ClaudeCodeAuthError as exc:
        # Un problema de credenciales no es un fallo del programa: se explica en
        # una linea con el arreglo, no con una traza.
        typer.secho(f"\n  {exc}", fg=typer.colors.YELLOW)
        typer.echo("\n  Mientras tanto:  lymi bench snake --demo")
        raise typer.Exit(1) from None
    except (LocalTimeoutError, ClaudeCodeLimiteError, Detenido, PresupuestoAgotado, EgressBloqueado) as exc:
        # Ninguno es un fallo del programa (servidor local mudo, limite de la
        # suscripcion, parada, tope, dato que no sale): se explica sin traza.
        typer.secho(f"\n  {exc}", fg=typer.colors.YELLOW)
        raise typer.Exit(1) from None
    finally:
        ledger.close()

    typer.echo(render_terminal(recibo))
    typer.echo()
    typer.echo(f"  puerta linea base : {r_base.gate.detail}")
    typer.echo(f"  puerta lymi       : {r_lymi.gate.detail}")
    typer.echo(f"  proveedores       : {procedencia}")
    typer.echo(f"  tarifas al        : {PRICES_UPDATED}")

    if card:
        card.parent.mkdir(parents=True, exist_ok=True)
        card.write_text(render_card_html(recibo), encoding="utf-8")
        typer.echo(f"\n  tarjeta escrita en {card}")
        if abrir:
            webbrowser.open(card.resolve().as_uri())


@app.command()
def ledger(
    db: Annotated[Path, typer.Option(help="Ruta del ledger.")] = Path("runs/lymi.sqlite3"),
    limite: Annotated[int, typer.Option(help="Corridas a mostrar.")] = 20,
) -> None:
    """Lista las ultimas corridas registradas."""
    led = Ledger(db)
    try:
        filas = led.conn.execute(
            "SELECT r.id, r.task_id, r.variant, r.status, t.remote_tokens, t.local_tokens,"
            " t.cost_usd, t.unpriced_calls, t.egress_calls"
            " FROM runs r JOIN run_totals t ON t.run_id = r.id"
            " ORDER BY r.started_at DESC LIMIT ?",
            (limite,),
        ).fetchall()
    finally:
        led.close()

    if not filas:
        typer.echo("El ledger esta vacio. Corre: lymi bench snake --demo")
        return

    typer.echo(f"{'corrida':<14}{'tarea':<10}{'variante':<12}{'estado':<9}"
               f"{'remotos':>10}{'locales':>10}{'costo':>11}{'egress':>8}")
    typer.echo("─" * 84)
    for f in filas:
        costo = "n/d" if f["cost_usd"] is None else f"${f['cost_usd']:.4f}"
        aviso = "!" if f["unpriced_calls"] else " "
        typer.echo(
            f"{f['id']:<14}{f['task_id']:<10}{f['variant'][:11]:<12}{f['status']:<9}"
            f"{f['remote_tokens']:>10,}{f['local_tokens']:>10,}{costo:>10}{aviso}"
            f"{f['egress_calls']:>8}"
        )



@app.command()
def setup(
    probar: Annotated[
        bool, typer.Option("--probar/--sin-probar", help="Gasta ~20 tokens comprobando que la suscripcion autentica.")
    ] = True,
) -> None:
    """Revisa que proveedores hay listos y que falta para los demas."""
    d = diagnosticar(probar_claude=probar)

    typer.echo()
    for c in d.chequeos:
        color = {
            Estado.OK: typer.colors.GREEN,
            Estado.FALTA: typer.colors.YELLOW,
            Estado.ERROR: typer.colors.RED,
        }[c.estado]
        marca = typer.style(f"[{SIMBOLO[c.estado]}]", fg=color, bold=True)
        typer.echo(f"  {marca} {c.nombre:<16}{c.detalle}")
        if c.arreglo:
            typer.echo(f"      {typer.style(c.arreglo, fg=typer.colors.CYAN)}")

    typer.echo()
    if d.tier_local:
        typer.secho("  Tier local listo: el volumen pesado corre gratis en tu GPU.", fg=typer.colors.GREEN)
    else:
        typer.secho("  Sin tier local. Todo el volumen iria al modelo caro.", fg=typer.colors.YELLOW)

    if d.puede_medir:
        typer.secho("  Hay proveedor remoto: se puede medir de verdad.", fg=typer.colors.GREEN)
        typer.echo()
        typer.echo("  Siguiente:  lymi bench snake")
    else:
        typer.secho("  Sin proveedor remoto: solo esta disponible el modo demo.", fg=typer.colors.YELLOW)
        typer.echo()
        typer.echo("  Siguiente:  lymi bench snake --demo")

@app.command()
def stop(
    motivo: Annotated[str, typer.Argument(help="Por que se detiene; queda escrito en la parada.")] = "",
) -> None:
    """Detiene lymi en esta maquina: ninguna corrida hace otra llamada ni otro paso."""
    ruta = detener(motivo)
    typer.secho(f"  lymi detenido ({ruta}). Nada nuevo corre hasta `lymi resume`.", fg=typer.colors.RED, bold=True)


@app.command()
def undo(
    corrida: Annotated[str, typer.Argument(help="Id de la corrida cuyas acciones sobre el PC se deshacen.")],
) -> None:
    """Deshace lo que una corrida hizo en tus archivos. Nada se borra: todo pasa por el diario."""
    from lymi.ejecutor import DiarioError, deshacer, raiz_diario

    if not corrida.isalnum():
        typer.secho("  id de corrida invalido", fg=typer.colors.RED)
        raise typer.Exit(1)
    try:
        informe = deshacer(raiz_diario() / corrida)
    except DiarioError as exc:
        typer.secho(f"  {exc}", fg=typer.colors.YELLOW)
        raise typer.Exit(1) from None
    if not informe:
        typer.echo("  La corrida no habia tocado ningun archivo.")
    for linea in informe:
        color = typer.colors.YELLOW if linea.startswith("no se puede") else typer.colors.GREEN
        typer.secho(f"  {linea}", fg=color)


@app.command()
def resume() -> None:
    """Quita la parada."""
    if reanudar():
        typer.secho("  lymi reanudado.", fg=typer.colors.GREEN)
    else:
        typer.echo("  lymi no estaba detenido.")


@app.command()
def ui(
    puerto: Annotated[int, typer.Option(help="Puerto local.")] = 8770,
    abrir: Annotated[bool, typer.Option("--abrir/--no-abrir", help="Abre el navegador.")] = True,
    db: Annotated[Path, typer.Option(help="Ruta del ledger.")] = Path("runs/lymi.sqlite3"),
    workflows: Annotated[Path, typer.Option(help="Carpeta de workflows.")] = Path("workflows"),
) -> None:
    """Abre la interfaz de lymi en el navegador. Solo escucha en esta maquina."""
    import threading

    import uvicorn

    from lymi.ui.app import ConfigUI, crear_app_ui

    # Sin opcion de host a proposito: la interfaz lanza corridas que gastan tokens y
    # aprueba efectos. Exponerla fuera de loopback no es una configuracion, es un fallo.
    config = ConfigUI(
        ledger=db,
        workflows=workflows,
        memoria=Path("runs/aprobaciones.sqlite3"),
        hosts=frozenset({f"127.0.0.1:{puerto}", f"localhost:{puerto}"}),
    )
    url = f"http://127.0.0.1:{puerto}/"
    typer.secho(f"  lymi ui en {url}  (Ctrl+C para cerrar)", fg=typer.colors.GREEN)
    typer.echo("  Solo escucha en esta maquina y la pagina no pide nada a internet.")
    if abrir:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    uvicorn.run(crear_app_ui(config), host="127.0.0.1", port=puerto, log_level="warning")


app.add_typer(flow_app, name="flow")
app.add_typer(integ_app, name="integrations")
app.add_typer(schedule_app, name="schedule")
app.add_typer(hooks_app, name="hooks")

from lymi.cli_web import web_app

app.add_typer(web_app, name="web")
app.command("serve")(servir)


if __name__ == "__main__":
    app()
