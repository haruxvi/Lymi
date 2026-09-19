"""Texto compacto para las respuestas del indice.

El mismo texto sirve a la terminal y a un agente por MCP: cada caracter que se
ahorra aqui se ahorra en cada llamada. Nada de decoracion.
"""

from __future__ import annotations

from typing import Any


def _kb(n: int) -> str:
    return f"{n / 1024:.1f} kB" if n >= 1024 else f"{n} B"


def ahorro(servidos: int, completos: int) -> str:
    """Bytes servidos frente a leer los archivos completos. Medido, no estimado."""
    if completos <= 0:
        return f"{_kb(servidos)}"
    porcentaje = 100 * (1 - servidos / completos)
    return f"{_kb(servidos)} en vez de {_kb(completos)} ({porcentaje:.0f}% menos)"


def _aviso_aproximado(exacto: bool) -> str:
    return "" if exacto else "  [aproximado: sin analizador para este lenguaje]"


def buscar(resultados: list[dict[str, Any]]) -> str:
    if not resultados:
        return "sin coincidencias"
    lineas = []
    for r in resultados:
        doc = f"  -- {r['doc']}" if r["doc"] else ""
        lineas.append(f"{r['ruta']}:{r['linea']}  {r['tipo']} {r['nombre']}{_aviso_aproximado(r['exacto'])}")
        lineas.append(f"    {r['firma']}{doc}")
    return "\n".join(lineas)


def esqueleto(datos: dict[str, Any]) -> str:
    cabecera = f"# {datos['ruta']} ({datos['lenguaje']}, {datos['lineas']} lineas){_aviso_aproximado(datos['exacto'])}"
    if datos["error"]:
        cabecera += f"\n# {datos['error']}"
    return f"{cabecera}\n{datos['esqueleto'] or '(sin definiciones)'}"


def fragmentos(resultados: list[dict[str, Any]]) -> str:
    if not resultados:
        return "no hay un simbolo con ese nombre (prueba buscar_simbolo)"
    bloques = []
    for r in resultados:
        bloques.append(
            f"# {r['ruta']}:{r['linea']}-{r['linea_fin']}  {r['nombre']}{_aviso_aproximado(r['exacto'])}\n{r['codigo']}"
        )
    return "\n\n".join(bloques)


def llamadores(nombre: str, resultados: list[dict[str, Any]]) -> str:
    confirmados = [r for r in resultados if r["confirmado"]]
    posibles = [r for r in resultados if not r["confirmado"]]
    if not confirmados and not posibles:
        return f"nadie llama a {nombre} (los lenguajes aproximados no registran llamadas)"
    lineas = [f"{len(confirmados)} llamadas a {nombre} (confirmadas por importacion, sin tipos):"]
    lineas.extend(f"  {r['ruta']}:{r['linea']}  desde {r['desde']}" for r in confirmados)
    if posibles:
        muestra = ", ".join(f"{r['ruta']}:{r['linea']}" for r in posibles[:5])
        extra = f" y {len(posibles) - 5} mas" if len(posibles) > 5 else ""
        lineas.append(f"{len(posibles)} posibles homonimos en archivos que no importan la definicion: {muestra}{extra}")
    return "\n".join(lineas)


def impacto(datos: dict[str, Any]) -> str:
    if not datos["niveles"]:
        return f"nada depende de {datos['nombre']} en el indice"
    lineas = [f"si cambia {datos['nombre']}:"]
    for i, nivel in enumerate(datos["niveles"], start=1):
        simbolos = ", ".join(f"{n['simbolo']} ({n['ruta']})" for n in nivel[:15])
        extra = f" y {len(nivel) - 15} mas" if len(nivel) > 15 else ""
        lineas.append(f"  nivel {i}: {simbolos}{extra}")
    if datos["pruebas"]:
        lineas.append("pruebas a correr: " + " ".join(datos["pruebas"]))
    lineas.append(f"nota: {datos['nota']}")
    return "\n".join(lineas)


def mapa(datos: dict[str, Any]) -> str:
    lenguajes = ", ".join(f"{k} {v}" for k, v in sorted(datos["lenguajes"].items()))
    lineas = [f"{datos['total']} archivos ({lenguajes})"]
    for a in datos["archivos"]:
        usa = f"  usa: {', '.join(a['usa'])}" if a["usa"] else ""
        lineas.append(f"  {a['ruta']}  {a['lineas']} lineas, {a['simbolos']} simbolos{usa}")
    if datos["mostrados"] < datos["total"]:
        lineas.append(f"  ... {datos['total'] - datos['mostrados']} mas: filtra con un prefijo de carpeta")
    return "\n".join(lineas)
