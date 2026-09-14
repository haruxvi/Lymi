"""Subcomandos `lymi integrations`: importar del catalogo y conectar cuentas."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

import typer

from lymi.flows.catalogo import CatalogoError, importar_manifiesto
from lymi.flows.oauth_dispositivo import CodigoDispositivo
from lymi.flows.schema import McpIntegration, WorkflowError, cargar

integ_app = typer.Typer(
    help="Integraciones MCP: importar del catalogo y conectar cuentas.",
    no_args_is_help=True,
    add_completion=False,
)


def _causa(exc: BaseException) -> BaseException:
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return exc


def _integracion_oauth(workflow: Path, nombre: str) -> McpIntegration:
    try:
        flujo = cargar(workflow)
    except WorkflowError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1) from None

    integ = flujo.integrations.get(nombre)
    if integ is None:
        disponibles = ", ".join(flujo.integrations) or "ninguna"
        typer.secho(f"  {workflow} no declara la integracion {nombre!r} (hay: {disponibles})", fg=typer.colors.RED)
        raise typer.Exit(1)
    if not isinstance(integ, McpIntegration) or integ.transport != "http" or integ.auth != "oauth":
        typer.secho(f"  {nombre!r} no es un servidor MCP por http con auth: oauth", fg=typer.colors.RED)
        raise typer.Exit(1)
    return integ


@integ_app.command("import")
def importar(
    manifiesto: Annotated[Path, typer.Argument(help="manifest.yaml de un catalogo MCP.")],
    salida: Annotated[Path | None, typer.Option("--output", "-o", help="Escribe el bloque YAML en un archivo.")] = None,
) -> None:
    """Convierte un manifiesto del catalogo en una integracion de lymi. No instala nada."""
    try:
        imp = importar_manifiesto(manifiesto)
    except CatalogoError as exc:
        typer.secho(f"  {exc}", fg=typer.colors.RED)
        raise typer.Exit(1) from None

    texto = imp.como_yaml()
    if salida is None:
        typer.echo(texto)
    else:
        salida.write_text(texto, encoding="utf-8")
        typer.secho(f"  bloque escrito en {salida}", fg=typer.colors.GREEN)

    for aviso in imp.avisos:
        typer.secho(f"  aviso: {aviso}", fg=typer.colors.YELLOW)

    if imp.variables:
        typer.echo()
        typer.secho("  Variables de entorno que necesita (en .env, nunca en el YAML):", bold=True)
        for v in imp.variables:
            tipo = "secreta" if v.secreta else "no secreta"
            opcional = "" if v.requerida else ", opcional"
            defecto = f"  [por defecto: {v.defecto}]" if v.defecto and not v.secreta else ""
            typer.echo(f"    {v.nombre:<24}{tipo}{opcional}  {v.descripcion}{defecto}")

    if imp.instalacion_manual:
        typer.echo()
        typer.secho("  Instalacion manual:", bold=True)
        for linea in imp.instalacion_manual.splitlines():
            typer.echo(f"    {linea}")

    if imp.integracion.auth == "oauth":
        typer.echo()
        typer.echo("  Despues de anadirla a tu workflow, conecta la cuenta con:")
        typer.secho(f"    lymi integrations login <workflow.yml> {imp.nombre}", fg=typer.colors.CYAN)


@integ_app.command("login")
def login(
    workflow: Annotated[Path, typer.Argument(help="Workflow que declara la integracion.")],
    nombre: Annotated[str, typer.Argument(help="Nombre de la integracion.")],
    puerto: Annotated[int | None, typer.Option(help="Puerto local para el retorno del navegador.")] = None,
    dispositivo: Annotated[
        bool, typer.Option("--dispositivo", help="Sin navegador aqui: autoriza con un codigo desde otro dispositivo.")
    ] = False,
    client_id: Annotated[
        str | None, typer.Option("--client-id", help="Client id OAuth, si el servidor no admite registro dinamico.")
    ] = None,
) -> None:
    """Conecta tu cuenta con un servidor MCP remoto: con navegador, o con un codigo de dispositivo."""
    from lymi.flows import oauth

    integ = _integracion_oauth(workflow, nombre)

    def mostrar(url: str) -> None:
        typer.echo("  Abriendo el navegador para autorizar a lymi. Si no se abre, visita:")
        typer.secho(f"  {url}", fg=typer.colors.CYAN)

    def mostrar_codigo(codigo: CodigoDispositivo) -> None:
        typer.echo("  Desde cualquier dispositivo con navegador, abre:")
        typer.secho(f"  {codigo.verification_uri_complete or codigo.verification_uri}", fg=typer.colors.CYAN)
        typer.echo("  e ingresa este codigo:")
        typer.secho(f"  {codigo.user_code}", fg=typer.colors.GREEN, bold=True)
        typer.echo(f"  Esperando la autorizacion (vence en {codigo.expires_in // 60} min)...")

    try:
        if dispositivo:
            from lymi.flows import oauth_dispositivo

            herramientas = asyncio.run(
                oauth_dispositivo.iniciar_sesion_dispositivo(
                    integ.url or "", list(integ.scopes), client_id=client_id, mostrar=mostrar_codigo
                )
            )
        else:
            herramientas = asyncio.run(
                oauth.iniciar_sesion(
                    integ.url or "",
                    list(integ.scopes),
                    mostrar=mostrar,
                    puerto=puerto if puerto is not None else oauth.PUERTO_RETORNO,
                )
            )
    except Exception as exc:  # noqa: BLE001 - se explica en una linea, sin traza
        typer.secho(f"  No se pudo iniciar sesion: {_causa(exc)}", fg=typer.colors.RED)
        raise typer.Exit(1) from None

    typer.echo()
    typer.secho(
        f"  Sesion iniciada con {nombre}. Tokens guardados en el almacen de credenciales del sistema.",
        fg=typer.colors.GREEN,
    )
    typer.echo(f"  El servidor ofrece {len(herramientas)} herramientas.")
    if integ.tools is None:
        typer.secho(
            "  Tu workflow las habilita todas. Lista en `tools:` solo las que usas.",
            fg=typer.colors.YELLOW,
        )
    else:
        typer.echo(f"  Tu workflow habilita {len(integ.tools)}: {', '.join(integ.tools)}")
        faltan = sorted(set(integ.tools) - set(herramientas))
        if faltan:
            typer.secho(f"  El servidor no ofrece: {', '.join(faltan)}", fg=typer.colors.YELLOW)


@integ_app.command("logout")
def logout(
    workflow: Annotated[Path, typer.Argument(help="Workflow que declara la integracion.")],
    nombre: Annotated[str, typer.Argument(help="Nombre de la integracion.")],
) -> None:
    """Borra los tokens guardados de una integracion."""
    from lymi.flows import oauth

    integ = _integracion_oauth(workflow, nombre)
    try:
        oauth.almacen_para(integ.url or "").borrar()
    except oauth.OAuthError as exc:
        typer.secho(f"  {exc}", fg=typer.colors.RED)
        raise typer.Exit(1) from None
    typer.secho(f"  Sesion cerrada: se borraron los tokens de {nombre}.", fg=typer.colors.GREEN)
