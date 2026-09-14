"""CLI de disparadores: schedule y hooks."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from lymi.cli import app
from lymi.triggers.ganchos import SERVICIO

runner = CliRunner()

TRANSFORMA = {
    "name": "leads_entrantes",
    "inputs": {"correo": {"type": "string"}},
    "steps": [{"id": "ficha", "type": "transform", "set": {"correo": "{{ inputs.correo }}"}}],
}
CON_EFECTO = {
    "name": "aviso",
    "inputs": {},
    "integrations": {"api": {"type": "http", "allow_hosts": ["api.ejemplo.com"]}},
    "steps": [{"id": "avisar", "type": "http", "integration": "api", "method": "POST", "url": "https://api.ejemplo.com/x"}],
}


def _yaml(tmp_path: Path, datos: dict) -> Path:
    ruta = tmp_path / f"{datos['name']}.yml"
    ruta.write_text(yaml.safe_dump(datos), encoding="utf-8")
    return ruta


class TestSchedule:
    def test_programar_y_listar(self, tmp_path) -> None:
        flujo = _yaml(tmp_path, TRANSFORMA)
        db = str(tmp_path / "agenda.sqlite3")

        alta = runner.invoke(app, ["schedule", "add", str(flujo), "*/15 * * * *", "-i", "correo=x", "--db", db])
        assert alta.exit_code == 0, alta.output
        assert "programado" in alta.output

        listado = runner.invoke(app, ["schedule", "list", "--db", db])
        assert listado.exit_code == 0, listado.output
        assert flujo.name in listado.output

    def test_avisa_los_efectos_que_se_rechazaran(self, tmp_path) -> None:
        flujo = _yaml(tmp_path, CON_EFECTO)
        resultado = runner.invoke(app, ["schedule", "add", str(flujo), "@daily", "--db", str(tmp_path / "a.sqlite3")])
        assert resultado.exit_code == 0, resultado.output
        assert "se rechazaran" in resultado.output
        assert "avisar" in resultado.output

    def test_error_sin_traza(self, tmp_path) -> None:
        flujo = _yaml(tmp_path, TRANSFORMA)
        resultado = runner.invoke(
            app, ["schedule", "add", str(flujo), "* * *", "-i", "correo=x", "--db", str(tmp_path / "a.sqlite3")]
        )
        assert resultado.exit_code == 1
        assert "5 campos" in resultado.output
        assert "Traceback" not in resultado.output


class TestHooks:
    @pytest.fixture
    def db(self, tmp_path) -> str:
        return str(tmp_path / "ganchos.sqlite3")

    def test_el_secreto_se_muestra_una_sola_vez(self, tmp_path, db, keyring_memoria) -> None:
        flujo = _yaml(tmp_path, TRANSFORMA)

        alta = runner.invoke(app, ["hooks", "add", "leads", str(flujo), "--db", db])
        assert alta.exit_code == 0, alta.output
        secreto = keyring_memoria.datos[(SERVICIO, "leads")]
        assert secreto in alta.output

        listado = runner.invoke(app, ["hooks", "list", "--db", db])
        assert listado.exit_code == 0, listado.output
        assert "leads" in listado.output
        assert secreto not in listado.output

    def test_rotar_muestra_el_nuevo_y_no_el_viejo(self, tmp_path, db, keyring_memoria) -> None:
        flujo = _yaml(tmp_path, TRANSFORMA)
        runner.invoke(app, ["hooks", "add", "leads", str(flujo), "--db", db])
        viejo = keyring_memoria.datos[(SERVICIO, "leads")]

        rotado = runner.invoke(app, ["hooks", "rotate", "leads", "--db", db])

        nuevo = keyring_memoria.datos[(SERVICIO, "leads")]
        assert rotado.exit_code == 0, rotado.output
        assert nuevo in rotado.output
        assert viejo not in rotado.output
