"""Servidor de disparadores: webhooks y agenda contra la aplicacion real."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from starlette.testclient import TestClient

from lymi.ledger import Ledger
from lymi.triggers import webhook
from lymi.triggers.ganchos import Ganchos
from lymi.triggers.servidor import (
    ConfigServidor,
    abrir_estado,
    cerrar_estado,
    crear_app,
    revisar_agenda,
)

TRANSFORMA = {
    "name": "leads_entrantes",
    "inputs": {"correo": {"type": "string"}},
    "steps": [{"id": "ficha", "type": "transform", "set": {"correo": "{{ inputs.correo }}"}}],
}

CON_EFECTO = {
    "name": "aviso",
    "inputs": {},
    "integrations": {"api": {"type": "http", "allow_hosts": ["api.ejemplo.com"]}},
    "steps": [{"id": "avisar", "type": "http", "integration": "api", "method": "POST",
               "url": "https://api.ejemplo.com/x", "body": {"a": 1}}],
}


def _yaml(tmp_path: Path, datos: dict) -> Path:
    ruta = tmp_path / f"{datos['name']}.yml"
    ruta.write_text(yaml.safe_dump(datos), encoding="utf-8")
    return ruta


@pytest.fixture
def config(tmp_path) -> ConfigServidor:
    return ConfigServidor(
        ledger=tmp_path / "ledger.sqlite3",
        agenda=tmp_path / "agenda.sqlite3",
        ganchos=tmp_path / "ganchos.sqlite3",
        intervalo_agenda=None,
    )


def _crear_gancho(config: ConfigServidor, tmp_path: Path, datos: dict = TRANSFORMA, **opciones) -> bytes:
    ganchos = Ganchos(config.ganchos)
    try:
        _, secreto = ganchos.crear("leads", _yaml(tmp_path, datos), **opciones)
    finally:
        ganchos.close()
    return secreto.encode()


def _corridas(config: ConfigServidor, variante: str) -> list[dict]:
    ledger = Ledger(config.ledger)
    try:
        filas = ledger.conn.execute("SELECT * FROM runs WHERE variant = ?", (variante,)).fetchall()
        return [dict(f) for f in filas]
    finally:
        ledger.close()


def _esperar_corrida(config: ConfigServidor, variante: str, timeout: float = 10.0) -> list[dict]:
    limite = time.monotonic() + timeout
    while time.monotonic() < limite:
        terminadas = [f for f in _corridas(config, variante) if f["status"] != "running"]
        if terminadas:
            return terminadas
        time.sleep(0.05)
    pytest.fail(f"no termino ninguna corrida {variante!r}")


def _firmado(secreto: bytes, cuerpo: bytes) -> dict[str, str]:
    return {webhook.CABECERA_FIRMA: webhook.firmar(secreto, cuerpo)}


class TestWebhook:
    def test_disparo_firmado_corre_el_workflow(self, config, tmp_path, keyring_memoria) -> None:
        secreto = _crear_gancho(config, tmp_path)
        cuerpo = json.dumps({"correo": "hola@acme.com"}).encode()

        with TestClient(crear_app(config)) as cliente:
            respuesta = cliente.post("/hooks/leads", content=cuerpo, headers=_firmado(secreto, cuerpo))
            assert respuesta.status_code == 202
            corridas = _esperar_corrida(config, "webhook:leads")

        assert corridas[0]["status"] == "passed"
        assert corridas[0]["task_id"] == "leads_entrantes"

    def test_inexistente_y_firma_mala_son_indistinguibles(self, config, tmp_path, keyring_memoria) -> None:
        _crear_gancho(config, tmp_path)
        cabecera = {webhook.CABECERA_FIRMA: "t=1,v1=00"}

        with TestClient(crear_app(config)) as cliente:
            mala = cliente.post("/hooks/leads", content=b"{}", headers=cabecera)
            inexistente = cliente.post("/hooks/fantasma", content=b"{}", headers=cabecera)

        assert (mala.status_code, mala.json()) == (401, {"error": "firma invalida"})
        assert (inexistente.status_code, inexistente.json()) == (401, {"error": "firma invalida"})

    def test_repeticion_rechazada(self, config, tmp_path, keyring_memoria) -> None:
        secreto = _crear_gancho(config, tmp_path)
        cuerpo = json.dumps({"correo": "x"}).encode()
        cabeceras = _firmado(secreto, cuerpo)

        with TestClient(crear_app(config)) as cliente:
            primera = cliente.post("/hooks/leads", content=cuerpo, headers=cabeceras)
            segunda = cliente.post("/hooks/leads", content=cuerpo, headers=cabeceras)

        assert primera.status_code == 202
        assert segunda.status_code == 409

    def test_entradas_desconocidas(self, config, tmp_path, keyring_memoria) -> None:
        secreto = _crear_gancho(config, tmp_path)
        cuerpo = json.dumps({"intruso": 1}).encode()
        with TestClient(crear_app(config)) as cliente:
            respuesta = cliente.post("/hooks/leads", content=cuerpo, headers=_firmado(secreto, cuerpo))
        assert respuesta.status_code == 400

    def test_cuerpo_gigante_se_corta(self, config, tmp_path, keyring_memoria) -> None:
        _crear_gancho(config, tmp_path)
        cuerpo = b" " * (webhook.LIMITE_CUERPO + 1)
        with TestClient(crear_app(config)) as cliente:
            respuesta = cliente.post("/hooks/leads", content=cuerpo, headers={webhook.CABECERA_FIRMA: "t=1,v1=00"})
        assert respuesta.status_code == 413

    def test_sin_cupo_responde_429(self, tmp_path, keyring_memoria) -> None:
        config = ConfigServidor(
            ledger=tmp_path / "l.sqlite3", agenda=tmp_path / "a.sqlite3", ganchos=tmp_path / "g.sqlite3",
            intervalo_agenda=None, max_corridas=0,
        )
        secreto = _crear_gancho(config, tmp_path)
        cuerpo = json.dumps({"correo": "x"}).encode()
        with TestClient(crear_app(config)) as cliente:
            respuesta = cliente.post("/hooks/leads", content=cuerpo, headers=_firmado(secreto, cuerpo))
        assert respuesta.status_code == 429
        assert respuesta.headers["retry-after"] == "30"

    def test_efecto_no_preaprobado_se_rechaza_sin_salir(self, config, tmp_path, keyring_memoria) -> None:
        secreto = _crear_gancho(config, tmp_path, datos=CON_EFECTO)
        with TestClient(crear_app(config)) as cliente:
            respuesta = cliente.post("/hooks/leads", content=b"{}", headers=_firmado(secreto, b"{}"))
            assert respuesta.status_code == 202
            corridas = _esperar_corrida(config, "webhook:leads")

        assert corridas[0]["status"] == "failed"
        assert "no fue aprobado" in corridas[0]["notes"]

    def test_salud(self, config, keyring_memoria) -> None:
        with TestClient(crear_app(config)) as cliente:
            assert cliente.get("/salud").json() == {"ok": True}


class TestAgenda:
    AHORA = datetime(2026, 9, 12, 10, 7, tzinfo=UTC)

    def test_lanza_las_vencidas_y_las_marca_antes(self, config, tmp_path, keyring_memoria) -> None:
        ruta = _yaml(tmp_path, TRANSFORMA)

        async def _ir():
            estado = abrir_estado(config)
            try:
                prog = estado.agenda.agregar(ruta, "*/15 * * * *", entradas={"correo": "x"}, ahora=self.AHORA)
                antes = await revisar_agenda(estado, self.AHORA)
                lanzadas = await revisar_agenda(estado, self.AHORA + timedelta(minutes=10))
                if estado.tareas:
                    await asyncio.wait(set(estado.tareas))
                return prog, antes, lanzadas, estado.agenda.obtener(prog.id)
            finally:
                await cerrar_estado(estado)

        prog, antes, lanzadas, despues = asyncio.run(_ir())

        assert antes == []
        assert lanzadas == [prog.id]
        assert despues.proxima == datetime(2026, 9, 12, 10, 30, tzinfo=UTC)
        assert _corridas(config, f"agenda:{prog.id}")[0]["status"] == "passed"

    def test_sin_cupo_no_marca_ni_lanza(self, tmp_path, keyring_memoria) -> None:
        config = ConfigServidor(
            ledger=tmp_path / "l.sqlite3", agenda=tmp_path / "a.sqlite3", ganchos=tmp_path / "g.sqlite3",
            intervalo_agenda=None, max_corridas=0,
        )
        ruta = _yaml(tmp_path, TRANSFORMA)

        async def _ir():
            estado = abrir_estado(config)
            try:
                prog = estado.agenda.agregar(ruta, "*/15 * * * *", entradas={"correo": "x"}, ahora=self.AHORA)
                lanzadas = await revisar_agenda(estado, self.AHORA + timedelta(minutes=10))
                return prog, lanzadas, estado.agenda.obtener(prog.id)
            finally:
                await cerrar_estado(estado)

        prog, lanzadas, despues = asyncio.run(_ir())
        assert lanzadas == []
        assert despues.proxima == prog.proxima  # sigue vencida; se reintenta en la proxima revision
