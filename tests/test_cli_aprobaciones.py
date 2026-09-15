"""Pruebas de `lymi flow approvals list|forget`."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from typer.testing import CliRunner

from lymi.cli import app
from lymi.flows.aprobaciones import Decision, MemoriaAprobaciones

runner = CliRunner()


def test_lista_vacia(tmp_path) -> None:
    resultado = runner.invoke(app, ["flow", "approvals", "list", "--memoria-aprobaciones", str(tmp_path / "m.sqlite3")])
    assert resultado.exit_code == 0
    assert "No hay decisiones" in resultado.output


def test_lista_solo_las_vigentes(tmp_path) -> None:
    ruta = tmp_path / "m.sqlite3"
    memoria = MemoriaAprobaciones(ruta)
    memoria.recordar("hooks.slack.com", "POST", Decision.APROBAR)
    memoria.recordar("api.vieja.com", None, Decision.APROBAR, ahora=datetime.now(UTC) - timedelta(days=40))

    resultado = runner.invoke(app, ["flow", "approvals", "list", "--memoria-aprobaciones", str(ruta)])
    assert resultado.exit_code == 0
    assert "hooks.slack.com" in resultado.output
    assert "api.vieja.com" not in resultado.output


def test_olvidar(tmp_path) -> None:
    ruta = tmp_path / "m.sqlite3"
    MemoriaAprobaciones(ruta).recordar("hooks.slack.com", "POST", Decision.APROBAR)

    resultado = runner.invoke(app, ["flow", "approvals", "forget", "hooks.slack.com", "--memoria-aprobaciones", str(ruta)])
    assert resultado.exit_code == 0
    assert "olvidadas 1" in resultado.output
    assert MemoriaAprobaciones(ruta).consultar("hooks.slack.com", "POST") is None


def test_olvidar_lo_que_no_existe(tmp_path) -> None:
    resultado = runner.invoke(
        app, ["flow", "approvals", "forget", "nadie.com", "--memoria-aprobaciones", str(tmp_path / "m.sqlite3")]
    )
    assert resultado.exit_code == 1
