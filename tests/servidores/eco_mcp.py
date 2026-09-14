"""Servidor MCP minimo para pruebas de punta a punta.

El mismo objeto sirve por stdio (ejecutando este archivo) y por HTTP (montando
`servidor.streamable_http_app()`), asi ambos transportes se prueban contra el
mismo codigo.
"""

from __future__ import annotations

import os

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel

servidor = MCPServer("eco")


class Total(BaseModel):
    total: int


@servidor.tool(structured_output=False)
def eco(texto: str) -> str:
    """Devuelve el texto tal cual."""
    return texto


@servidor.tool()
def suma(a: int, b: int) -> Total:
    """Suma dos enteros."""
    return Total(total=a + b)


@servidor.tool(structured_output=False)
def leer_env(nombre: str) -> str:
    """Devuelve una variable de entorno del proceso servidor, o <ausente>."""
    return os.environ.get(nombre, "<ausente>")


@servidor.tool(structured_output=False)
def falla() -> str:
    """Error declarado: su mensaje es para quien llama y viaja hasta el cliente."""
    raise ToolError("fallo a proposito")


@servidor.tool(structured_output=False)
def crashea() -> str:
    """Excepcion inesperada: el servidor no filtra el detalle interno al cliente."""
    raise RuntimeError("detalle interno que no debe salir")


@servidor.tool(structured_output=False)
def morir() -> str:
    """Mata el proceso del servidor. Solo para pruebas por stdio: por HTTP mataria
    al proceso que ejecuta las pruebas."""
    os._exit(1)


if __name__ == "__main__":
    servidor.run("stdio")
