"""Agenda de workflows programados."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from lymi.triggers.agenda import Agenda, AgendaError, aprobador_desatendido

AHORA = datetime(2026, 9, 12, 10, 7, tzinfo=UTC)

AVISO = {
    "name": "aviso_diario",
    "inputs": {"msg": {"type": "string"}},
    "integrations": {"slack": {"type": "http", "allow_hosts": ["hooks.slack.com"]}},
    "steps": [
        {"id": "preparar", "type": "transform", "set": {"texto": "{{ inputs.msg }}"}},
        {
            "id": "avisar", "type": "http", "integration": "slack", "method": "POST",
            "url": "https://hooks.slack.com/services/${SLACK_PATH}",
            "body": {"text": "{{ steps.preparar.output.texto }}"},
        },
    ],
}


@pytest.fixture
def workflow(tmp_path) -> Path:
    ruta = tmp_path / "aviso.yml"
    ruta.write_text(yaml.safe_dump(AVISO, allow_unicode=True), encoding="utf-8")
    return ruta


@pytest.fixture
def agenda(tmp_path):
    a = Agenda(tmp_path / "agenda.sqlite3")
    yield a
    a.close()


def _agregar(agenda: Agenda, workflow: Path, expresion: str = "*/15 * * * *", **opciones):
    opciones.setdefault("entradas", {"msg": "hola"})
    opciones.setdefault("ahora", AHORA)
    return agenda.agregar(workflow, expresion, **opciones)


class TestAgregar:
    def test_calcula_la_proxima(self, agenda: Agenda, workflow: Path) -> None:
        prog = _agregar(agenda, workflow)
        assert prog.proxima == datetime(2026, 9, 12, 10, 15, tzinfo=UTC)
        assert prog.activo
        assert prog.workflow.is_absolute()

    def test_respeta_la_zona_horaria(self, agenda: Agenda, workflow: Path) -> None:
        prog = _agregar(agenda, workflow, "0 9 * * *", zona="Asia/Tokyo", ahora=datetime(2026, 9, 12, tzinfo=UTC))
        assert prog.proxima == datetime(2026, 9, 13, 0, 0, tzinfo=UTC)

    def test_cron_invalido(self, agenda: Agenda, workflow: Path) -> None:
        with pytest.raises(AgendaError, match="5 campos"):
            _agregar(agenda, workflow, "* * *")

    def test_zona_desconocida(self, agenda: Agenda, workflow: Path) -> None:
        with pytest.raises(AgendaError, match="desconocida"):
            _agregar(agenda, workflow, zona="Nada/Ninguna")

    def test_workflow_invalido(self, agenda: Agenda, tmp_path) -> None:
        roto = tmp_path / "roto.yml"
        roto.write_text("name: roto\nsteps: []\n", encoding="utf-8")
        with pytest.raises(AgendaError):
            _agregar(agenda, roto)

    def test_entradas_se_validan_al_programar(self, agenda: Agenda, workflow: Path) -> None:
        with pytest.raises(AgendaError, match="requerida"):
            _agregar(agenda, workflow, entradas={})

    def test_no_se_guarda_nada_si_algo_falla(self, agenda: Agenda, workflow: Path) -> None:
        with pytest.raises(AgendaError):
            _agregar(agenda, workflow, entradas={})
        assert agenda.listar() == []


class TestPreaprobacion:
    def test_preaprobar_un_efecto(self, agenda: Agenda, workflow: Path) -> None:
        prog = _agregar(agenda, workflow, aprobados=["avisar"])
        assert prog.aprobados == frozenset({"avisar"})
        assert agenda.efectos_sin_autorizar(prog) == []

    def test_paso_inexistente(self, agenda: Agenda, workflow: Path) -> None:
        with pytest.raises(AgendaError, match="no es un paso"):
            _agregar(agenda, workflow, aprobados=["fantasma"])

    def test_paso_sin_efectos_no_se_preaprueba(self, agenda: Agenda, workflow: Path) -> None:
        with pytest.raises(AgendaError, match="no tiene efectos"):
            _agregar(agenda, workflow, aprobados=["preparar"])

    def test_informa_los_efectos_que_se_rechazaran(self, agenda: Agenda, workflow: Path) -> None:
        prog = _agregar(agenda, workflow)
        assert agenda.efectos_sin_autorizar(prog) == ["avisar"]

    def test_aprobador_desatendido(self) -> None:
        aprobar = aprobador_desatendido(frozenset({"avisar"}))
        assert aprobar("avisar", "POST hooks.slack.com") is True
        assert aprobar("borrar_todo", "DELETE ...") is False


class TestEjecucion:
    def test_vencidas_solo_las_que_tocan_y_en_orden(self, agenda: Agenda, workflow: Path) -> None:
        cada_hora = _agregar(agenda, workflow, "0 * * * *")
        cada_cuarto = _agregar(agenda, workflow, "*/15 * * * *")

        assert agenda.vencidas(AHORA) == []
        assert [p.id for p in agenda.vencidas(AHORA + timedelta(hours=2))] == [cada_cuarto.id, cada_hora.id]

    def test_sin_recuperacion_de_ejecuciones_perdidas(self, agenda: Agenda, workflow: Path) -> None:
        prog = _agregar(agenda, workflow)
        tres_dias_despues = AHORA + timedelta(days=3)

        actualizada = agenda.marcar_ejecutada(prog.id, tres_dias_despues)

        assert actualizada.ultima == tres_dias_despues.replace(microsecond=0)
        assert actualizada.proxima == datetime(2026, 9, 15, 10, 15, tzinfo=UTC)
        assert agenda.vencidas(tres_dias_despues) == []

    def test_pausar_y_reanudar(self, agenda: Agenda, workflow: Path) -> None:
        prog = _agregar(agenda, workflow)
        agenda.pausar(prog.id)
        assert agenda.vencidas(AHORA + timedelta(days=1)) == []

        mas_tarde = AHORA + timedelta(days=1)
        reanudada = agenda.reanudar(prog.id, ahora=mas_tarde)
        assert reanudada.activo
        assert reanudada.proxima > mas_tarde  # no dispara al instante una hora vieja

    def test_quitar(self, agenda: Agenda, workflow: Path) -> None:
        prog = _agregar(agenda, workflow)
        agenda.quitar(prog.id)
        with pytest.raises(AgendaError):
            agenda.obtener(prog.id)
        with pytest.raises(AgendaError):
            agenda.quitar(prog.id)

    def test_persiste_entre_aperturas(self, tmp_path, workflow: Path) -> None:
        ruta = tmp_path / "persistente.sqlite3"
        primera = Agenda(ruta)
        prog = _agregar(primera, workflow)
        primera.close()

        segunda = Agenda(ruta)
        try:
            assert [p.id for p in segunda.listar()] == [prog.id]
        finally:
            segunda.close()
