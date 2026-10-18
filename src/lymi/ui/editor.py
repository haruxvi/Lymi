"""El editor de workflows por nodos: esquema, validacion, guardado y costo por nodo.

El lienzo y el YAML son el mismo archivo. El lienzo manda el workflow como datos,
lymi lo valida con el mismo esquema que `lymi flow run` y lo escribe en YAML. Lo
que no pasa la validacion no se guarda: un lienzo nunca deja un archivo roto.

Guardar reescribe el YAML (los comentarios del archivo no sobreviven), asi que
antes se guarda una copia del anterior en `runs/workflows-anteriores/`.

El costo de cada nodo no es una estimacion: es la mediana de lo que ese paso
gasto en las ultimas corridas reales del ledger. Sin corridas, se dice.
"""

from __future__ import annotations

import shutil
import statistics
import typing
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from lymi.flows.plan import planificar, resumir
from lymi.flows.schema import Step, Workflow
from lymi.ledger import Ledger
from lymi.ui.comun import ErrorApi, archivo_en, cuerpo

GRUPOS = {
    "llm": ("Modelos", "Modelo de lenguaje", "Pide texto o JSON a un modelo local (gratis) o remoto (se paga)."),
    "agencia": ("Modelos", "Agencia", "Le da una tarea a una agencia de agentes con departamentos."),
    "correo": ("Tus datos", "Correo", "Lee tu bandeja de Thunderbird o la resume. Nunca envia."),
    "calendario": ("Tus datos", "Calendario", "Tus eventos de los proximos dias, de archivos .ics."),
    "memoria": ("Tus datos", "Memoria", "Busca en la memoria o anota algo para revisar."),
    "codigo": ("Tus datos", "Codigo", "Consulta el mapa de un repositorio: simbolos, llamadores, impacto."),
    "web": ("Red", "Web", "Lee una pagina, busca, mapea un sitio o investiga con fuentes."),
    "http": ("Red", "HTTP", "Llama a una API de una integracion declarada."),
    "tool": ("Red", "Herramienta MCP", "Usa una herramienta de un servidor MCP."),
    "pc": ("Tu PC", "PC", "Lee, lista, escribe, mueve, borra o ejecuta, con diario de deshacer."),
    "transform": ("Logica", "Transformar", "Arma datos con plantillas a partir de pasos anteriores."),
}
COMUNES = ("id", "type", "when", "retries", "timeout_s")


def _tipos_de_paso() -> list[type]:
    union = typing.get_args(Step)[0]
    return list(typing.get_args(union))


def esquema() -> dict[str, Any]:
    """Cada tipo de nodo con sus campos: de aqui salen la paleta y el inspector."""
    tipos = []
    for clase in _tipos_de_paso():
        js = clase.model_json_schema()
        tipo = js["properties"]["type"].get("const") or js["properties"]["type"]["enum"][0]
        grupo, titulo, descripcion = GRUPOS.get(tipo, ("Otros", tipo, ""))
        campos = {k: v for k, v in js["properties"].items() if k not in {"type"}}
        tipos.append({
            "tipo": tipo, "grupo": grupo, "titulo": titulo, "descripcion": descripcion,
            "campos": campos, "requeridos": [r for r in js.get("required", []) if r != "type"],
            "defs": js.get("$defs", {}), "comunes": list(COMUNES),
        })
    return {"tipos": tipos, "grupos": list(dict.fromkeys(g for g, _, _ in GRUPOS.values()))}


def validar(datos: Any) -> Workflow:
    if not isinstance(datos, dict):
        raise ErrorApi(400, "se esperaba el workflow como objeto")
    try:
        return Workflow.model_validate(datos)
    except ValidationError as exc:
        lineas = []
        for e in exc.errors():
            donde = ".".join(str(x) for x in e["loc"]) or "(raiz)"
            lineas.append(f"{donde}: {e['msg']}")
        raise ErrorApi(400, "\n".join(lineas[:12])) from None


def como_datos(flujo: Workflow) -> dict[str, Any]:
    """El workflow como lo escribiria una persona: sin los valores por defecto."""
    return flujo.model_dump(mode="json", exclude_unset=True, by_alias=True)


def como_yaml(flujo: Workflow) -> str:
    return yaml.safe_dump(como_datos(flujo), sort_keys=False, allow_unicode=True, width=100)


def plan(flujo: Workflow) -> dict[str, Any]:
    filas = planificar(flujo)
    return {"plan": [asdict(f) for f in filas], "resumen": asdict(resumir(filas))}


def costos(ledger: Ledger, nombre: str, ultimas: int = 50) -> dict[str, Any]:
    """Mediana por paso de lo que gasto en las ultimas corridas reales de este workflow."""
    corridas = [f["id"] for f in ledger.conn.execute(
        "SELECT id FROM runs WHERE task_id = ? ORDER BY started_at DESC LIMIT ?", (nombre, ultimas)
    ).fetchall()]
    if not corridas:
        return {"corridas": 0, "pasos": {}}
    marcas = ",".join("?" * len(corridas))
    filas = ledger.conn.execute(
        "SELECT run_id, substr(purpose, 6) AS paso,"
        " SUM(input_tokens + output_tokens + cache_read_tokens + cache_write_tokens) AS tokens,"
        " SUM(cost_usd) AS costo, MAX(egress) AS egress, MAX(tier) AS tier, COUNT(*) AS llamadas"
        f" FROM calls WHERE run_id IN ({marcas}) AND purpose LIKE 'flow:%' GROUP BY run_id, purpose",
        corridas,
    ).fetchall()
    por_paso: dict[str, list[Any]] = {}
    for f in filas:
        por_paso.setdefault(f["paso"], []).append(f)
    pasos = {}
    for paso, lista in por_paso.items():
        con_costo = [f["costo"] for f in lista if f["costo"] is not None]
        pasos[paso] = {
            "corridas": len(lista),
            "tokens": int(statistics.median(f["tokens"] for f in lista)),
            "costo": statistics.median(con_costo) if con_costo else None,
            "egress": any(f["egress"] for f in lista),
            "tier": lista[0]["tier"],
        }
    return {"corridas": len(corridas), "pasos": pasos}


def rutas(workflows: Path, ledger: Path) -> list[Route]:
    def api_esquema(_request: Request) -> JSONResponse:
        return JSONResponse(esquema())

    async def api_validar(request: Request) -> JSONResponse:
        datos = await cuerpo(request, limite=400_000)
        try:
            flujo = validar(datos.get("flujo"))
        except ErrorApi as exc:
            return JSONResponse({"ok": False, "error": str(exc)})
        return JSONResponse({"ok": True, "yaml": como_yaml(flujo), **plan(flujo)})

    async def guardar(request: Request, *, nuevo: bool) -> JSONResponse:
        datos = await cuerpo(request, limite=400_000)
        nombre = request.path_params.get("archivo") or str(datos.get("archivo") or "")
        ruta = archivo_en(workflows, nombre, existente=False)
        if ruta is None:
            raise ErrorApi(400, "nombre de archivo invalido: letras, numeros, . _ - y terminado en .yml")
        if nuevo and ruta.exists():
            raise ErrorApi(409, f"ya existe {ruta.name}")
        if not nuevo and not ruta.is_file():
            raise ErrorApi(404, "workflow no encontrado")
        flujo = validar(datos.get("flujo"))
        workflows.mkdir(parents=True, exist_ok=True)
        if ruta.exists():
            copias = Path("runs") / "workflows-anteriores"
            copias.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ruta, copias / f"{ruta.stem}.{datetime.now(UTC):%Y%m%dT%H%M%S}{ruta.suffix}")
        temporal = ruta.with_name(ruta.name + ".tmp")
        temporal.write_text(como_yaml(flujo), encoding="utf-8")
        temporal.replace(ruta)
        return JSONResponse({"archivo": ruta.name, "flujo": como_datos(flujo), **plan(flujo)},
                            status_code=201 if nuevo else 200)

    async def api_crear(request: Request) -> JSONResponse:
        return await guardar(request, nuevo=True)

    async def api_guardar(request: Request) -> JSONResponse:
        return await guardar(request, nuevo=False)

    def api_costos(request: Request) -> JSONResponse:
        ruta = archivo_en(workflows, request.path_params["archivo"])
        if ruta is None:
            raise ErrorApi(404, "workflow no encontrado")
        try:
            nombre = yaml.safe_load(ruta.read_text(encoding="utf-8")).get("name", "")
        except (OSError, yaml.YAMLError, AttributeError):
            raise ErrorApi(400, "el archivo no es un workflow valido") from None
        led = Ledger(ledger)
        try:
            return JSONResponse(costos(led, str(nombre)))
        finally:
            led.close()

    return [
        Route("/api/editor/esquema", api_esquema, methods=["GET"]),
        Route("/api/editor/validar", api_validar, methods=["POST"]),
        Route("/api/workflows", api_crear, methods=["POST"]),
        Route("/api/workflows/{archivo}", api_guardar, methods=["PUT"]),
        Route("/api/workflows/{archivo}/costos", api_costos, methods=["GET"]),
    ]
