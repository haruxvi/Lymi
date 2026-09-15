"""Aplicacion web local de lymi.

Solo escucha en loopback, y se defiende como si eso no bastara:

- **Host permitido explicito.** Sin esto, un sitio malicioso podria reapuntar su
  dominio a 127.0.0.1 (DNS rebinding) y hablar con la API desde tu navegador.
- **Token por proceso en toda la API.** La pagina lo recibe incrustado; otro
  origen no puede leerlo porque no hay CORS. Tambien se rechaza un Origin ajeno.
- **CSP estricta sin inline.** Ni scripts ni estilos inyectados se ejecutan, y la
  pagina no puede pedir nada a otro dominio: la interfaz no genera egress.
- **Sin payloads.** La API lee el ledger, que solo guarda hashes.
"""

from __future__ import annotations

import hmac
import json
import re
import secrets
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.datastructures import MutableHeaders
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from lymi import control
from lymi.flows.engine import EntradaError
from lymi.flows.plan import planificar, resumir
from lymi.flows.schema import WorkflowError, cargar
from lymi.ledger import Ledger
from lymi.ui import datos, tema
from lymi.ui.trabajos import TrabajoError, Trabajos

ESTATICOS = Path(__file__).with_name("static")
CABECERA_TOKEN = "x-lymi-token"
LIMITE_CUERPO = 64_000
ARCHIVO_WORKFLOW = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}\.ya?ml$")
ID_CORRIDA = re.compile(r"^[0-9a-f]{12}$")
ID_TRABAJO = re.compile(r"^[0-9a-f]{10}$")

CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; font-src 'self'; base-uri 'none'; form-action 'none'; "
    "frame-ancestors 'none'"
)


@dataclass(slots=True)
class ConfigUI:
    ledger: Path
    workflows: Path
    memoria: Path
    hosts: frozenset[str]
    """Valores exactos aceptados en la cabecera Host, con puerto."""
    token: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    proveedores: Callable[[], Any] | None = None
    cablear: Callable[[], Any] | None = None
    diagnosticar: Callable[..., Any] | None = None
    vencimiento: float = 300.0


class ErrorApi(Exception):
    def __init__(self, estado: int, mensaje: str) -> None:
        super().__init__(mensaje)
        self.estado = estado


class Guardia:
    """Middleware ASGI: host, token, origen y cabeceras de seguridad."""

    def __init__(self, app: ASGIApp, config: ConfigUI) -> None:
        self.app = app
        self.config = config

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        cabeceras = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        if cabeceras.get("host", "") not in self.config.hosts:
            await PlainTextResponse("host no permitido", status_code=421)(scope, receive, send)
            return

        es_api = scope["path"].startswith("/api/")
        if es_api:
            token = cabeceras.get(CABECERA_TOKEN, "").encode()
            if not hmac.compare_digest(token, self.config.token.encode()):
                await JSONResponse({"error": "token invalido"}, status_code=403)(scope, receive, send)
                return
            origen = cabeceras.get("origin")
            if origen is not None and origen.split("://", 1)[-1] not in self.config.hosts:
                await JSONResponse({"error": "origen no permitido"}, status_code=403)(scope, receive, send)
                return

        async def enviar(mensaje: Message) -> None:
            if mensaje["type"] == "http.response.start":
                h = MutableHeaders(scope=mensaje)
                h["Content-Security-Policy"] = CSP
                h["X-Content-Type-Options"] = "nosniff"
                h["Referrer-Policy"] = "no-referrer"
                h["X-Frame-Options"] = "DENY"
                h["Cross-Origin-Opener-Policy"] = "same-origin"
                # La API nunca se guarda; la pagina y los estaticos se revalidan siempre:
                # tras actualizar lymi el navegador no debe seguir con un app.js viejo.
                h["Cache-Control"] = "no-store" if es_api else "no-cache"
            await send(mensaje)

        await self.app(scope, receive, enviar)


def _entero(valor: str | None, defecto: int, minimo: int, maximo: int) -> int:
    try:
        numero = int(valor) if valor is not None else defecto
    except ValueError:
        numero = defecto
    return max(minimo, min(maximo, numero))


async def _cuerpo(request: Request) -> dict[str, Any]:
    crudo = b""
    async for trozo in request.stream():
        crudo += trozo
        if len(crudo) > LIMITE_CUERPO:
            raise ErrorApi(413, f"el cuerpo supera {LIMITE_CUERPO} bytes")
    try:
        valor = json.loads(crudo or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ErrorApi(400, "el cuerpo no es JSON valido") from None
    if not isinstance(valor, dict):
        raise ErrorApi(400, "se esperaba un objeto JSON")
    return valor


def _ruta_workflow(carpeta: Path, nombre: str) -> Path | None:
    """El archivo pedido, solo si es un YAML directamente dentro de la carpeta."""
    if not ARCHIVO_WORKFLOW.match(nombre):
        return None
    ruta = carpeta / nombre
    try:
        if ruta.resolve().parent != carpeta.resolve() or not ruta.is_file():
            return None
    except OSError:
        return None
    return ruta


def crear_app_ui(config: ConfigUI) -> Starlette:
    trabajos = Trabajos(
        ledger=config.ledger,
        memoria=config.memoria,
        proveedores=config.proveedores,
        cablear=config.cablear,
        vencimiento=config.vencimiento,
    )

    def con_ledger(leer: Callable[[Ledger], Any]) -> Any:
        ledger = Ledger(config.ledger)
        try:
            return leer(ledger)
        finally:
            ledger.close()

    # ------------------------------------------------------------ pagina

    def pagina(_request: Request) -> HTMLResponse:
        html = (ESTATICOS / "index.html").read_text(encoding="utf-8")
        return HTMLResponse(html.replace("__LYMI_TOKEN__", config.token))

    # ------------------------------------------------------------ lecturas

    def api_resumen(_request: Request) -> JSONResponse:
        resumen, ultimas = con_ledger(lambda led: (datos.resumen(led), datos.corridas(led, 6)))
        return JSONResponse(
            {**resumen, "ultimas": ultimas, "trabajos_activos": trabajos.activos(), "detenido": control.detenido()}
        )

    async def api_parar(request: Request) -> JSONResponse:
        cuerpo = await _cuerpo(request)
        motivo = str(cuerpo.get("motivo") or "detenido desde la interfaz")[:200]
        control.detener(motivo)
        return JSONResponse({"detenido": True, "aprobaciones_revocadas": trabajos.revocar_pendientes()})

    async def api_reanudar(_request: Request) -> JSONResponse:
        return JSONResponse({"detenido": False, "estaba_detenido": control.reanudar()})

    def api_proveedores(request: Request) -> JSONResponse:
        probar = request.query_params.get("probar") == "1"
        if config.diagnosticar is None:
            from lymi.doctor import diagnosticar
        else:
            diagnosticar = config.diagnosticar
        diagnostico = diagnosticar(probar_claude=probar)
        return JSONResponse(
            {
                "probado": probar,
                "tier_local": diagnostico.tier_local,
                "tier_remoto": diagnostico.tier_remoto,
                "chequeos": [
                    {"nombre": c.nombre, "estado": str(c.estado), "detalle": c.detalle, "arreglo": c.arreglo}
                    for c in diagnostico.chequeos
                ],
            }
        )

    def api_corridas(request: Request) -> JSONResponse:
        limite = _entero(request.query_params.get("limite"), 50, 1, 500)
        return JSONResponse(con_ledger(lambda led: datos.corridas(led, limite)))

    def api_corrida(request: Request) -> JSONResponse:
        run_id = request.path_params["run_id"]
        detalle = con_ledger(lambda led: datos.corrida(led, run_id)) if ID_CORRIDA.match(run_id) else None
        if detalle is None:
            raise ErrorApi(404, "corrida no encontrada")
        return JSONResponse(detalle)

    def api_egress(request: Request) -> JSONResponse:
        limite = _entero(request.query_params.get("limite"), 200, 1, 1000)
        return JSONResponse(con_ledger(lambda led: datos.egress(led, limite)))

    def api_workflows(_request: Request) -> JSONResponse:
        lista: list[dict[str, Any]] = []
        carpeta = config.workflows
        if carpeta.is_dir():
            for ruta in sorted(carpeta.iterdir()):
                if not ruta.is_file() or not ARCHIVO_WORKFLOW.match(ruta.name):
                    continue
                item: dict[str, Any] = {"archivo": ruta.name}
                try:
                    flujo = cargar(ruta)
                except WorkflowError as exc:
                    item["error"] = str(exc)
                else:
                    item.update(
                        nombre=flujo.name,
                        descripcion=flujo.description,
                        pasos=len(flujo.steps),
                        resumen=asdict(resumir(planificar(flujo))),
                    )
                lista.append(item)
        return JSONResponse({"carpeta": str(carpeta), "workflows": lista})

    def api_workflow(request: Request) -> JSONResponse:
        ruta = _ruta_workflow(config.workflows, request.path_params["archivo"])
        if ruta is None:
            raise ErrorApi(404, "workflow no encontrado")
        texto = ruta.read_text(encoding="utf-8")
        try:
            flujo = cargar(ruta)
        except WorkflowError as exc:
            return JSONResponse({"archivo": ruta.name, "yaml": texto, "error": str(exc)})
        filas = planificar(flujo)
        return JSONResponse(
            {
                "archivo": ruta.name,
                "nombre": flujo.name,
                "descripcion": flujo.description,
                "yaml": texto,
                "entradas": {nombre: spec.model_dump() for nombre, spec in flujo.inputs.items()},
                "plan": [asdict(f) for f in filas],
                "tiers": {p.id: getattr(p, "tier", None) for p in flujo.steps},
                "resumen": asdict(resumir(filas)),
            }
        )

    # ------------------------------------------------------------ trabajos

    async def api_correr_workflow(request: Request) -> JSONResponse:
        ruta = _ruta_workflow(config.workflows, request.path_params["archivo"])
        if ruta is None:
            raise ErrorApi(404, "workflow no encontrado")
        cuerpo = await _cuerpo(request)
        entradas = cuerpo.get("entradas", {})
        if not isinstance(entradas, dict):
            raise ErrorApi(400, "entradas debe ser un objeto")
        return JSONResponse(trabajos.lanzar_workflow(ruta, entradas), status_code=202)

    async def api_bench(request: Request) -> JSONResponse:
        cuerpo = await _cuerpo(request)
        if cuerpo.get("tarea", "snake") != "snake":
            raise ErrorApi(400, "por ahora solo esta la tarea snake")
        vista = trabajos.lanzar_bench(
            demo=cuerpo.get("demo") is True,
            calentar=cuerpo.get("calentar", True) is True,
            confirmar=cuerpo.get("confirmar") is True,
        )
        return JSONResponse(vista, status_code=202)

    def api_trabajos(_request: Request) -> JSONResponse:
        return JSONResponse(trabajos.listar())

    def api_trabajo(request: Request) -> JSONResponse:
        trabajo_id = request.path_params["trabajo_id"]
        vista = trabajos.obtener(trabajo_id) if ID_TRABAJO.match(trabajo_id) else None
        if vista is None:
            raise ErrorApi(404, "trabajo no encontrado")
        return JSONResponse(vista)

    async def api_decidir(request: Request) -> JSONResponse:
        trabajo_id = request.path_params["trabajo_id"]
        if not ID_TRABAJO.match(trabajo_id):
            raise ErrorApi(404, "trabajo no encontrado")
        cuerpo = await _cuerpo(request)
        try:
            trabajos.decidir(trabajo_id, str(cuerpo.get("decision", "")))
        except KeyError:
            raise ErrorApi(404, "trabajo no encontrado") from None
        return JSONResponse({"ok": True})

    # ------------------------------------------------------------ tema

    def api_tema(_request: Request) -> JSONResponse:
        actual = tema.leer(tema.ruta_tema())
        presets = [{"id": k, "nombre": v["nombre"], "tinta": v["tinta"]} for k, v in tema.PRESETS.items()]
        return JSONResponse({**actual, "ruta": str(tema.ruta_tema()), "presets": presets})

    async def api_guardar_tema(request: Request) -> JSONResponse:
        cuerpo = await _cuerpo(request)
        tema.escribir(tema.ruta_tema(), cuerpo.get("nombre"), cuerpo.get("tinta"))
        return JSONResponse(tema.leer(tema.ruta_tema()))

    # ------------------------------------------------------------ errores

    def error_api(_request: Request, exc: Exception) -> JSONResponse:
        estados = {ErrorApi: None, TrabajoError: 409, WorkflowError: 400, EntradaError: 400,
                   tema.TemaError: 400, ValueError: 400}
        for tipo, estado in estados.items():
            if isinstance(exc, tipo):
                codigo = exc.estado if isinstance(exc, ErrorApi) else estado
                return JSONResponse({"error": str(exc)}, status_code=codigo)
        return JSONResponse({"error": "error interno"}, status_code=500)  # pragma: no cover

    rutas = [
        Route("/", pagina, methods=["GET"]),
        Route("/api/resumen", api_resumen, methods=["GET"]),
        Route("/api/parar", api_parar, methods=["POST"]),
        Route("/api/reanudar", api_reanudar, methods=["POST"]),
        Route("/api/proveedores", api_proveedores, methods=["GET"]),
        Route("/api/corridas", api_corridas, methods=["GET"]),
        Route("/api/corridas/{run_id}", api_corrida, methods=["GET"]),
        Route("/api/egress", api_egress, methods=["GET"]),
        Route("/api/workflows", api_workflows, methods=["GET"]),
        Route("/api/workflows/{archivo}", api_workflow, methods=["GET"]),
        Route("/api/workflows/{archivo}/correr", api_correr_workflow, methods=["POST"]),
        Route("/api/bench", api_bench, methods=["POST"]),
        Route("/api/trabajos", api_trabajos, methods=["GET"]),
        Route("/api/trabajos/{trabajo_id}", api_trabajo, methods=["GET"]),
        Route("/api/trabajos/{trabajo_id}/aprobacion", api_decidir, methods=["POST"]),
        Route("/api/tema", api_tema, methods=["GET"]),
        Route("/api/tema", api_guardar_tema, methods=["PUT"]),
        Mount("/static", app=StaticFiles(directory=ESTATICOS), name="static"),
    ]
    app = Starlette(
        routes=rutas,
        middleware=[Middleware(Guardia, config=config)],
        exception_handlers={
            ErrorApi: error_api,
            TrabajoError: error_api,
            WorkflowError: error_api,
            EntradaError: error_api,
            tema.TemaError: error_api,
            ValueError: error_api,
        },
    )
    app.state.trabajos = trabajos
    return app
