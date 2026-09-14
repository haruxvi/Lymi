"""Registro de webhooks: el secreto nunca toca la base de datos."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from lymi.triggers.ganchos import SERVICIO, GanchoError, Ganchos

FLUJO = {
    "name": "aviso",
    "inputs": {},
    "integrations": {"api": {"type": "http", "allow_hosts": ["api.ejemplo.com"]}},
    "steps": [
        {"id": "preparar", "type": "transform", "set": {"x": 1}},
        {"id": "avisar", "type": "http", "integration": "api", "method": "POST", "url": "https://api.ejemplo.com/x"},
    ],
}


@pytest.fixture
def workflow(tmp_path) -> Path:
    ruta = tmp_path / "aviso.yml"
    ruta.write_text(yaml.safe_dump(FLUJO), encoding="utf-8")
    return ruta


@pytest.fixture
def ganchos(tmp_path, keyring_memoria):
    g = Ganchos(tmp_path / "ganchos.sqlite3")
    yield g
    g.close()


class TestSecretos:
    def test_el_secreto_va_al_almacen_y_no_a_sqlite(self, ganchos: Ganchos, workflow: Path, keyring_memoria) -> None:
        _, secreto = ganchos.crear("leads", workflow)

        assert len(secreto) >= 32
        assert keyring_memoria.datos[(SERVICIO, "leads")] == secreto
        volcado = "\n".join(ganchos._conn.iterdump())
        assert secreto not in volcado

    def test_secreto_de_un_webhook(self, ganchos: Ganchos, workflow: Path) -> None:
        _, secreto = ganchos.crear("leads", workflow)
        assert ganchos.secreto("leads") == secreto.encode()
        assert ganchos.secreto("fantasma") is None

    def test_rotar_reemplaza_el_secreto(self, ganchos: Ganchos, workflow: Path) -> None:
        _, viejo = ganchos.crear("leads", workflow)
        nuevo = ganchos.rotar("leads")
        assert nuevo != viejo
        assert ganchos.secreto("leads") == nuevo.encode()

    def test_quitar_borra_fila_y_secreto(self, ganchos: Ganchos, workflow: Path, keyring_memoria) -> None:
        ganchos.crear("leads", workflow)
        ganchos.quitar("leads")
        assert ganchos.obtener("leads") is None
        assert (SERVICIO, "leads") not in keyring_memoria.datos


class TestValidacion:
    @pytest.mark.parametrize("nombre", ["Leads", "1leads", "leads!", "", "x" * 41])
    def test_nombre_invalido(self, ganchos: Ganchos, workflow: Path, nombre: str) -> None:
        with pytest.raises(GanchoError, match="nombre invalido"):
            ganchos.crear(nombre, workflow)

    def test_nombre_duplicado(self, ganchos: Ganchos, workflow: Path) -> None:
        ganchos.crear("leads", workflow)
        with pytest.raises(GanchoError, match="ya existe"):
            ganchos.crear("leads", workflow)

    def test_esquema_desconocido(self, ganchos: Ganchos, workflow: Path) -> None:
        with pytest.raises(GanchoError, match="no soportado"):
            ganchos.crear("leads", workflow, esquema="stripe")

    def test_workflow_invalido(self, ganchos: Ganchos, tmp_path) -> None:
        roto = tmp_path / "roto.yml"
        roto.write_text("name: roto\nsteps: []\n", encoding="utf-8")
        with pytest.raises(GanchoError):
            ganchos.crear("leads", roto)

    def test_preaprobar_paso_sin_efectos(self, ganchos: Ganchos, workflow: Path) -> None:
        with pytest.raises(GanchoError, match="no tiene efectos"):
            ganchos.crear("leads", workflow, aprobados=["preparar"])

    def test_preaprobar_efecto(self, ganchos: Ganchos, workflow: Path) -> None:
        gancho, _ = ganchos.crear("leads", workflow, aprobados=["avisar"])
        assert gancho.aprobados == frozenset({"avisar"})

    def test_operar_sobre_inexistente(self, ganchos: Ganchos) -> None:
        for operacion in (lambda: ganchos.rotar("x"), lambda: ganchos.quitar("x"), lambda: ganchos.activar("x", False)):
            with pytest.raises(GanchoError, match="no existe"):
                operacion()


class TestRegistro:
    def test_desactivar(self, ganchos: Ganchos, workflow: Path) -> None:
        ganchos.crear("leads", workflow)
        assert ganchos.activar("leads", False).activo is False

    def test_persiste_entre_aperturas(self, tmp_path, workflow: Path, keyring_memoria) -> None:
        ruta = tmp_path / "persistente.sqlite3"
        primero = Ganchos(ruta)
        primero.crear("leads", workflow)
        primero.close()

        segundo = Ganchos(ruta)
        try:
            assert [g.nombre for g in segundo.listar()] == ["leads"]
        finally:
            segundo.close()
