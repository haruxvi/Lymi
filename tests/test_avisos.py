"""Avisos: lo que lymi cuenta sin que mires la pagina (bandeja y avisos de la interfaz)."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from starlette.testclient import TestClient

from lymi.avisos import Avisos, eventos_proximos
from lymi.triggers.servidor import ConfigServidor, abrir_estado, cerrar_estado, lanzar
from lymi.ui.app import ConfigUI, crear_app_ui

TOKEN = "a" * 40


def test_cola_cursor_y_sin_repetir() -> None:
    avisos = Avisos(maximo=3)
    assert avisos.publicar("evento", "uno", clave="x") is not None
    assert avisos.publicar("evento", "uno otra vez", clave="x") is None  # un evento avisa una vez
    for i in range(4):
        avisos.publicar("terminado", f"t{i}")
    assert [a.titulo for a in avisos.despues_de(0)] == ["t1", "t2", "t3"]  # acotada
    ultimo = avisos.ultimo()
    avisos.publicar("error", "nuevo")
    assert [a.titulo for a in avisos.despues_de(ultimo)] == ["nuevo"]


def test_eventos_que_empiezan_pronto(tmp_path, monkeypatch) -> None:
    zona = ZoneInfo("America/Santiago")
    ahora = datetime.now(zona).replace(second=0, microsecond=0)
    def ics(nombre: str, inicio: datetime) -> str:
        return (f"BEGIN:VEVENT\nUID:{nombre}\nDTSTART;TZID=America/Santiago:{inicio:%Y%m%dT%H%M%S}\n"
                f"DURATION:PT30M\nSUMMARY:{nombre}\nEND:VEVENT\n")
    (tmp_path / "c.ics").write_text(
        "BEGIN:VCALENDAR\n" + ics("Reunion", ahora + timedelta(minutes=10)) + ics("Tarde", ahora + timedelta(hours=3))
        + "END:VCALENDAR\n", encoding="utf-8")
    monkeypatch.setenv("LYMI_CALENDARIO", str(tmp_path))
    avisos = Avisos()
    assert eventos_proximos(avisos, ahora) == 1
    (aviso,) = avisos.despues_de(0)
    assert aviso.titulo == "En 10 min: Reunion" and aviso.enlace == "#/calendario"
    assert eventos_proximos(avisos, ahora + timedelta(minutes=1)) == 0  # no se repite


def test_sin_calendario_no_hay_nada_que_vigilar(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LYMI_CALENDARIO", str(tmp_path / "nada"))
    assert eventos_proximos(Avisos()) == 0


def test_una_programacion_que_termina_avisa(tmp_path) -> None:
    flujo = tmp_path / "hola.yml"
    flujo.write_text(yaml.safe_dump({"name": "hola", "steps": [{"id": "x", "type": "transform", "set": {"a": "1"}}]}),
                     encoding="utf-8")
    avisos = Avisos()
    config = ConfigServidor(ledger=tmp_path / "l.sqlite3", agenda=tmp_path / "a.sqlite3", ganchos=tmp_path / "g.sqlite3",
                            intervalo_agenda=None, avisos=avisos)

    async def correr() -> None:
        estado = abrir_estado(config)
        try:
            assert lanzar(estado, flujo, {}, frozenset(), "agenda:abc")
            await asyncio.wait(set(estado.tareas))
        finally:
            await cerrar_estado(estado)

    asyncio.run(correr())
    (aviso,) = avisos.despues_de(0)
    assert aviso.tipo == "programacion" and aviso.titulo == "hola: listo" and aviso.enlace.startswith("#/corridas/")


def test_la_interfaz_avisa_aprobaciones_y_trabajos_terminados(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "workflows").mkdir()
    (tmp_path / "workflows" / "w.yml").write_text(yaml.safe_dump({"name": "w", "steps": [
        {"id": "guardar", "type": "pc", "op": "escribir", "ruta": "salidas/x.md", "contenido": "hola"}]}), encoding="utf-8")
    avisos = Avisos()
    config = ConfigUI(ledger=tmp_path / "l.sqlite3", workflows=tmp_path / "workflows", memoria=tmp_path / "m.sqlite3",
                      hosts=frozenset({"testserver"}), token=TOKEN, proveedores=lambda: (None, None, None, None),
                      avisos=avisos, avisos_nativos=True)
    with TestClient(crear_app_ui(config)) as c:
        c.headers.update({"X-Lymi-Token": TOKEN})
        assert c.get("/api/avisos").json() == {"avisos": [], "ultimo": 0, "nativos": True}
        t = c.post("/api/workflows/w.yml/correr", json={"entradas": {}}).json()
        limite = time.monotonic() + 10
        while not avisos.despues_de(0) and time.monotonic() < limite:
            time.sleep(0.05)
        (pide,) = avisos.despues_de(0)
        assert pide.tipo == "aprobacion" and pide.enlace == "#/workflows/w.yml" and "guardar" in pide.texto
        c.post(f"/api/trabajos/{t['id']}/aprobacion", json={"decision": "rechazar"})
        while len(avisos.despues_de(0)) < 2 and time.monotonic() < limite:
            time.sleep(0.05)
        termino = avisos.despues_de(pide.id)[0]
        assert termino.tipo == "error" and termino.titulo == "No termino: w" and "rechazado" in termino.texto
        assert [a["id"] for a in c.get(f"/api/avisos?desde={pide.id}").json()["avisos"]] == [termino.id]
    assert not Path(tmp_path / "salidas" / "x.md").exists()
    assert datetime.fromisoformat(termino.ts) <= datetime.now(UTC)
