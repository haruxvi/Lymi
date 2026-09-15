"""El paso `pc` en workflows: aprobacion, registro, diario y proteccion de lo leido."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from lymi.cli import app
from lymi.ejecutor import Perfil
from lymi.flows.engine import correr
from lymi.flows.plan import planificar
from lymi.flows.schema import Workflow
from lymi.ledger import Billing, Ledger
from lymi.providers.base import Completion, Usage


class Remoto:
    provider = "espia"
    model = "claude-opus-5"
    billing = Billing.API
    tier = "frontier"

    def __init__(self) -> None:
        self.recibido: list[str] = []

    def complete(self, messages, *, system=None, max_tokens=4096, cache_system=False) -> Completion:
        self.recibido.append(messages[-1].content)
        return Completion(text="ok", usage=Usage(input_tokens=1, output_tokens=1), model=self.model,
                          provider=self.provider, billing=self.billing, tier=self.tier, latency_ms=1)


ESCRIBIR = {
    "name": "informe",
    "inputs": {"texto": {"type": "string"}},
    "steps": [{"id": "guardar", "type": "pc", "op": "escribir", "ruta": "salidas/informe.md",
               "contenido": "# Informe\n{{ inputs.texto }}"}],
}


@pytest.fixture
def proyecto(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def ledger(proyecto):
    led = Ledger(proyecto / "runs" / "lymi.sqlite3")
    yield led
    led.close()


def _flujo(datos: dict) -> Workflow:
    return Workflow.model_validate(datos)


class TestEsquema:
    def test_campos_por_operacion(self) -> None:
        with pytest.raises(ValueError, match="requiere contenido"):
            _flujo({"name": "x", "steps": [{"id": "a", "type": "pc", "op": "escribir", "ruta": "salidas/a"}]})
        with pytest.raises(ValueError, match="no admite"):
            _flujo({"name": "x", "steps": [{"id": "a", "type": "pc", "op": "leer", "ruta": "a", "contenido": "x"}]})

    def test_un_efecto_no_se_reintenta(self) -> None:
        with pytest.raises(ValueError, match="no se reintenta"):
            _flujo({"name": "x", "steps": [{"id": "a", "type": "pc", "op": "borrar", "ruta": "a", "retries": 2}]})

    def test_sin_secretos_del_entorno(self) -> None:
        with pytest.raises(ValueError, match="VARIABLE"):
            _flujo({"name": "x", "steps": [{"id": "a", "type": "pc", "op": "escribir", "ruta": "salidas/a",
                                            "contenido": "${API_KEY}"}]})

    def test_el_plan_lo_muestra_como_efecto_local(self) -> None:
        (fila,) = planificar(_flujo(ESCRIBIR))
        assert fila.efectos is True
        assert fila.costo == "gratis"
        assert "este PC: escribir" in fila.destino


class TestEjecucion:
    def test_escribir_pide_aprobacion_y_si_se_rechaza_no_toca_nada(self, proyecto, ledger) -> None:
        vistas: list[str] = []

        def rechazar(paso_id: str, vista: str) -> bool:
            vistas.append(vista)
            return False

        resultado = correr(_flujo(ESCRIBIR), {"texto": "hola"}, ledger=ledger, aprobar=rechazar)
        assert resultado.pasos[0].status == "rechazado"
        assert not (proyecto / "salidas" / "informe.md").exists()
        assert "escribir en este PC: salidas/informe.md" in vistas[0]
        assert "# Informe\nhola" in vistas[0]

    def test_aprobado_escribe_registra_y_se_deshace(self, proyecto, ledger, monkeypatch) -> None:
        resultado = correr(_flujo(ESCRIBIR), {"texto": "hola"}, ledger=ledger, aprobar=lambda *_: True)
        assert resultado.ok, resultado.detalle
        archivo = proyecto / "salidas" / "informe.md"
        assert archivo.read_text(encoding="utf-8") == "# Informe\nhola"

        llamada = ledger.conn.execute("SELECT provider, egress, tier FROM calls WHERE run_id = ?",
                                      (resultado.run_id,)).fetchone()
        assert (llamada["provider"], llamada["egress"], llamada["tier"]) == ("pc", 0, "local")

        salida = CliRunner().invoke(app, ["undo", resultado.run_id])
        assert salida.exit_code == 0, salida.output
        assert "quitado" in salida.output
        assert not archivo.exists()

    def test_una_capacidad_denegada_falla_sin_reintentos(self, proyecto, ledger) -> None:
        datos = {"name": "fuera", "steps": [{"id": "a", "type": "pc", "op": "escribir",
                                             "ruta": "../fuera.txt", "contenido": "x"}]}
        resultado = correr(_flujo(datos), {}, ledger=ledger, aprobar=lambda *_: True)
        assert not resultado.ok
        assert resultado.pasos[0].intentos == 1
        assert "fuera de las carpetas escribibles" in resultado.pasos[0].detalle
        assert not (proyecto.parent / "fuera.txt").exists()

    def test_leer_un_env_lo_protege_para_el_resto_de_la_corrida(self, proyecto, ledger) -> None:
        (proyecto / ".env").write_text("STRIPE_SECRET=clave-muy-privada-que-no-debe-salir-nunca-jamas", encoding="utf-8")
        datos = {
            "name": "fuga",
            "steps": [
                {"id": "leer", "type": "pc", "op": "leer", "ruta": ".env"},
                {"id": "enviar", "type": "llm", "tier": "remote", "prompt": "Revisa: {{ steps.leer.output }}"},
            ],
        }
        remoto = Remoto()
        resultado = correr(_flujo(datos), {}, ledger=ledger, remote=remoto, perfil=Perfil.por_defecto(proyecto))
        assert [p.status for p in resultado.pasos] == ["ok", "fallo"]
        assert "archivo nunca sale" in resultado.pasos[1].detalle
        assert remoto.recibido == []

    def test_listar(self, proyecto, ledger) -> None:
        (proyecto / "docs").mkdir()
        (proyecto / "docs" / "a.md").write_text("a", encoding="utf-8")
        datos = {"name": "ver", "steps": [{"id": "ver", "type": "pc", "op": "listar", "ruta": "docs"}]}
        resultado = correr(_flujo(datos), {}, ledger=ledger)
        assert resultado.ok
        assert resultado.salidas["ver"] == [{"nombre": "a.md", "tipo": "archivo", "bytes": 1}]


def test_undo_de_una_corrida_desconocida(proyecto) -> None:
    salida = CliRunner().invoke(app, ["undo", "abc123"])
    assert salida.exit_code == 1


def test_undo_rechaza_ids_con_rutas(proyecto) -> None:
    salida = CliRunner().invoke(app, ["undo", "../../etc"])
    assert salida.exit_code == 1
    assert "invalido" in salida.output


@pytest.mark.parametrize("nombre", [Path("salidas") / "informe.md"])
def test_rutas_relativas_se_resuelven_contra_el_directorio_actual(proyecto, ledger, nombre) -> None:
    resultado = correr(_flujo(ESCRIBIR), {"texto": "x"}, ledger=ledger, aprobar=lambda *_: True)
    assert resultado.ok
    assert (proyecto / nombre).exists()
