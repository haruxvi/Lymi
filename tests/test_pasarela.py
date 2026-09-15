"""Pruebas de la pasarela de egress en el Recorder y en el motor de workflows.

Lo que se verifica es lo que promete el proyecto: lo que recibe el proveedor
remoto no trae el secreto ni el dato personal, lo que ve el usuario si, y lo que
queda en el ledger como egress es exactamente lo que salio.
"""

from __future__ import annotations

from hashlib import sha256

import pytest
import yaml

from lymi.bench.runner import Recorder
from lymi.control import Detenido, Presupuesto, PresupuestoAgotado, detener
from lymi.flows.engine import correr
from lymi.flows.schema import Workflow
from lymi.ledger import Billing, Ledger
from lymi.privacidad import EgressBloqueado
from lymi.providers.base import Completion, Message, Usage


class Espia:
    """Cliente que guarda lo que recibe y devuelve el primer marcador que vio."""

    provider = "espia"
    model = "claude-opus-5"
    tier = "frontier"

    def __init__(self, billing: Billing = Billing.API) -> None:
        self.billing = billing
        self.recibido: list[tuple[str | None, list[Message]]] = []

    def complete(self, messages, *, system=None, max_tokens=4096, cache_system=False) -> Completion:
        self.recibido.append((system, list(messages)))
        texto = messages[-1].content
        marcadores = [p.strip(".,") for p in texto.split() if p.startswith("⟦")]
        respuesta = f"Respondo a {marcadores[0]}." if marcadores else "ok"
        return Completion(
            text=respuesta, usage=Usage(input_tokens=100, output_tokens=20),
            model=self.model, provider=self.provider, billing=self.billing, tier=self.tier, latency_ms=5,
        )


@pytest.fixture
def ledger(tmp_path):
    led = Ledger(tmp_path / "ledger.sqlite3")
    yield led
    led.close()


def _llamada(ledger: Ledger, run_id: str) -> dict:
    return dict(ledger.conn.execute("SELECT * FROM calls WHERE run_id = ?", (run_id,)).fetchone())


class TestRecorder:
    def test_el_remoto_no_ve_el_dato_y_el_usuario_si(self, ledger) -> None:
        espia = Espia()
        with ledger.run("t", "v", Billing.API) as run:
            respuesta = Recorder(run).call(espia, [Message("user", "escribe a ana@empresa.cl hoy")], purpose="p")

        _, mensajes = espia.recibido[0]
        assert "ana@empresa.cl" not in mensajes[0].content
        assert respuesta.text == "Respondo a ana@empresa.cl."

        fila = _llamada(ledger, run.run_id)
        assert fila["redacciones"] == 1
        # El hash registrado es el de lo que salio de verdad: el texto redactado.
        assert fila["payload_sha256"] == sha256(mensajes[0].content.encode()).hexdigest()
        assert ledger.totals(run.run_id)["redacciones"] == 1

    def test_el_local_recibe_el_dato_pero_saneado(self, ledger) -> None:
        espia = Espia(Billing.LOCAL)
        with ledger.run("t", "v", Billing.LOCAL) as run:
            Recorder(run).call(espia, [Message("user", "ana@empresa.cl\u200b\u202e")], purpose="p")
        _, mensajes = espia.recibido[0]
        assert mensajes[0].content == "ana@empresa.cl"
        assert _llamada(ledger, run.run_id)["redacciones"] == 0

    def test_una_clave_privada_no_llega_al_proveedor(self, ledger) -> None:
        espia = Espia()
        clave = "-----BEGIN RSA PRIVATE KEY-----\nMIIE\n-----END RSA PRIVATE KEY-----"
        with pytest.raises(EgressBloqueado), ledger.run("t", "v", Billing.API) as run:
            Recorder(run).call(espia, [Message("user", clave)], purpose="p")
        assert espia.recibido == []
        assert ledger.totals(run.run_id)["n_calls"] == 0

    def test_la_parada_corta_antes_de_llamar(self, ledger, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("LYMI_PARADA", str(tmp_path / "PARAR"))
        detener("prueba")
        espia = Espia()
        with pytest.raises(Detenido), ledger.run("t", "v", Billing.API) as run:
            Recorder(run).call(espia, [Message("user", "hola")], purpose="p")
        assert espia.recibido == []

    def test_el_presupuesto_corta_la_siguiente_llamada(self, ledger) -> None:
        espia = Espia()
        with pytest.raises(PresupuestoAgotado), ledger.run("t", "v", Billing.API) as run:
            rec = Recorder(run, presupuesto=Presupuesto(tokens_remotos=100))
            rec.call(espia, [Message("user", "uno")], purpose="p")
            rec.call(espia, [Message("user", "dos")], purpose="p")
        assert len(espia.recibido) == 1


def _flujo(datos: dict) -> Workflow:
    return Workflow.model_validate(yaml.safe_load(yaml.safe_dump(datos)))


REDACTAR = {
    "name": "respuesta",
    "inputs": {"correo": {"type": "string"}},
    "steps": [{"id": "redactar", "type": "llm", "tier": "remote", "prompt": "Contesta: {{ inputs.correo }}"}],
}


class TestMotor:
    def test_paso_remoto_redacta_y_rehidrata(self, ledger) -> None:
        espia = Espia()
        resultado = correr(
            _flujo(REDACTAR), {"correo": "soy\u200b beto@x.io y mi clave es sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUV"},
            ledger=ledger, remote=espia,
        )
        assert resultado.ok, resultado.detalle
        _, mensajes = espia.recibido[0]
        enviado = mensajes[0].content
        assert "beto@x.io" not in enviado and "sk-ant-api03" not in enviado and "\u200b" not in enviado
        assert resultado.salidas["redactar"] == "Respondo a beto@x.io."
        assert ledger.totals(resultado.run_id)["redacciones"] == 2

    def test_egress_bloqueado_no_se_reintenta(self, ledger) -> None:
        espia = Espia()
        datos = {**REDACTAR, "steps": [{**REDACTAR["steps"][0], "retries": 3}]}
        clave = "-----BEGIN PRIVATE KEY-----\nMIIE\n-----END PRIVATE KEY-----"
        resultado = correr(_flujo(datos), {"correo": clave}, ledger=ledger, remote=espia)
        assert not resultado.ok
        assert resultado.pasos[0].intentos == 1
        assert "no sale de la maquina" in resultado.pasos[0].detalle
        assert espia.recibido == []

    def test_la_parada_detiene_entre_pasos(self, ledger, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("LYMI_PARADA", str(tmp_path / "PARAR"))
        detener()
        flujo = _flujo({"name": "f", "steps": [{"id": "a", "type": "transform", "set": {"x": 1}}]})
        resultado = correr(flujo, {}, ledger=ledger)
        assert not resultado.ok
        assert "detenido" in resultado.pasos[0].detalle

    def test_presupuesto_de_flujo(self, ledger) -> None:
        datos = {
            "name": "dos_llamadas",
            "steps": [
                {"id": "uno", "type": "llm", "tier": "remote", "prompt": "a"},
                {"id": "dos", "type": "llm", "tier": "remote", "prompt": "b"},
            ],
        }
        espia = Espia()
        resultado = correr(_flujo(datos), {}, ledger=ledger, remote=espia, presupuesto=Presupuesto(llamadas=1))
        assert [p.status for p in resultado.pasos] == ["ok", "fallo"]
        assert "1 llamadas" in resultado.pasos[1].detalle
        assert len(espia.recibido) == 1


def test_una_base_vieja_gana_la_columna(tmp_path) -> None:
    import sqlite3

    ruta = tmp_path / "vieja.sqlite3"
    conn = sqlite3.connect(ruta)
    conn.executescript(
        "CREATE TABLE runs (id TEXT PRIMARY KEY, task_id TEXT NOT NULL, variant TEXT NOT NULL,"
        " billing_mode TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT,"
        " status TEXT NOT NULL DEFAULT 'running', score REAL, notes TEXT, git_sha TEXT);"
        "CREATE TABLE calls (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, seq INTEGER NOT NULL,"
        " ts TEXT NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL, billing_mode TEXT NOT NULL,"
        " tier TEXT NOT NULL, purpose TEXT, input_tokens INTEGER NOT NULL DEFAULT 0,"
        " output_tokens INTEGER NOT NULL DEFAULT 0, cache_read_tokens INTEGER NOT NULL DEFAULT 0,"
        " cache_write_tokens INTEGER NOT NULL DEFAULT 0, cost_usd REAL, latency_ms INTEGER,"
        " ok INTEGER NOT NULL DEFAULT 1, error TEXT, egress INTEGER NOT NULL DEFAULT 0,"
        " payload_sha256 TEXT, payload_bytes INTEGER);"
    )
    conn.close()

    ledger = Ledger(ruta)
    try:
        with ledger.run("t", "v", Billing.API) as run:
            Recorder(run).call(Espia(), [Message("user", "ana@x.io")], purpose="p")
        assert ledger.totals(run.run_id)["redacciones"] == 1
    finally:
        ledger.close()
