"""Evaluacion de modelos como agentes: preguntas, correccion sin juez y recorrido completo."""

from __future__ import annotations

import asyncio

import pytest

from lymi.bench.agentes import Pregunta, calificar, evaluar, preguntas
from lymi.ledger import Ledger
from tests.test_agencia import Guion

REPO = {
    "src/app/nucleo.py": "def validar(x):\n    return bool(x)\n\n\ndef _privada():\n    pass\n",
    "src/app/uso.py": "from app.nucleo import validar\n\n\ndef procesar(x):\n    return validar(x)\n",
    "src/app/solo.py": "def sin_llamadores():\n    pass\n",
}


@pytest.fixture
def repo(tmp_path, monkeypatch):
    for ruta, contenido in REPO.items():
        archivo = tmp_path / ruta
        archivo.parent.mkdir(parents=True, exist_ok=True)
        archivo.write_text(contenido, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LYMI_CODIGO", str(tmp_path / "indices"))
    return tmp_path


def test_preguntas_solo_con_llamadores_reales(repo) -> None:
    (p,) = preguntas(repo, 10)
    assert (p.simbolo, p.ruta, p.linea, p.llamadores) == ("validar", "src/app/nucleo.py", 1, frozenset({"procesar"}))


@pytest.mark.parametrize("texto,aprobada,motivo", [
    ("Se define en src/app/nucleo.py:1 y la llama procesar.", True, "ok"),
    ("Esta en nucleo.py:1, la usa procesar.", True, "ok"),
    ("Esta en src/app/nucleo.py:2, la usa procesar.", False, "no cita src/app/nucleo.py:1"),
    ("Esta en src/app/nucleo.py:1.", False, "no nombra ningun llamador real"),
])
def test_calificar(texto, aprobada, motivo) -> None:
    p = Pregunta("validar", "src/app/nucleo.py", 1, frozenset({"procesar"}))
    assert calificar(texto, p, []) == (aprobada, motivo)


def test_una_cita_sin_respaldo_reprueba_aunque_acierte() -> None:
    p = Pregunta("validar", "src/app/nucleo.py", 1, frozenset({"procesar"}))
    ok, motivo = calificar("src/app/nucleo.py:1, procesar, y otro.py:9", p, ["otro.py:9"])
    assert not ok and "cita sin respaldo: otro.py:9" in motivo


def test_recorrido_con_un_modelo_que_busca_y_uno_que_inventa(repo, tmp_path) -> None:
    lista = preguntas(repo, 1)
    buscar = {"accion": "usar", "herramienta": "codigo.buscar", "args": {"consulta": "validar"}}
    llamadores = {"accion": "usar", "herramienta": "codigo.llamadores", "args": {"nombre": "validar"}}
    bueno = Guion({"producto.ingeniero": [buscar, llamadores,
                                          {"accion": "terminar", "resultado": "src/app/nucleo.py:1; la llama procesar"}]})
    inventa = {"accion": "terminar", "resultado": "src/app/otro.py:7; la llama procesar"}
    malo = Guion({"producto.ingeniero": [inventa, inventa]})
    ledger = Ledger(tmp_path / "l.sqlite3")
    try:
        (r_bueno,) = asyncio.run(evaluar(bueno, "local", lista, ledger=ledger))
        (r_malo,) = asyncio.run(evaluar(malo, "local", lista, ledger=ledger))
    finally:
        ledger.close()
    assert r_bueno.aprobada, r_bueno.motivo
    assert r_bueno.turnos == 3
    assert not r_malo.aprobada and r_malo.sin_respaldo == ["src/app/otro.py:7"]
