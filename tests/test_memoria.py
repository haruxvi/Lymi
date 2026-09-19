"""Memoria: promocion, busqueda con procedencia, secretos fuera y uso desde agentes y workflows."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from lymi.agencia import correr_agencia
from lymi.agencia.citas import respaldada, vistas
from lymi.agencia.definicion import Agencia
from lymi.cli import app
from lymi.flows.engine import ejecutar_flujo
from lymi.flows.schema import Workflow
from lymi.ledger import Ledger
from lymi.memoria import Memoria, MemoriaError, formato
from tests.test_agencia import Guion


@pytest.fixture
def memoria() -> Memoria:
    return Memoria()


@pytest.fixture
def ledger(tmp_path):
    led = Ledger(tmp_path / "l.sqlite3")
    yield led
    led.close()


class TestPromocion:
    def test_un_agente_anota_una_afirmacion(self, memoria) -> None:
        nota = memoria.anotar("El cliente Acme paga a 60 dias.", fuente="correo del 3/9", agente="ventas.a")
        assert nota.estado == "afirmacion" and nota.ruta.parent.name == "afirmaciones"
        (r,) = memoria.buscar("cuando paga Acme")
        texto = formato([r], memoria.raiz)
        assert texto.startswith("[SIN REVISAR]") and "no lo presentes como hecho" in texto
        assert memoria.buscar("Acme", solo_hechos=True) == []

    def test_promover_y_descartar(self, memoria) -> None:
        a = memoria.anotar("Acme paga a 60 dias.", fuente="correo")
        b = memoria.anotar("Acme odia el azul.", fuente="rumor")
        assert memoria.promover(a.id).estado == "hecho"
        assert memoria.descartar(b.id).ruta.parent.name == "descartadas"
        (r,) = memoria.buscar("Acme paga", solo_hechos=True)
        assert r.nota.id == a.id and formato([r], memoria.raiz).startswith("[hecho]")
        assert memoria.listar("afirmaciones") == []
        assert (memoria.raiz / "descartadas" / f"{b.id}.md").exists()  # nada se borra

    @pytest.mark.parametrize("nota_id", ["../../etc/passwd", "20260919-000000-zzzzzz", "x"])
    def test_ids_invalidos(self, memoria, nota_id) -> None:
        with pytest.raises(MemoriaError):
            memoria.promover(nota_id)

    def test_la_linea_citada_es_la_del_texto(self, memoria) -> None:
        nota = memoria.anotar("primera linea\n\nLa clave del exito es medir.", fuente="yo", hecho=True)
        (r,) = memoria.buscar("clave del exito")
        lineas = nota.ruta.read_text(encoding="utf-8").splitlines()
        assert r.fragmento.splitlines()[0] in lineas[r.linea - 1] or lineas[r.linea - 1] in r.fragmento


class TestSecretos:
    @pytest.mark.parametrize("texto", [
        "la clave es sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "password: hunter2hunter2",
        "-----BEGIN RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY-----",
    ])
    def test_no_entran(self, memoria, texto) -> None:
        with pytest.raises(MemoriaError, match="no se guarda"):
            memoria.anotar(texto, fuente="x")
        assert memoria.listar("afirmaciones") == []

    def test_un_contacto_si(self, memoria) -> None:
        memoria.anotar("Contacto de Acme: ana@acme.cl", fuente="tarjeta")


def test_las_notas_propias_cuentan_como_del_usuario(memoria) -> None:
    (memoria.raiz / "proyectos").mkdir(parents=True)
    (memoria.raiz / "proyectos" / "lymi.md").write_text("# lymi\n\nEl objetivo es ahorro falsable.\n", encoding="utf-8")
    (memoria.raiz / ".obsidian").mkdir()
    (memoria.raiz / ".obsidian" / "config.md").write_text("ahorro falsable secreto de config", encoding="utf-8")
    resultados = memoria.buscar("ahorro falsable")
    assert [r.nota.estado for r in resultados] == ["propia"]
    assert formato(resultados, memoria.raiz).startswith("[nota del usuario]")


class TestDesdeAgentes:
    def _agencia(self) -> Agencia:
        return Agencia.model_validate({"name": "m", "departamentos": {"d": {"agentes": {"a": {
            "descripcion": "x", "rol": "r", "herramientas": ["memoria.buscar", "memoria.anotar"]}}}}})

    def test_anota_con_autor_fijado_por_el_motor_y_cita_lo_que_vio(self, ledger, memoria) -> None:
        guion = Guion({"d.a": [
            {"accion": "usar", "herramienta": "memoria.anotar",
             "args": {"texto": "Acme paga a 60 dias", "fuente": "correo", "autor": "usuario"}},
            {"accion": "usar", "herramienta": "memoria.buscar", "args": {"consulta": "Acme paga"}},
            {"accion": "terminar", "resultado": "listo"},
        ]})
        r = asyncio.run(correr_agencia(self._agencia(), "recuerda", ledger=ledger, local=guion, agente="d"))
        assert r.ok
        (nota,) = memoria.listar("afirmaciones")
        assert nota.agente == "d.a (t1)" and nota.corrida == r.run_id
        assert guion.vio("d.a", "queda SIN REVISAR") and guion.vio("d.a", "[SIN REVISAR]")
        # Lo devuelto por la memoria trae ruta:linea que el agente puede citar.
        (recuerdo,) = memoria.buscar("Acme paga")
        visto = vistas(formato([recuerdo], memoria.raiz))
        cita = f"{recuerdo.nota.ruta.relative_to(memoria.raiz.parent).as_posix()}:{recuerdo.linea}"
        assert respaldada(cita, visto)


def test_paso_de_workflow(ledger, memoria) -> None:
    flujo = Workflow.model_validate({"name": "m", "steps": [
        {"id": "anotar", "type": "memoria", "op": "anotar", "texto": "Beta sale el lunes", "fuente": "reunion"},
        {"id": "buscar", "type": "memoria", "op": "buscar", "consulta": "cuando sale Beta"},
    ]})
    r = asyncio.run(ejecutar_flujo(flujo, {}, ledger=ledger))
    assert r.ok, r.detalle
    assert r.salidas["buscar"]["datos"][0]["estado"] == "afirmacion"
    with pytest.raises(ValueError, match="anotar requiere texto y fuente"):
        Workflow.model_validate({"name": "m", "steps": [{"id": "a", "type": "memoria", "op": "anotar", "texto": "x"}]})


def test_cli(memoria) -> None:
    runner = CliRunner()
    r = runner.invoke(app, ["memoria", "anotar", "Gamma usa Postgres", "--fuente", "arquitectura"])
    assert r.exit_code == 0 and "afirmacion" in r.output
    nota_id = r.output.split()[1]
    assert nota_id in runner.invoke(app, ["memoria", "pendientes"]).output
    assert runner.invoke(app, ["memoria", "promover", nota_id]).exit_code == 0
    assert "[hecho]" in runner.invoke(app, ["memoria", "buscar", "Gamma Postgres"]).output
    assert Path(os.environ["LYMI_MEMORIA"]).exists()
