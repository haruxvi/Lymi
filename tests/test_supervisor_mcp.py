"""Supervisor de servidores MCP: reinicio tras una caida y degradacion."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from lymi.flows.nodes import McpPool, PasoError
from lymi.flows.schema import McpIntegration

SERVIDOR = Path(__file__).parent / "servidores" / "eco_mcp.py"


def _integ(script: Path) -> McpIntegration:
    return McpIntegration.model_validate({"type": "mcp", "command": sys.executable, "args": [str(script)]})


class TestReinicio:
    def test_reinicia_tras_morir_y_no_repite_la_llamada_en_curso(self) -> None:
        esperas: list[float] = []

        async def dormir(segundos: float) -> None:
            esperas.append(segundos)

        async def _ir():
            pool = McpPool({"eco": _integ(SERVIDOR)}, {}, dormir=dormir)
            try:
                primero = await pool.llamar("eco", "eco", {"texto": "antes"})
                with pytest.raises(PasoError):
                    await pool.llamar("eco", "morir", {})
                despues = await pool.llamar("eco", "eco", {"texto": "despues"})
                return primero, despues, pool.salud()["eco"]
            finally:
                await pool.aclose()

        primero, despues, salud = asyncio.run(_ir())

        assert (primero, despues) == ("antes", "despues")
        assert salud.arranques == 2
        assert len(salud.reinicios) == 1
        assert esperas == [0.5]
        assert salud.degradado is False

    def test_un_error_de_herramienta_no_reinicia(self) -> None:
        async def _ir():
            pool = McpPool({"eco": _integ(SERVIDOR)}, {})
            try:
                with pytest.raises(PasoError):
                    await pool.llamar("eco", "falla", {})
                await pool.llamar("eco", "eco", {"texto": "x"})
                return pool.salud()["eco"]
            finally:
                await pool.aclose()

        salud = asyncio.run(_ir())
        assert salud.arranques == 1
        assert salud.reinicios == []


class TestDegradacion:
    def test_se_degrada_tras_demasiados_reinicios(self, tmp_path) -> None:
        roto = tmp_path / "roto.py"
        roto.write_text("raise SystemExit(3)\n", encoding="utf-8")
        esperas: list[float] = []

        async def dormir(segundos: float) -> None:
            esperas.append(segundos)

        async def _ir():
            pool = McpPool({"roto": _integ(roto)}, {}, reinicios_maximos=2, dormir=dormir)
            errores: list[str] = []
            try:
                for _ in range(5):
                    with pytest.raises(PasoError) as exc:
                        await pool.llamar("roto", "eco", {"texto": "x"})
                    errores.append(str(exc.value))
                return errores, pool.salud()["roto"]
            finally:
                await pool.aclose()

        errores, salud = asyncio.run(_ir())

        assert salud.degradado is True
        assert salud.arranques == 3  # arranque inicial + 2 reinicios; despues ninguno mas
        assert esperas == [0.5, 1.0]  # espera exponencial
        assert "degradad" in errores[-1]
        assert "degradad" in errores[-2]

    def test_la_ventana_olvida_reinicios_viejos(self, tmp_path) -> None:
        roto = tmp_path / "roto.py"
        roto.write_text("raise SystemExit(3)\n", encoding="utf-8")
        reloj = [0.0]

        async def dormir(_segundos: float) -> None:
            reloj[0] += 100  # cada reinicio ocurre fuera de la ventana del anterior

        async def _ir():
            pool = McpPool({"roto": _integ(roto)}, {}, reinicios_maximos=1, ventana=60, dormir=dormir,
                           reloj=lambda: reloj[0])
            try:
                for _ in range(4):
                    with pytest.raises(PasoError):
                        await pool.llamar("roto", "eco", {"texto": "x"})
                return pool.salud()["roto"]
            finally:
                await pool.aclose()

        salud = asyncio.run(_ir())
        assert salud.degradado is False
        assert salud.arranques == 4
