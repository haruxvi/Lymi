"""Aprobaciones ampliadas: reglas, memoria, vencimiento e integracion con el motor."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from lymi.flows.aprobaciones import (
    Decision,
    MemoriaAprobaciones,
    Politica,
    Regla,
    ReglaError,
    Solicitud,
    cargar_politica,
    resolver_aprobacion,
)
from lymi.flows.engine import ejecutar_flujo
from lymi.flows.schema import Workflow
from lymi.ledger import Ledger

AHORA = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)


def _sol(destino: str = "hooks.slack.com", metodo: str | None = "POST", paso: str = "avisar") -> Solicitud:
    return Solicitud(paso, "http", destino, metodo, f"{metodo} https://{destino}/x")


class TestReglas:
    def test_glob_de_destino(self) -> None:
        regla = Regla(Decision.APROBAR, destino="*.slack.com")
        assert regla.aplica(_sol("hooks.slack.com"))
        assert not regla.aplica(_sol("slack.com.evil.net"))

    def test_metodo_y_paso(self) -> None:
        regla = Regla(Decision.RECHAZAR, paso="borrar_*", metodo="delete")
        assert regla.aplica(_sol(metodo="DELETE", paso="borrar_filas"))
        assert not regla.aplica(_sol(metodo="POST", paso="borrar_filas"))

    @pytest.mark.parametrize(
        "kwargs", [{}, {"destino": "*"}, {"paso": "*"}, {"destino": "**", "paso": "*"}]
    )
    def test_aprobar_todo_no_se_puede_guardar(self, kwargs: dict) -> None:
        with pytest.raises(ReglaError, match="--yes"):
            Regla(Decision.APROBAR, **kwargs)

    def test_rechazar_todo_si_se_puede(self) -> None:
        assert Regla(Decision.RECHAZAR, destino="*").aplica(_sol())


class TestPolitica:
    def test_primera_regla_que_coincide_gana(self) -> None:
        politica = Politica([
            Regla(Decision.RECHAZAR, metodo="DELETE"),
            Regla(Decision.APROBAR, destino="hooks.slack.com"),
        ])
        assert politica.evaluar(_sol(metodo="DELETE"))[0] is Decision.RECHAZAR
        assert politica.evaluar(_sol())[0] is Decision.APROBAR

    def test_una_regla_que_rechaza_gana_a_la_memoria(self, tmp_path) -> None:
        memoria = MemoriaAprobaciones(tmp_path / "m.sqlite3")
        memoria.recordar("hooks.slack.com", "POST", Decision.APROBAR, ahora=AHORA)
        politica = Politica([Regla(Decision.RECHAZAR, destino="hooks.slack.com")], memoria)
        assert politica.evaluar(_sol(), AHORA)[0] is Decision.RECHAZAR

    def test_sin_regla_ni_memoria_pregunta(self) -> None:
        assert Politica().evaluar(_sol())[0] is Decision.PREGUNTAR


class TestMemoria:
    def test_recordar_y_consultar(self, tmp_path) -> None:
        memoria = MemoriaAprobaciones(tmp_path / "m.sqlite3")
        memoria.recordar("Hooks.Slack.com", "post", Decision.APROBAR, dias=7, ahora=AHORA)
        assert memoria.consultar("hooks.slack.com", "POST", AHORA) is Decision.APROBAR
        assert memoria.consultar("hooks.slack.com", "GET", AHORA) is None

    def test_vence(self, tmp_path) -> None:
        memoria = MemoriaAprobaciones(tmp_path / "m.sqlite3")
        memoria.recordar("hooks.slack.com", "POST", Decision.APROBAR, dias=1, ahora=AHORA)
        assert memoria.consultar("hooks.slack.com", "POST", AHORA + timedelta(days=2)) is None
        assert memoria.listar() == []

    @pytest.mark.parametrize("destino", ["?", "*"])
    def test_no_recuerda_destinos_desconocidos(self, tmp_path, destino: str) -> None:
        with pytest.raises(ReglaError):
            MemoriaAprobaciones(tmp_path / "m.sqlite3").recordar(destino, None, Decision.APROBAR)

    def test_olvidar(self, tmp_path) -> None:
        memoria = MemoriaAprobaciones(tmp_path / "m.sqlite3")
        memoria.recordar("a.com", "POST", Decision.APROBAR, ahora=AHORA)
        memoria.recordar("a.com", "PUT", Decision.APROBAR, ahora=AHORA)
        assert memoria.olvidar("a.com") == 2

    def test_se_puede_usar_desde_otro_hilo(self, tmp_path) -> None:
        # El aprobador interactivo corre en un hilo aparte.
        memoria = MemoriaAprobaciones(tmp_path / "m.sqlite3")
        asyncio.run(asyncio.to_thread(memoria.recordar, "a.com", "POST", Decision.APROBAR))
        assert memoria.consultar("a.com", "POST") is Decision.APROBAR


class TestCargarPolitica:
    def test_yaml_valido(self, tmp_path) -> None:
        ruta = tmp_path / "p.yml"
        ruta.write_text(
            "reglas:\n  - accion: rechazar\n    metodo: DELETE\n  - accion: aprobar\n    destino: '*.slack.com'\n",
            encoding="utf-8",
        )
        politica = cargar_politica(ruta)
        assert [r.accion for r in politica.reglas] == [Decision.RECHAZAR, Decision.APROBAR]

    @pytest.mark.parametrize("contenido", [
        "reglas:\n  - accion: permitir\n",
        "reglas:\n  - accion: aprobar\n    host: x.com\n",
        "reglas:\n  - accion: aprobar\n",
        "reglas: nada\n",
    ])
    def test_yaml_invalido(self, tmp_path, contenido: str) -> None:
        ruta = tmp_path / "p.yml"
        ruta.write_text(contenido, encoding="utf-8")
        with pytest.raises(ReglaError):
            cargar_politica(ruta)


class TestResolver:
    def test_politica_que_aprueba_no_pregunta(self) -> None:
        def nunca(*_a, **_k):
            raise AssertionError("no deberia preguntar")

        politica = Politica([Regla(Decision.APROBAR, destino="hooks.slack.com")])
        assert asyncio.run(resolver_aprobacion(_sol(), nunca, politica))[0] is True

    def test_aprobador_sincrono(self) -> None:
        assert asyncio.run(resolver_aprobacion(_sol(), lambda _p, _v: True)) == (True, "aprobado por una persona")

    def test_aprobador_asincrono(self) -> None:
        async def aprobar(_p: str, _v: str) -> bool:
            return False

        assert asyncio.run(resolver_aprobacion(_sol(), aprobar)) == (False, "el efecto no fue aprobado")

    def test_el_aprobador_puede_pedir_la_solicitud(self) -> None:
        vistas: list[Solicitud] = []

        def aprobar(_p: str, _v: str, solicitud: Solicitud) -> bool:
            vistas.append(solicitud)
            return True

        asyncio.run(resolver_aprobacion(_sol("api.x.com"), aprobar))
        assert vistas[0].destino == "api.x.com"

    def test_vence_y_cuenta_como_rechazo(self) -> None:
        async def lento(_p: str, _v: str) -> bool:
            await asyncio.sleep(5)
            return True

        aprobado, motivo = asyncio.run(resolver_aprobacion(_sol(), lento, tiempo=0.05))
        assert aprobado is False
        assert "vencio" in motivo


SLACK = {"slack": {"type": "http", "allow_hosts": ["hooks.slack.com"]}}
AVISO = {"id": "avisar", "type": "http", "integration": "slack", "method": "POST",
         "url": "https://hooks.slack.com/services/x", "body": {"t": 1}}


def _flujo() -> Workflow:
    return Workflow.model_validate({"name": "aviso", "integrations": SLACK, "steps": [AVISO]})


def _correr(ledger: Ledger, **opciones):
    enviadas: list[httpx.Request] = []

    async def _ir():
        transporte = httpx.MockTransport(lambda r: enviadas.append(r) or httpx.Response(200, json={}))
        async with httpx.AsyncClient(transport=transporte) as cliente:
            return await ejecutar_flujo(_flujo(), {}, ledger=ledger, http_client=cliente, **opciones)

    return asyncio.run(_ir()), enviadas


class TestMotor:
    @pytest.fixture
    def ledger(self, tmp_path):
        led = Ledger(tmp_path / "l.sqlite3")
        yield led
        led.close()

    def test_regla_que_rechaza_bloquea_aunque_la_persona_apruebe(self, ledger) -> None:
        politica = Politica([Regla(Decision.RECHAZAR, destino="*.slack.com")])
        r, enviadas = _correr(ledger, politica=politica, aprobar=lambda _p, _v: True)
        assert not r.ok
        assert r.pasos[0].status == "rechazado"
        assert "regla" in r.pasos[0].detalle
        assert enviadas == []

    def test_decision_recordada_aprueba_sin_preguntar(self, ledger, tmp_path) -> None:
        memoria = MemoriaAprobaciones(tmp_path / "m.sqlite3")
        memoria.recordar("hooks.slack.com", "POST", Decision.APROBAR)
        r, enviadas = _correr(ledger, politica=Politica(memoria=memoria))
        assert r.ok, r.detalle
        assert len(enviadas) == 1

    def test_vencimiento_en_el_motor(self, ledger) -> None:
        async def lento(_p: str, _v: str) -> bool:
            await asyncio.sleep(5)
            return True

        r, enviadas = _correr(ledger, aprobar=lento, tiempo_aprobacion=0.05)
        assert r.pasos[0].status == "rechazado"
        assert "vencio" in r.pasos[0].detalle
        assert enviadas == []
