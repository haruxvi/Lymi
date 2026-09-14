"""MCP de punta a punta contra servidores reales, por stdio y por HTTP.

Hasta aqui el cliente MCP estaba escrito pero nunca habia hablado con un servidor
de verdad. Estas pruebas levantan uno y ejecutan workflows que lo usan a traves
del motor completo: plantillas, ledger, errores y entorno.
"""

from __future__ import annotations

import asyncio
import importlib.util
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

from lymi.flows.engine import ejecutar_flujo
from lymi.flows.schema import Workflow
from lymi.ledger import Ledger

SERVIDOR = Path(__file__).parent / "servidores" / "eco_mcp.py"
HERRAMIENTAS = ["eco", "suma", "leer_env", "falla", "crashea"]
STDIO = {"type": "mcp", "command": sys.executable, "args": [str(SERVIDOR)], "tools": HERRAMIENTAS}


@pytest.fixture
def ledger(tmp_path):
    led = Ledger(tmp_path / "mcp.sqlite3")
    yield led
    led.close()


def _correr(flujo: Workflow, inputs: dict | None = None, **opciones):
    return asyncio.run(ejecutar_flujo(flujo, inputs or {}, **opciones))


def _flujo(integracion: dict, pasos: list[dict], inputs: dict | None = None) -> Workflow:
    return Workflow.model_validate(
        {"name": "mcp_e2e", "inputs": inputs or {}, "integrations": {"eco": integracion}, "steps": pasos}
    )


def _paso(id_: str, herramienta: str, args: dict | None = None, **extra) -> dict:
    return {
        "id": id_, "type": "tool", "integration": "eco", "tool": herramienta,
        "args": args or {}, "side_effect": False, **extra,
    }


class TestStdio:
    def test_llamada_de_texto(self, ledger: Ledger) -> None:
        flujo = _flujo(STDIO, [_paso("a", "eco", {"texto": "{{ inputs.x }}"})], inputs={"x": {}})
        r = _correr(flujo, {"x": "hola"}, ledger=ledger)
        assert r.ok, r.detalle
        assert r.salidas["a"] == "hola"

    def test_salida_estructurada_encadenada(self, ledger: Ledger) -> None:
        flujo = _flujo(STDIO, [
            _paso("sumar", "suma", {"a": 2, "b": 3}),
            _paso("repetir", "eco", {"texto": "total={{ steps.sumar.output.total }}"}),
        ])
        r = _correr(flujo, ledger=ledger)
        assert r.ok, r.detalle
        assert r.salidas["sumar"] == {"total": 5}
        assert r.salidas["repetir"] == "total=5"

    def test_error_declarado_llega_con_su_mensaje(self, ledger: Ledger) -> None:
        r = _correr(_flujo(STDIO, [_paso("a", "falla", retries=2)]), ledger=ledger)
        assert not r.ok
        assert r.pasos[0].intentos == 1
        assert "fallo a proposito" in r.pasos[0].detalle

    def test_fallo_inesperado_se_detecta_sin_filtrar_el_detalle(self, ledger: Ledger) -> None:
        # El SDK no envia al cliente el mensaje de una excepcion inesperada, y esta
        # bien. Lo que importa es que lymi lo trate como fallo y no como exito.
        r = _correr(_flujo(STDIO, [_paso("a", "crashea", retries=2)]), ledger=ledger)
        assert not r.ok
        assert r.pasos[0].status == "fallo"
        assert r.pasos[0].intentos == 1
        assert "detalle interno" not in r.pasos[0].detalle

    def test_el_servidor_solo_recibe_las_variables_declaradas(self, ledger: Ledger, monkeypatch) -> None:
        monkeypatch.setenv("SECRETO_AJENO", "no-debe-llegar")
        integracion = {**STDIO, "env": {"SALUDO": "${SALUDO}"}}
        flujo = _flujo(integracion, [
            _paso("declarada", "leer_env", {"nombre": "SALUDO"}),
            _paso("ajena", "leer_env", {"nombre": "SECRETO_AJENO"}),
        ])
        r = _correr(flujo, ledger=ledger, entorno={"SALUDO": "hola", "SECRETO_AJENO": "no-debe-llegar"})
        assert r.ok, r.detalle
        assert r.salidas["declarada"] == "hola"
        assert r.salidas["ajena"] == "<ausente>"

    def test_cada_llamada_queda_en_el_ledger_como_egress(self, ledger: Ledger) -> None:
        flujo = _flujo(STDIO, [_paso("a", "eco", {"texto": "x"}), _paso("b", "eco", {"texto": "y"})])
        r = _correr(flujo, ledger=ledger)
        assert r.ok, r.detalle
        filas = ledger.conn.execute(
            "SELECT provider, model, egress, ok FROM calls WHERE run_id = ? ORDER BY seq", (r.run_id,)
        ).fetchall()
        assert [(f["provider"], f["model"], f["egress"], f["ok"]) for f in filas] == [("mcp", "eco.eco", 1, 1)] * 2

    def test_servidor_que_no_arranca(self, ledger: Ledger, tmp_path) -> None:
        roto = tmp_path / "roto.py"
        roto.write_text("raise SystemExit(3)\n", encoding="utf-8")
        flujo = _flujo({**STDIO, "args": [str(roto)]}, [_paso("a", "eco", {"texto": "x"}, retries=2)])
        r = _correr(flujo, ledger=ledger)
        assert not r.ok
        assert r.pasos[0].intentos == 1


def _cargar_servidor():
    spec = importlib.util.spec_from_file_location("eco_mcp_http", SERVIDOR)
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo.servidor


@pytest.fixture(scope="module")
def url_http():
    import uvicorn

    app = _cargar_servidor().streamable_http_app()
    enchufe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    enchufe.bind(("127.0.0.1", 0))
    puerto = enchufe.getsockname()[1]

    servidor = uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="on"))
    hilo = threading.Thread(target=servidor.run, kwargs={"sockets": [enchufe]}, daemon=True)
    hilo.start()

    limite = time.monotonic() + 15
    while not servidor.started:
        if time.monotonic() > limite:
            pytest.fail("el servidor MCP por HTTP no arranco en 15 s")
        time.sleep(0.05)

    yield f"http://127.0.0.1:{puerto}/mcp"

    servidor.should_exit = True
    hilo.join(timeout=10)


def _http(url: str) -> dict:
    return {"type": "mcp", "transport": "http", "url": url, "tools": HERRAMIENTAS}


class TestHttp:
    def test_llamadas_por_http(self, ledger: Ledger, url_http: str) -> None:
        flujo = _flujo(_http(url_http), [_paso("a", "eco", {"texto": "por http"}), _paso("b", "suma", {"a": 40, "b": 2})])
        r = _correr(flujo, ledger=ledger)
        assert r.ok, r.detalle
        assert r.salidas == {"a": "por http", "b": {"total": 42}}

    def test_error_declarado_por_http(self, ledger: Ledger, url_http: str) -> None:
        r = _correr(_flujo(_http(url_http), [_paso("a", "falla")]), ledger=ledger)
        assert not r.ok
        assert "fallo a proposito" in r.pasos[0].detalle

    def test_fallo_inesperado_por_http(self, ledger: Ledger, url_http: str) -> None:
        r = _correr(_flujo(_http(url_http), [_paso("a", "crashea")]), ledger=ledger)
        assert not r.ok
        assert r.pasos[0].status == "fallo"
        assert "detalle interno" not in r.pasos[0].detalle
