"""El indice de codigo como servidor MCP, para cualquier agente.

`lymi codigo servir` por stdio. Todas las herramientas son de solo lectura y solo
devuelven archivos indexados de la raiz: una ruta con `..` o absoluta no coincide
con nada del indice, asi que no hay nada que escapar.

Cada llamada abre el indice, lo pone al dia (milisegundos si nada cambio) y lo
cierra: la respuesta describe el codigo tal como esta ahora.
"""

from __future__ import annotations

from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from lymi.codigo import formato
from lymi.codigo.indice import IndiceError, abrir

INSTRUCCIONES = """Mapa del codigo de este repositorio, siempre al dia.
Antes de abrir un archivo completo: usa `esqueleto` para ver sus firmas, `fragmento`
para leer solo la funcion o clase que necesitas, `buscar_simbolo` para encontrar
donde esta algo, y `llamadores` o `impacto` antes de cambiar una firma.
La resolucion de llamadas es por nombre (sin tipos) y solo Python es exacto."""

_LECTURA = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)


def crear_servidor(raiz: Path) -> MCPServer:
    raiz = Path(raiz).resolve()
    servidor = MCPServer("lymi-codigo", instructions=INSTRUCCIONES)

    def consultar(funcion) -> str:
        try:
            with abrir(raiz) as indice:
                return funcion(indice)
        except IndiceError as exc:
            return f"error: {exc}"

    @servidor.tool(annotations=_LECTURA, structured_output=False)
    def buscar_simbolo(consulta: str, limite: int = 20) -> str:
        """Busca funciones, clases y metodos por nombre (subcadena, sin distinguir mayusculas)."""
        return consultar(lambda i: formato.buscar(i.buscar(consulta, max(1, min(limite, 100)))))

    @servidor.tool(annotations=_LECTURA, structured_output=False)
    def esqueleto(ruta: str) -> str:
        """Firmas y primera linea de documentacion de un archivo, sin los cuerpos."""
        return consultar(lambda i: formato.esqueleto(i.esqueleto(ruta)))

    @servidor.tool(annotations=_LECTURA, structured_output=False)
    def fragmento(nombre: str) -> str:
        """El codigo de una funcion, metodo o clase (ej. `Web.obtener`), no del archivo entero."""
        return consultar(lambda i: formato.fragmentos(i.fragmento(nombre)))

    @servidor.tool(annotations=_LECTURA, structured_output=False)
    def llamadores(nombre: str) -> str:
        """Donde se llama a una funcion o metodo."""
        return consultar(lambda i: formato.llamadores(nombre, i.llamadores(nombre)))

    @servidor.tool(annotations=_LECTURA, structured_output=False)
    def impacto(nombre: str, profundidad: int = 3) -> str:
        """Que codigo y que pruebas se ven afectados si cambia `nombre` (llamadores transitivos)."""
        return consultar(lambda i: formato.impacto(i.impacto(nombre, profundidad)))

    @servidor.tool(annotations=_LECTURA, structured_output=False)
    def mapa(prefijo: str = "") -> str:
        """Archivos del repositorio con su tamano, simbolos y dependencias internas."""
        return consultar(lambda i: formato.mapa(i.mapa(prefijo)))

    return servidor
