"""Simbolos, llamadas e importaciones de un archivo de codigo.

Python se analiza con `ast` de la libreria estandar: exacto y sin ejecutar nada
del archivo. JavaScript/TypeScript, Go y Rust tienen un extractor aproximado por
patrones, que encuentra definiciones e importaciones pero no llamadas. El indice
guarda cual de los dos se uso, para que ninguna respuesta aparente mas precision
de la que tiene.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field

LENGUAJES = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
}

VERSION = 2
"""Sube cuando cambia lo que se extrae: el indice se reconstruye solo."""

MODULO = "<modulo>"
"""Nombre del llamador cuando la llamada esta fuera de toda funcion."""


@dataclass(slots=True)
class Simbolo:
    nombre: str
    """Nombre calificado dentro del archivo: `Clase.metodo`."""
    tipo: str
    """funcion | metodo | clase | tipo"""
    linea: int
    linea_fin: int
    firma: str
    doc: str = ""


@dataclass(slots=True)
class Llamada:
    desde: str
    hacia: str
    """Nombre simple llamado. Sin tipos: `self.x()` y `otro.x()` son ambos `x`."""
    linea: int


@dataclass(slots=True)
class Extraido:
    lenguaje: str
    exacto: bool
    simbolos: list[Simbolo] = field(default_factory=list)
    llamadas: list[Llamada] = field(default_factory=list)
    importaciones: list[str] = field(default_factory=list)
    esqueleto: str = ""
    error: str | None = None


def _primera_linea(doc: str | None) -> str:
    if not doc:
        return ""
    return doc.strip().splitlines()[0].strip()[:200]


def _nombre_llamado(funcion: ast.expr) -> str | None:
    if isinstance(funcion, ast.Name):
        return funcion.id
    if isinstance(funcion, ast.Attribute):
        return funcion.attr
    return None


def _llamadas_en(nodo: ast.AST, desde: str) -> list[Llamada]:
    encontradas = []
    for sub in ast.walk(nodo):
        if isinstance(sub, ast.Call) and (nombre := _nombre_llamado(sub.func)):
            encontradas.append(Llamada(desde, nombre, sub.lineno))
    return encontradas


def _python(texto: str, ruta: str) -> Extraido:
    try:
        arbol = ast.parse(texto, filename=ruta)
    except (SyntaxError, ValueError, RecursionError) as exc:
        return Extraido("python", True, error=f"no se pudo analizar: {type(exc).__name__}")

    resultado = Extraido("python", True)
    esqueleto: list[str] = []
    if doc := _primera_linea(ast.get_docstring(arbol)):
        esqueleto.append(f'"""{doc}"""')

    def firma(nodo: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        prefijo = "async def" if isinstance(nodo, ast.AsyncFunctionDef) else "def"
        retorno = f" -> {ast.unparse(nodo.returns)}" if nodo.returns is not None else ""
        return f"{prefijo} {nodo.name}({ast.unparse(nodo.args)}){retorno}"

    def visitar(cuerpo: list[ast.stmt], prefijo: str, sangria: str) -> None:
        for nodo in cuerpo:
            if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
                nombre = f"{prefijo}{nodo.name}"
                texto_firma = firma(nodo)
                doc = _primera_linea(ast.get_docstring(nodo))
                resultado.simbolos.append(
                    Simbolo(nombre, "metodo" if prefijo else "funcion", nodo.lineno,
                            nodo.end_lineno or nodo.lineno, texto_firma, doc)
                )
                esqueleto.extend(f"{sangria}@{ast.unparse(d)}" for d in nodo.decorator_list)
                esqueleto.append(f"{sangria}{texto_firma}: ...  # L{nodo.lineno}")
                if doc:
                    esqueleto.append(f'{sangria}    """{doc}"""')
                # Las funciones anidadas no se indexan aparte: sus llamadas cuentan
                # para la funcion que las contiene, que es a quien se llama.
                resultado.llamadas.extend(_llamadas_en(nodo, nombre))
            elif isinstance(nodo, ast.ClassDef):
                nombre = f"{prefijo}{nodo.name}"
                bases = ", ".join(ast.unparse(b) for b in nodo.bases)
                texto_firma = f"class {nodo.name}({bases})" if bases else f"class {nodo.name}"
                doc = _primera_linea(ast.get_docstring(nodo))
                resultado.simbolos.append(
                    Simbolo(nombre, "clase", nodo.lineno, nodo.end_lineno or nodo.lineno, texto_firma, doc)
                )
                esqueleto.extend(f"{sangria}@{ast.unparse(d)}" for d in nodo.decorator_list)
                esqueleto.append(f"{sangria}{texto_firma}:  # L{nodo.lineno}")
                if doc:
                    esqueleto.append(f'{sangria}    """{doc}"""')
                visitar(nodo.body, f"{nombre}.", sangria + "    ")
            elif not prefijo:
                if isinstance(nodo, (ast.Assign, ast.AnnAssign)):
                    objetivos = nodo.targets if isinstance(nodo, ast.Assign) else [nodo.target]
                    for objetivo in objetivos:
                        if isinstance(objetivo, ast.Name) and objetivo.id.isupper():
                            esqueleto.append(f"{objetivo.id} = ...  # L{nodo.lineno}")
                resultado.llamadas.extend(_llamadas_en(nodo, MODULO))

    visitar(arbol.body, "", "")

    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            resultado.importaciones.extend(alias.name for alias in nodo.names)
        elif isinstance(nodo, ast.ImportFrom):
            base = "." * nodo.level + (nodo.module or "")
            resultado.importaciones.append(base)
            # `from paquete import modulo` importa un archivo aunque el __init__ no
            # lo mencione: se prueba tambien `paquete.modulo`. Si no existe, no resuelve.
            separador = "." if nodo.module else ""
            resultado.importaciones.extend(
                f"{base}{separador}{alias.name}" for alias in nodo.names if alias.name != "*"
            )
    resultado.importaciones = list(dict.fromkeys(resultado.importaciones))
    resultado.esqueleto = "\n".join(esqueleto)
    return resultado


_JS = (
    (re.compile(r"^[ \t]*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)\s*\(", re.MULTILINE),
     "funcion"),
    (re.compile(r"^[ \t]*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+([A-Za-z_$][\w$]*)", re.MULTILINE), "clase"),
    (re.compile(
        r"^[ \t]*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*(?:async\s*)?"
        r"(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*(?::[^=]+)?=>", re.MULTILINE), "funcion"),
)
_TS_EXTRA = (
    (re.compile(r"^[ \t]*(?:export\s+)?(?:interface|type|enum)\s+([A-Za-z_$][\w$]*)", re.MULTILINE), "tipo"),
)
_PATRONES = {
    "javascript": _JS,
    "typescript": _JS + _TS_EXTRA,
    "go": (
        (re.compile(r"^func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)\s*[\[(]", re.MULTILINE), "funcion"),
        (re.compile(r"^type\s+([A-Za-z_]\w*)\s+(?:struct|interface)\b", re.MULTILINE), "tipo"),
    ),
    "rust": (
        (re.compile(r"^[ \t]*(?:pub(?:\([^)]*\))?\s+)?(?:const\s+)?(?:async\s+)?(?:unsafe\s+)?fn\s+([A-Za-z_]\w*)",
                    re.MULTILINE), "funcion"),
        (re.compile(r"^[ \t]*(?:pub(?:\([^)]*\))?\s+)?(?:struct|enum|trait)\s+([A-Za-z_]\w*)", re.MULTILINE), "tipo"),
    ),
}
_IMPORTS = {
    "javascript": re.compile(r"""(?:\bfrom\s+|\brequire\(\s*|^\s*import\s+)["']([^"']+)["']""", re.MULTILINE),
    "go": re.compile(r"""^\s*(?:import\s+)?(?:[A-Za-z_]\w*\s+)?"([^"]+)"\s*$""", re.MULTILINE),
    "rust": re.compile(r"^\s*(?:pub\s+)?use\s+([\w:]+)", re.MULTILINE),
}
_IMPORTS["typescript"] = _IMPORTS["javascript"]
_COMENTARIO = {"javascript": "//", "typescript": "//", "go": "//", "rust": "//"}


def _aproximado(texto: str, lenguaje: str) -> Extraido:
    resultado = Extraido(lenguaje, False)
    inicios = [0]
    for i, caracter in enumerate(texto):
        if caracter == "\n":
            inicios.append(i + 1)

    def linea_de(posicion: int) -> int:
        bajo, alto = 0, len(inicios) - 1
        while bajo < alto:
            medio = (bajo + alto + 1) // 2
            if inicios[medio] <= posicion:
                bajo = medio
            else:
                alto = medio - 1
        return bajo + 1

    lineas = texto.splitlines()
    for patron, tipo in _PATRONES[lenguaje]:
        for m in patron.finditer(texto):
            numero = linea_de(m.start(1))
            firma = lineas[numero - 1].strip()[:160] if numero <= len(lineas) else m.group(0).strip()
            # Sin analizador no se conoce el final: se marca igual al inicio.
            resultado.simbolos.append(Simbolo(m.group(1), tipo, numero, numero, firma))
    resultado.simbolos.sort(key=lambda s: s.linea)
    if patron_imports := _IMPORTS.get(lenguaje):
        resultado.importaciones = list(dict.fromkeys(patron_imports.findall(texto)))
    comentario = _COMENTARIO[lenguaje]
    resultado.esqueleto = "\n".join(f"{s.firma}  {comentario} L{s.linea}" for s in resultado.simbolos)
    return resultado


def extraer(texto: str, ruta: str, lenguaje: str) -> Extraido:
    if lenguaje == "python":
        return _python(texto, ruta)
    return _aproximado(texto, lenguaje)
