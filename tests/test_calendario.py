"""Calendario: lectura de .ics, zonas horarias, repeticiones y excepciones."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from typer.testing import CliRunner

from lymi.calendario import Calendario, CalendarioError, expandir, leer
from lymi.cli import app

SIMPLE = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:uno@ejemplo
DTSTART:20260920T130000Z
DTEND:20260920T140000Z
SUMMARY:Reunion con Ana
LOCATION:Oficina
END:VEVENT
BEGIN:VEVENT
UID:dos@ejemplo
DTSTART;VALUE=DATE:20260921
DTEND;VALUE=DATE:20260922
SUMMARY:Feriado
END:VEVENT
BEGIN:VEVENT
UID:tres@ejemplo
DTSTART:20260920T160000Z
SUMMARY:Cancelada
STATUS:CANCELLED
END:VEVENT
END:VCALENDAR
"""

REPETIDO = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:semanal@ejemplo
DTSTART;TZID=America/Santiago:20260921T090000
DURATION:PT30M
SUMMARY:Daily del equipo
RRULE:FREQ=WEEKLY;BYDAY=MO,WE;COUNT=4
EXDATE;TZID=America/Santiago:20260923T090000
END:VEVENT
END:VCALENDAR
"""

PLEGADO = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:largo@ejemplo
DTSTART:20260920T100000Z
DTEND:20260920T103000Z
SUMMARY:Revision del informe trimestral con el equipo
  de finanzas y el contador
LOCATION:Sala 2\\, piso 3
END:VEVENT
END:VCALENDAR
"""


@pytest.fixture
def carpeta(tmp_path) -> Path:
    (tmp_path / "personal.ics").write_text(SIMPLE, encoding="utf-8")
    return tmp_path


def ventana(dias: int = 30) -> tuple[datetime, datetime]:
    inicio = datetime(2026, 9, 20, tzinfo=UTC)
    return inicio, inicio + timedelta(days=dias)


class TestLectura:
    def test_eventos_con_hora_y_de_todo_el_dia(self, carpeta) -> None:
        eventos, avisos = Calendario(carpeta).eventos(*ventana())
        assert avisos == []
        assert [e.titulo for e in eventos] == ["Reunion con Ana", "Feriado"]  # la cancelada no aparece
        reunion, feriado = eventos
        assert reunion.inicio == datetime(2026, 9, 20, 13, tzinfo=UTC) and reunion.lugar == "Oficina"
        assert "20/09 13:00-14:00  Reunion con Ana  (Oficina)" == reunion.resumen()
        assert feriado.todo_el_dia and "todo el dia" in feriado.resumen()

    def test_zona_horaria_y_duracion(self, tmp_path) -> None:
        (tmp_path / "trabajo.ics").write_text(REPETIDO, encoding="utf-8")
        eventos, _ = Calendario(tmp_path).eventos(*ventana())
        primero = eventos[0]
        assert primero.inicio == datetime(2026, 9, 21, 9, tzinfo=ZoneInfo("America/Santiago"))
        assert primero.fin - primero.inicio == timedelta(minutes=30)

    def test_lineas_plegadas_y_escapes(self, tmp_path) -> None:
        (tmp_path / "x.ics").write_text(PLEGADO, encoding="utf-8")
        (evento,) = Calendario(tmp_path).eventos(*ventana())[0]
        # El estandar quita el salto y UN espacio: el segundo espacio es parte del texto.
        assert evento.titulo == "Revision del informe trimestral con el equipo de finanzas y el contador"
        assert evento.lugar == "Sala 2, piso 3"

    def test_sin_calendarios_lo_dice(self, tmp_path) -> None:
        with pytest.raises(CalendarioError, match="no hay archivos .ics"):
            Calendario(tmp_path / "vacio").eventos(*ventana())


class TestRepeticiones:
    def _bases(self, texto: str):
        bases, _ = leer(texto, "prueba")
        return bases

    def test_semanal_con_dias_cuenta_y_excepcion(self, tmp_path) -> None:
        (base,) = self._bases(REPETIDO)
        eventos = expandir(base, *ventana(60))
        # Lunes 21, miercoles 23 (excluido pero cuenta), lunes 28, miercoles 30: quedan 3 de 4.
        assert [e.inicio.day for e in eventos] == [21, 28, 30]

    def test_diario_con_until(self) -> None:
        texto = SIMPLE.replace(
            "SUMMARY:Reunion con Ana", "SUMMARY:Diario\nRRULE:FREQ=DAILY;UNTIL=20260923T130000Z")
        base = self._bases(texto)[0]
        assert [e.inicio.day for e in expandir(base, *ventana())] == [20, 21, 22, 23]

    def test_mensual_respeta_fin_de_mes(self) -> None:
        texto = SIMPLE.replace("DTSTART:20260920T130000Z", "DTSTART:20260131T130000Z").replace(
            "SUMMARY:Reunion con Ana", "SUMMARY:Pago\nRRULE:FREQ=MONTHLY;COUNT=3")
        base = self._bases(texto)[0]
        eventos = expandir(base, datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 7, 1, tzinfo=UTC))
        # Febrero no tiene 31: no hay ocurrencia (no se corre al 28).
        assert [(e.inicio.month, e.inicio.day) for e in eventos] == [(1, 31), (3, 31), (5, 31)]

    def test_una_regla_infinita_no_cuelga(self) -> None:
        texto = SIMPLE.replace("SUMMARY:Reunion con Ana", "SUMMARY:Siempre\nRRULE:FREQ=DAILY")
        base = self._bases(texto)[0]
        eventos = expandir(base, *ventana(10))
        assert len(eventos) == 10  # solo lo que cae en la ventana

    def test_regla_que_no_entiendo_se_omite(self) -> None:
        texto = SIMPLE.replace("SUMMARY:Reunion con Ana", "SUMMARY:Rara\nRRULE:FREQ=SECONDLY")
        assert expandir(self._bases(texto)[0], *ventana()) == []


def test_cli(carpeta, monkeypatch) -> None:
    monkeypatch.setenv("LYMI_CALENDARIO", str(carpeta))
    salida = CliRunner().invoke(app, ["calendario", "hoy", "--dias", "40"])
    assert salida.exit_code == 0
    assert "Reunion con Ana" in salida.output and "Cancelada" not in salida.output


def test_cli_sin_carpeta(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LYMI_CALENDARIO", str(tmp_path / "no-existe"))
    salida = CliRunner().invoke(app, ["calendario", "hoy"])
    assert salida.exit_code == 1 and "LYMI_CALENDARIO" in salida.output


def test_paso_de_workflow_y_herramienta_de_agente(carpeta, tmp_path, monkeypatch) -> None:
    import asyncio

    from lymi.flows.engine import ejecutar_flujo
    from lymi.flows.schema import Workflow
    from lymi.ledger import Ledger

    monkeypatch.setenv("LYMI_CALENDARIO", str(carpeta))
    flujo = Workflow.model_validate({"name": "agenda", "steps": [
        {"id": "hoy", "type": "calendario", "dias": 40, "carpeta": str(carpeta)},
    ]})
    ledger = Ledger(tmp_path / "l.sqlite3")
    try:
        r = asyncio.run(ejecutar_flujo(flujo, {}, ledger=ledger))
        assert r.ok, r.detalle
        assert "Reunion con Ana" in r.salidas["hoy"]["texto"]
        assert r.salidas["hoy"]["datos"][0]["lugar"] == "Oficina"
        fila = ledger.conn.execute(
            "SELECT provider, egress FROM calls WHERE run_id = ?", (r.run_id,)).fetchone()
        assert (fila["provider"], fila["egress"]) == ("calendario", 0)
    finally:
        ledger.close()


def test_el_informe_del_dia_es_valido() -> None:
    from lymi.flows.plan import planificar
    from lymi.flows.schema import cargar

    flujo = cargar(Path(__file__).resolve().parent.parent / "workflows" / "informe-del-dia.yml")
    filas = planificar(flujo)
    assert [f.tipo for f in filas] == ["correo", "calendario", "transform", "pc"]
    assert [f.costo for f in filas] == ["gratis"] * 4  # cero tokens remotos
    assert sum(f.efectos for f in filas) == 1  # solo escribir el informe pide aprobacion
