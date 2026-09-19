"""Procedencia de las citas: un agente solo puede citar lo que vio.

Un modelo pequeno lee `red.py:91` en el resultado de una herramienta y escribe
`buscar.py:39` en su respuesta. No hay forma de notarlo leyendo la respuesta: se
ve igual de segura. Por eso lymi guarda cada `ruta:linea` y cada URL que aparece
en lo que el agente recibio (su tarea, los resultados de herramientas, lo que le
entregaron sus hijas, sus mensajes) y, al terminar, compara.

Es mecanico y falsable: no juzga si la respuesta es buena, solo si cada
referencia tiene de donde salir.
"""

from __future__ import annotations

import re

_EXTENSIONES = r"py|pyi|js|mjs|cjs|jsx|ts|tsx|go|rs|md|ya?ml|json|toml|txt|css|html|sql|sh"
_RUTA_LINEA = re.compile(
    rf"(?<![\w/\\.-])((?:[\w.-]+[/\\])*[\w.-]+\.(?:{_EXTENSIONES})):(\d+)(?:-(\d+))?"
)
_URL = re.compile(r"https?://[^\s)\]>\"'«»`]+")
_CABECERA = re.compile(rf"^# ((?:[\w.-]+/)*[\w.-]+\.(?:{_EXTENSIONES})) \(", re.MULTILINE)
_LINEA_ESQUELETO = re.compile(r"# L(\d+)\b")
MAX_RANGO = 400


def _ruta(texto: str) -> str:
    ruta = texto.replace("\\", "/")
    while ruta.startswith("./"):
        ruta = ruta[2:]
    return ruta


def _url(texto: str) -> str:
    return texto.rstrip(".,;:!?").rstrip("/")


def citas(texto: str) -> list[str]:
    """Referencias que afirma un texto: `ruta:linea` y URLs, en orden y sin repetir."""
    encontradas = [f"{_ruta(r)}:{linea}" for r, linea, _ in _RUTA_LINEA.findall(texto)]
    encontradas += [_url(u) for u in _URL.findall(texto)]
    return list(dict.fromkeys(encontradas))


def vistas(texto: str) -> set[str]:
    """Referencias que un texto recibido pone a disposicion del agente.

    Entiende los formatos de lymi: `ruta:10-20` (un fragmento) respalda cada linea
    del rango, y un esqueleto (`# ruta (python ...)` seguido de `# L91`) respalda
    cada linea que lista.
    """
    encontradas: set[str] = set()
    for r, desde, hasta in _RUTA_LINEA.findall(texto):
        ruta, inicio = _ruta(r), int(desde)
        fin = min(int(hasta), inicio + MAX_RANGO) if hasta else inicio
        encontradas.update(f"{ruta}:{n}" for n in range(inicio, fin + 1))
    encontradas.update(_url(u) for u in _URL.findall(texto))
    cabeceras = list(_CABECERA.finditer(texto))
    for i, cabecera in enumerate(cabeceras):
        fin = cabeceras[i + 1].start() if i + 1 < len(cabeceras) else len(texto)
        ruta = _ruta(cabecera.group(1))
        encontradas.update(f"{ruta}:{n}" for n in _LINEA_ESQUELETO.findall(texto, cabecera.end(), fin))
    return encontradas


def respaldada(cita: str, vistos: set[str]) -> bool:
    """Si la cita salio de algo visto. `red.py:91` vale si se vio `src/lymi/web/red.py:91`."""
    if cita in vistos:
        return True
    if cita.startswith(("http://", "https://")):
        return False
    return any(v.endswith("/" + cita) for v in vistos)


def sin_respaldo(texto: str, vistos: set[str]) -> list[str]:
    return [c for c in citas(texto) if not respaldada(c, vistos)]
