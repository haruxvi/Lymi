"""Pruebas de la interfaz local (`lymi ui`).

Dos cosas importan tanto como que funcione: que nadie mas que la pagina local
pueda hablar con la API, y que ningun efecto corra sin una decision explicita.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
import yaml
from starlette.testclient import TestClient

from lymi.bench.demo import MATERIAL_DEMO, SNAKE_SOLUCION
from lymi.bench.strategies import BaselineAgent, LymiAgent, _trozos
from lymi.bench.wiring import Cableado
from lymi.doctor import Chequeo, Diagnostico, Estado
from lymi.ledger import Billing, CallRecord, Ledger
from lymi.providers.fake import ScriptedClient, ScriptedLocalClient, ScriptedTurn
from lymi.ui.app import ConfigUI, crear_app_ui

TOKEN = "token-de-prueba"

TRANSFORMA = {
    "name": "ficha_simple",
    "description": "Arma una ficha sin llamar a nadie.",
    "inputs": {"correo": {"type": "string", "description": "Texto del correo."}},
    "steps": [{"id": "ficha", "type": "transform", "set": {"correo": "{{ inputs.correo }}"}}],
}

CON_EFECTO = {
    "name": "aviso_externo",
    "integrations": {"api": {"type": "http", "allow_hosts": ["api.ejemplo.com"]}},
    "steps": [{"id": "avisar", "type": "http", "integration": "api", "method": "POST",
               "url": "https://api.ejemplo.com/x", "body": {"a": 1}}],
}


def _diagnostico(probar_claude: bool = False) -> Diagnostico:
    return Diagnostico([
        Chequeo("ollama servidor", Estado.OK, "1 modelos"),
        Chequeo("claude code", Estado.OK if probar_claude else Estado.FALTA, "probado" if probar_claude else "sin probar"),
    ])


def _cableado_guionado() -> Cableado:
    base = ScriptedClient([
        ScriptedTurn("ok", input_tokens=5, output_tokens=1),  # calentamiento
        ScriptedTurn(SNAKE_SOLUCION, input_tokens=6000, output_tokens=900),
    ])
    remoto_lymi = ScriptedClient([ScriptedTurn(SNAKE_SOLUCION, input_tokens=200, output_tokens=900)])
    local = ScriptedLocalClient(
        turns=[ScriptedTurn("ficha", input_tokens=1000, output_tokens=40) for _ in _trozos(MATERIAL_DEMO)]
    )
    return Cableado(base=BaselineAgent(base), lymi=LymiAgent(remoto_lymi, local), remoto="guionado", local="guionado")


@pytest.fixture
def config(tmp_path, monkeypatch) -> ConfigUI:
    monkeypatch.setenv("LYMI_TEMA", str(tmp_path / "theme.toml"))
    monkeypatch.setenv("LYMI_PARADA", str(tmp_path / "PARAR"))
    carpeta = tmp_path / "workflows"
    carpeta.mkdir()
    return ConfigUI(
        ledger=tmp_path / "ledger.sqlite3",
        workflows=carpeta,
        memoria=tmp_path / "aprobaciones.sqlite3",
        hosts=frozenset({"testserver"}),
        token=TOKEN,
        proveedores=lambda: (None, None, None, None),
        cablear=_cableado_guionado,
        diagnosticar=_diagnostico,
        vencimiento=10.0,
    )


@pytest.fixture
def cliente(config):
    with TestClient(crear_app_ui(config)) as c:
        c.headers.update({"X-Lymi-Token": TOKEN})
        yield c


def _workflow(config: ConfigUI, datos: dict, nombre: str | None = None) -> str:
    archivo = nombre or f"{datos['name']}.yml"
    (config.workflows / archivo).write_text(yaml.safe_dump(datos), encoding="utf-8")
    return archivo


def _esperar(cliente, trabajo_id: str, estados=("ok", "fallo", "error"), timeout: float = 30.0) -> dict:
    limite = time.monotonic() + timeout
    trabajo: dict = {}
    while time.monotonic() < limite:
        trabajo = cliente.get(f"/api/trabajos/{trabajo_id}").json()
        if trabajo["estado"] in estados:
            return trabajo
        time.sleep(0.05)
    raise AssertionError(f"el trabajo no llego a {estados}: {trabajo}")


class TestDefensas:
    def test_host_ajeno_se_rechaza(self, config) -> None:
        # DNS rebinding: un dominio ajeno reapuntado a 127.0.0.1.
        with TestClient(crear_app_ui(config), base_url="http://malo.example") as c:
            respuesta = c.get("/api/resumen", headers={"X-Lymi-Token": TOKEN})
        assert respuesta.status_code == 421

    def test_api_sin_token(self, config) -> None:
        with TestClient(crear_app_ui(config)) as c:
            assert c.get("/api/resumen").status_code == 403

    def test_token_incorrecto(self, config) -> None:
        with TestClient(crear_app_ui(config)) as c:
            assert c.get("/api/resumen", headers={"X-Lymi-Token": "otro"}).status_code == 403

    def test_origen_ajeno(self, cliente) -> None:
        respuesta = cliente.post("/api/bench", json={"demo": True}, headers={"Origin": "http://malo.example"})
        assert respuesta.status_code == 403

    def test_pagina_trae_token_y_cabeceras(self, cliente) -> None:
        respuesta = cliente.get("/")
        assert respuesta.status_code == 200
        assert f'content="{TOKEN}"' in respuesta.text
        assert "script-src 'self'" in respuesta.headers["content-security-policy"]
        assert respuesta.headers["x-content-type-options"] == "nosniff"
        assert respuesta.headers["x-frame-options"] == "DENY"

    def test_la_api_no_se_cachea(self, cliente) -> None:
        assert cliente.get("/api/resumen").headers["cache-control"] == "no-store"

    def test_pagina_y_estaticos_se_revalidan(self, cliente) -> None:
        # Paso de verdad: tras cambiar app.css el navegador siguio con la copia
        # vieja. Una app local que se actualiza no puede servir estaticos rancios.
        assert cliente.get("/").headers["cache-control"] == "no-cache"
        assert cliente.get("/static/app.css").headers["cache-control"] == "no-cache"

    def test_estaticos(self, cliente) -> None:
        respuesta = cliente.get("/static/app.js")
        assert respuesta.status_code == 200
        assert "javascript" in respuesta.headers["content-type"]

    def test_la_pagina_no_pide_nada_a_internet(self) -> None:
        # Sin CDN ni fuentes remotas: la interfaz no genera egress.
        estaticos = Path(__file__).parents[1] / "src" / "lymi" / "ui" / "static"
        for archivo in ("index.html", "app.js", "app.css"):
            texto = (estaticos / archivo).read_text(encoding="utf-8")
            assert "https://" not in texto and "http://" not in texto, archivo

    def test_cuerpo_invalido(self, cliente) -> None:
        respuesta = cliente.post("/api/bench", content=b"no es json", headers={"Content-Type": "application/json"})
        assert respuesta.status_code == 400


class TestLedger:
    def test_resumen_vacio(self, cliente) -> None:
        datos = cliente.get("/api/resumen").json()
        assert datos["corridas"] == 0
        assert datos["ultimas"] == []

    def test_corridas_y_detalle_sin_payload(self, cliente, config) -> None:
        ledger = Ledger(config.ledger)
        try:
            with ledger.run("snake", "baseline", Billing.API) as run:
                run.record(CallRecord(provider="anthropic", model="claude-opus-5", billing=Billing.API,
                                      input_tokens=1000, output_tokens=200, egress=True,
                                      payload="DATO SENSIBLE QUE NUNCA DEBE VOLVER"))
        finally:
            ledger.close()

        corridas = cliente.get("/api/corridas").json()
        assert [c["run_id"] for c in corridas] == [run.run_id]

        respuesta = cliente.get(f"/api/corridas/{run.run_id}")
        detalle = respuesta.json()
        assert detalle["remote_tokens"] == 1200
        assert detalle["llamadas"][0]["payload_sha256"]
        assert "DATO SENSIBLE" not in respuesta.text

        egress = cliente.get("/api/egress").json()
        assert egress[0]["run_id"] == run.run_id

    def test_corrida_inexistente(self, cliente) -> None:
        assert cliente.get("/api/corridas/0123456789ab").status_code == 404
        assert cliente.get("/api/corridas/no-es-un-id").status_code == 404


class TestProveedores:
    def test_sin_probar_por_defecto(self, cliente) -> None:
        datos = cliente.get("/api/proveedores").json()
        assert datos["probado"] is False
        assert {c["nombre"] for c in datos["chequeos"]} == {"ollama servidor", "claude code"}

    def test_probar_es_explicito(self, cliente) -> None:
        datos = cliente.get("/api/proveedores?probar=1").json()
        assert datos["probado"] is True


class TestWorkflows:
    def test_lista_con_plan_y_errores(self, cliente, config) -> None:
        _workflow(config, TRANSFORMA)
        (config.workflows / "roto.yml").write_text("name: [", encoding="utf-8")
        (config.workflows / "notas.txt").write_text("no es yaml", encoding="utf-8")

        datos = cliente.get("/api/workflows").json()
        por_archivo = {w["archivo"]: w for w in datos["workflows"]}
        assert set(por_archivo) == {"ficha_simple.yml", "roto.yml"}
        assert por_archivo["ficha_simple.yml"]["resumen"]["gratis"] == 1
        assert "error" in por_archivo["roto.yml"]

    def test_detalle(self, cliente, config) -> None:
        archivo = _workflow(config, TRANSFORMA)
        datos = cliente.get(f"/api/workflows/{archivo}").json()
        assert datos["nombre"] == "ficha_simple"
        assert datos["entradas"]["correo"]["type"] == "string"
        assert datos["plan"][0]["costo"] == "gratis"

    @pytest.mark.parametrize("nombre", ["..%2F..%2Fpyproject.toml", "pyproject.toml", ".oculto.yml"])
    def test_nombres_fuera_de_la_carpeta(self, cliente, nombre) -> None:
        assert cliente.get(f"/api/workflows/{nombre}").status_code == 404

    def test_correr_sin_efectos(self, cliente, config) -> None:
        archivo = _workflow(config, TRANSFORMA)
        respuesta = cliente.post(f"/api/workflows/{archivo}/correr", json={"entradas": {"correo": "hola"}})
        assert respuesta.status_code == 202

        trabajo = _esperar(cliente, respuesta.json()["id"])
        assert trabajo["estado"] == "ok"
        assert trabajo["resultado"]["pasos"][0]["estado"] == "ok"
        assert cliente.get(f"/api/corridas/{trabajo['resultado']['run_id']}").status_code == 200

    def test_entradas_invalidas(self, cliente, config) -> None:
        archivo = _workflow(config, TRANSFORMA)
        respuesta = cliente.post(f"/api/workflows/{archivo}/correr", json={"entradas": {}})
        assert respuesta.status_code == 400
        assert "correo" in respuesta.json()["error"]

    def test_un_efecto_espera_y_se_puede_rechazar(self, cliente, config) -> None:
        archivo = _workflow(config, CON_EFECTO)
        trabajo_id = cliente.post(f"/api/workflows/{archivo}/correr", json={}).json()["id"]

        esperando = _esperar(cliente, trabajo_id, estados=("esperando",))
        assert esperando["pendiente"]["destino"] == "api.ejemplo.com"
        assert esperando["pendiente"]["metodo"] == "POST"

        assert cliente.post(f"/api/trabajos/{trabajo_id}/aprobacion", json={"decision": "rechazar"}).status_code == 200
        final = _esperar(cliente, trabajo_id)
        assert final["estado"] == "fallo"
        assert final["resultado"]["pasos"][0]["estado"] == "rechazado"

    def test_sin_respuesta_vence_y_rechaza(self, config, tmp_path) -> None:
        config.vencimiento = 0.3
        archivo = _workflow(config, CON_EFECTO)
        with TestClient(crear_app_ui(config)) as c:
            c.headers.update({"X-Lymi-Token": TOKEN})
            trabajo_id = c.post(f"/api/workflows/{archivo}/correr", json={}).json()["id"]
            final = _esperar(c, trabajo_id)
        assert final["estado"] == "fallo"
        assert final["resultado"]["pasos"][0]["estado"] == "rechazado"

    def test_decisiones_invalidas(self, cliente, config) -> None:
        archivo = _workflow(config, TRANSFORMA)
        trabajo_id = cliente.post(f"/api/workflows/{archivo}/correr", json={"entradas": {"correo": "x"}}).json()["id"]
        _esperar(cliente, trabajo_id)
        assert cliente.post(f"/api/trabajos/{trabajo_id}/aprobacion", json={"decision": "tal vez"}).status_code == 400
        assert cliente.post(f"/api/trabajos/{trabajo_id}/aprobacion", json={"decision": "aprobar"}).status_code == 409
        assert cliente.post("/api/trabajos/0123456789/aprobacion", json={"decision": "aprobar"}).status_code == 404


class TestBench:
    def test_la_medicion_real_exige_confirmar(self, cliente) -> None:
        respuesta = cliente.post("/api/bench", json={"demo": False})
        assert respuesta.status_code == 400
        assert "gasta tokens" in respuesta.json()["error"]

    def test_demo_emite_recibo(self, cliente) -> None:
        trabajo_id = cliente.post("/api/bench", json={"demo": True}).json()["id"]
        trabajo = _esperar(cliente, trabajo_id)
        assert trabajo["estado"] == "ok", trabajo
        recibo = trabajo["resultado"]
        assert recibo["tipo"] == "recibo"
        assert recibo["demo"] is True
        assert recibo["base"]["run_id"] != recibo["lymi"]["run_id"]

    def test_real_calienta_la_cache_aparte(self, cliente, config) -> None:
        trabajo_id = cliente.post("/api/bench", json={"demo": False, "confirmar": True, "calentar": True}).json()["id"]
        trabajo = _esperar(cliente, trabajo_id)
        assert trabajo["estado"] == "ok", trabajo

        ledger = Ledger(config.ledger)
        try:
            variantes = [f["variant"] for f in ledger.conn.execute("SELECT variant FROM runs")]
        finally:
            ledger.close()
        assert "calentamiento" in variantes
        # El calentamiento no se suma a la linea base.
        assert trabajo["resultado"]["base"]["tokens"] == 6900


class TestParada:
    def test_detener_y_reanudar(self, cliente) -> None:
        assert cliente.get("/api/resumen").json()["detenido"] is False
        assert cliente.post("/api/parar", json={}).json()["detenido"] is True
        assert cliente.get("/api/resumen").json()["detenido"] is True
        assert cliente.post("/api/reanudar", json={}).json()["estaba_detenido"] is True
        assert cliente.get("/api/resumen").json()["detenido"] is False

    def test_detener_revoca_las_aprobaciones_pendientes(self, cliente, config) -> None:
        archivo = _workflow(config, CON_EFECTO)
        trabajo_id = cliente.post(f"/api/workflows/{archivo}/correr", json={}).json()["id"]
        _esperar(cliente, trabajo_id, estados=("esperando",))

        assert cliente.post("/api/parar", json={"motivo": "prueba"}).json()["aprobaciones_revocadas"] == 1
        final = _esperar(cliente, trabajo_id)
        assert final["estado"] == "fallo"
        assert final["resultado"]["pasos"][0]["estado"] == "rechazado"
        cliente.post("/api/reanudar", json={})


class TestTema:
    def test_por_defecto(self, cliente) -> None:
        datos = cliente.get("/api/tema").json()
        assert datos["nombre"] == "riso-rosa-menta"
        assert len(datos["presets"]) == 8

    def test_guardar_y_leer(self, cliente) -> None:
        tinta = {"papel": "#1e1e2e", "panel": "#313244", "texto": "#cdd6f4",
                 "remoto": "#fab387", "local": "#a6e3a1", "gris": "#9399b2"}
        assert cliente.put("/api/tema", json={"nombre": "catppuccin-mocha", "tinta": tinta}).status_code == 200
        datos = cliente.get("/api/tema").json()
        assert datos["nombre"] == "catppuccin-mocha"
        assert datos["tinta"]["remoto"] == "#fab387"

    @pytest.mark.parametrize(
        ("nombre", "cambio"),
        [
            ("bien", {"remoto": "rojo"}),
            ('mal"\n[inyeccion]', {}),
        ],
    )
    def test_rechaza_valores_invalidos(self, cliente, nombre, cambio) -> None:
        tinta = {"papel": "#000000", "panel": "#111111", "texto": "#ffffff",
                 "remoto": "#ff0000", "local": "#00ff00", "gris": "#888888", **cambio}
        assert cliente.put("/api/tema", json={"nombre": nombre, "tinta": tinta}).status_code == 400
