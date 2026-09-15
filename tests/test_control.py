"""Pruebas del interruptor de parada y los presupuestos."""

from __future__ import annotations

import pytest

from lymi.control import (
    Detenido,
    Presupuesto,
    PresupuestoAgotado,
    detener,
    detenido,
    reanudar,
    verificar_parada,
)


@pytest.fixture(autouse=True)
def parada_aislada(tmp_path, monkeypatch):
    monkeypatch.setenv("LYMI_PARADA", str(tmp_path / "PARAR"))


class TestParada:
    def test_por_defecto_no_esta_detenido(self) -> None:
        assert detenido() is False
        verificar_parada()

    def test_detener_y_reanudar(self) -> None:
        detener("pruebas")
        assert detenido() is True
        with pytest.raises(Detenido, match="lymi resume"):
            verificar_parada()
        assert reanudar() is True
        assert detenido() is False

    def test_reanudar_sin_parada(self) -> None:
        assert reanudar() is False


class TestPresupuesto:
    def test_sin_topes_nunca_se_agota(self) -> None:
        p = Presupuesto()
        p.sumar(10_000_000)
        p.verificar()

    def test_tope_de_tokens(self) -> None:
        p = Presupuesto(tokens_remotos=1000)
        p.verificar()
        p.sumar(1200)  # una llamada puede pasarse: no se sabe antes cuanto costara
        with pytest.raises(PresupuestoAgotado, match="1,000 tokens"):
            p.verificar()

    def test_tope_de_llamadas(self) -> None:
        p = Presupuesto(llamadas=2)
        p.sumar(1)
        p.verificar()
        p.sumar(1)
        with pytest.raises(PresupuestoAgotado, match="2 llamadas"):
            p.verificar()

    @pytest.mark.parametrize("tope", [0, -5])
    def test_topes_invalidos(self, tope) -> None:
        with pytest.raises(ValueError):
            Presupuesto(tokens_remotos=tope)
