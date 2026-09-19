"""Subcomandos `lymi codigo`: el mapa del repositorio desde la terminal o por MCP."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from lymi.codigo import IndiceError, abrir
from lymi.codigo import formato as fmt

codigo_app = typer.Typer(
    help="Mapa del codigo: firmas, fragmentos y llamadores en vez de archivos enteros.",
    no_args_is_help=True,
    add_completion=False,
)

Raiz = Annotated[Path, typer.Option("--raiz", help="Carpeta del repositorio.")]


def _nota(texto: str) -> None:
    typer.secho(f"  {texto}", fg=typer.colors.BRIGHT_BLACK, err=True)


def _correr(raiz: Path, funcion) -> None:
    try:
        with abrir(raiz) as indice:
            funcion(indice)
    except IndiceError as exc:
        typer.secho(f"  {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from None


@codigo_app.command("indexar")
def indexar(raiz: Raiz = Path(".")) -> None:
    """Indexa o pone al dia el repositorio (cada consulta lo hace sola)."""

    def trabajo(indice) -> None:
        typer.secho(f"  {indice.ultima.resumen()}", fg=typer.colors.GREEN)
        datos = indice.mapa(limite=0)
        typer.echo(f"  {datos['total']} archivos: " + ", ".join(f"{k} {v}" for k, v in sorted(datos["lenguajes"].items())))
        for omitido in indice.ultima.omitidos[:10]:
            _nota(f"omitido: {omitido}")

    _correr(raiz, trabajo)


@codigo_app.command("buscar")
def buscar(consulta: str, limite: Annotated[int, typer.Option(min=1, max=100)] = 20, raiz: Raiz = Path(".")) -> None:
    """Funciones, clases y metodos cuyo nombre contiene la consulta."""
    _correr(raiz, lambda i: typer.echo(fmt.buscar(i.buscar(consulta, limite))))


@codigo_app.command("esqueleto")
def esqueleto(ruta: str, raiz: Raiz = Path(".")) -> None:
    """Las firmas de un archivo, sin los cuerpos."""

    def trabajo(indice) -> None:
        datos = indice.esqueleto(ruta)
        texto = fmt.esqueleto(datos)
        typer.echo(texto)
        _nota(fmt.ahorro(len(texto.encode("utf-8")), datos["bytes_archivo"]))

    _correr(raiz, trabajo)


@codigo_app.command("fragmento")
def fragmento(nombre: str, raiz: Raiz = Path(".")) -> None:
    """El codigo de un simbolo (ej. Web.obtener), no del archivo entero."""

    def trabajo(indice) -> None:
        resultados = indice.fragmento(nombre)
        texto = fmt.fragmentos(resultados)
        typer.echo(texto)
        if resultados:
            completos = sum({r["ruta"]: r["bytes_archivo"] for r in resultados}.values())
            _nota(fmt.ahorro(len(texto.encode("utf-8")), completos))

    _correr(raiz, trabajo)


@codigo_app.command("llamadores")
def llamadores(nombre: str, raiz: Raiz = Path(".")) -> None:
    """Donde se llama a una funcion o metodo."""
    _correr(raiz, lambda i: typer.echo(fmt.llamadores(nombre, i.llamadores(nombre))))


@codigo_app.command("impacto")
def impacto(
    nombre: str,
    profundidad: Annotated[int, typer.Option(min=1, max=6)] = 3,
    raiz: Raiz = Path("."),
) -> None:
    """Que codigo y que pruebas toca un cambio en `nombre`."""
    _correr(raiz, lambda i: typer.echo(fmt.impacto(i.impacto(nombre, profundidad))))


@codigo_app.command("mapa")
def mapa(prefijo: Annotated[str, typer.Argument()] = "", raiz: Raiz = Path(".")) -> None:
    """Archivos con su tamano, simbolos y dependencias internas."""
    _correr(raiz, lambda i: typer.echo(fmt.mapa(i.mapa(prefijo))))


@codigo_app.command("servir")
def servir(raiz: Raiz = Path(".")) -> None:
    """Servidor MCP por stdio. En Claude Code: claude mcp add lymi-codigo -- uv run lymi codigo servir"""
    from lymi.codigo.servidor import crear_servidor

    if not raiz.is_dir():
        typer.secho(f"  {raiz} no es una carpeta", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    # stdout es el canal del protocolo: nada mas se imprime ahi.
    crear_servidor(raiz).run("stdio")
