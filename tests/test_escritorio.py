"""App de escritorio: carpeta de datos, instancia unica, motor y vigilancia de red."""

from __future__ import annotations

import sys

import pytest
from starlette.testclient import TestClient

from lymi import escritorio, vigia_red


class TestCarpetaDeDatos:
    def test_lymi_home_manda(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("LYMI_HOME", str(tmp_path / "datos"))
        assert escritorio.hogar() == tmp_path / "datos"

    def test_copia_ejemplos_una_vez_y_nunca_pisa(self, tmp_path) -> None:
        origen = tmp_path / "origen"
        (origen / "workflows").mkdir(parents=True)
        (origen / "workflows" / "a.yml").write_text("name: a\n", encoding="utf-8")
        destino = tmp_path / "datos"

        assert escritorio.preparar_hogar(destino, origen) == ["workflows"]
        assert (destino / "runs").is_dir()
        # La persona borra el ejemplo y edita otro: el siguiente arranque no repone ni pisa.
        (destino / "workflows" / "a.yml").unlink()
        (destino / "workflows" / "mio.yml").write_text("propio", encoding="utf-8")
        assert escritorio.preparar_hogar(destino, origen) == []
        assert [p.name for p in (destino / "workflows").iterdir()] == ["mio.yml"]

    def test_los_ejemplos_del_repositorio_existen(self) -> None:
        for nombre in escritorio.EJEMPLOS:
            assert (escritorio.recursos() / nombre).is_dir()


def test_instancia_unica(tmp_path) -> None:
    candado = tmp_path / "runs" / "escritorio.candado"
    with escritorio.instancia_unica(candado) as primera:
        assert primera
        if sys.platform == "win32":  # msvcrt bloquea por manejador: un segundo open choca
            with escritorio.instancia_unica(candado) as segunda:
                assert not segunda
    with escritorio.instancia_unica(candado) as otra_vez:
        assert otra_vez  # al salir se suelta


class TestMotor:
    def test_qt_por_defecto(self, monkeypatch) -> None:
        monkeypatch.delenv("LYMI_MOTOR", raising=False)
        monkeypatch.setattr("importlib.util.find_spec", lambda nombre: object())
        assert escritorio.elegir_motor() == "qt"

    def test_sin_qt_no_cae_a_edge_en_silencio(self, monkeypatch) -> None:
        monkeypatch.delenv("LYMI_MOTOR", raising=False)
        monkeypatch.setattr("importlib.util.find_spec", lambda nombre: None)
        with pytest.raises(escritorio.MotorError, match="Qt WebEngine"):
            escritorio.elegir_motor()

    def test_edge_solo_si_se_pide(self, monkeypatch) -> None:
        monkeypatch.setenv("LYMI_MOTOR", "edge")
        assert escritorio.elegir_motor() == "edge"
        with pytest.raises(escritorio.MotorError, match="desconocido"):
            escritorio.elegir_motor("firefox")


def test_la_app_sirve_la_interfaz_y_corre_la_agenda(tmp_path) -> None:
    escritorio.preparar_hogar(tmp_path, escritorio.recursos())
    app = escritorio.crear_app_escritorio(tmp_path, 4321)
    with TestClient(app, base_url="http://127.0.0.1:4321") as cliente:
        pagina = cliente.get("/")
        assert pagina.status_code == 200 and "lymi-token" in pagina.text
        assert app.state.lymi.agenda is not None  # el ciclo de la agenda esta vivo
        assert cliente.get("/", headers={"host": "localhost:4321"}).status_code == 421
    assert (tmp_path / "runs" / "agenda.sqlite3").is_file()


def test_arranca_y_cierra_en_un_puerto_efimero(tmp_path) -> None:
    import httpx

    toma, puerto = escritorio.puerto_libre()
    servidor = escritorio.arrancar(escritorio.crear_app_escritorio(tmp_path, puerto), toma, puerto)
    try:
        assert servidor.url == f"http://127.0.0.1:{puerto}/"
        assert httpx.get(servidor.url, timeout=5).status_code == 200
    finally:
        servidor.cerrar()
    assert not servidor.hilo.is_alive()


class TestInforme:
    def test_cero_conexiones(self) -> None:
        vigia = escritorio.Vigia(10)
        vigia.muestras = 5
        assert "0 conexiones fuera de esta maquina" in vigia.informe("qt")

    def test_lista_destinos(self) -> None:
        vigia = escritorio.Vigia(10)
        vigia.muestras, vigia.vistas = 5, {("TCP", "52.97.51.114", 443): 4}
        informe = vigia.informe("edge")
        assert "1 destinos" in informe and "52.97.51.114:443" in informe


# ---------------------------------------------------------------- vigia_red

NETSTAT = """
Conexiones activas

  Proto  Direccion local        Direccion remota       Estado           PID
  TCP    0.0.0.0:135            0.0.0.0:0              LISTENING       2036
  TCP    127.0.0.1:54457        127.0.0.1:60001        ESTABLISHED     500
  TCP    192.168.1.5:60640      52.97.51.114:443       ESTABLISHED     500
  TCP    192.168.1.5:60641      20.1.1.1:443           ESTABLISHED     999
  TCP    [::1]:5000             [::1]:6000             ESTABLISHED     500
  TCP    [2800::5]:7000         [2606:4700::1]:443     ESTABLISHED     501
  UDP    0.0.0.0:5353           *:*                                    500
"""


class TestVigiaRed:
    def test_netstat_solo_externas_del_arbol(self) -> None:
        halladas = vigia_red.leer_netstat(NETSTAT, {500, 501})
        assert [(c.remoto, c.puerto, c.pid) for c in halladas] == [
            ("52.97.51.114", 443, 500),
            ("2606:4700::1", 443, 501),
        ]

    def test_descendientes(self) -> None:
        pares = [(1, 0), (10, 1), (11, 10), (12, 11), (20, 2), (13, 13)]
        assert vigia_red.descendientes(10, pares) == {10, 11, 12}

    def test_direcciones_de_proc(self) -> None:
        assert vigia_red.direccion_proc("0100007F:1F90") == ("127.0.0.1", 8080)
        assert vigia_red.direccion_proc("00000000000000000000000001000000:0050") == ("::1", 80)

    def test_proc_net_y_mapeado_ipv4(self) -> None:
        texto = (
            "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
            "   0: 0100007F:1F90 7233610A:01BB 01 00000000:00000000 00:00000000 00000000  1000        0 4242 1\n"
        )
        assert vigia_red.leer_proc_net(texto, "tcp") == {4242: ("10.97.51.114", 443)}
        assert not vigia_red.es_externa("::ffff:127.0.0.1")
        assert vigia_red.es_externa("::ffff:8.8.8.8")

    def test_lsof(self) -> None:
        texto = (
            "COMMAND   PID USER   FD   TYPE DEVICE SIZE/OFF NODE NAME\n"
            "lymi     700 ana   12u  IPv4 0x1      0t0  TCP 127.0.0.1:5000->127.0.0.1:6000 (ESTABLISHED)\n"
            "lymi     701 ana   13u  IPv4 0x2      0t0  TCP 10.0.0.2:5001->17.253.1.1:443 (ESTABLISHED)\n"
            "lymi     700 ana   14u  IPv4 0x3      0t0  UDP *:5353\n"
        )
        assert [str(c) for c in vigia_red.leer_lsof(texto)] == ["TCP 17.253.1.1:443 (pid 701)"]

    def test_lo_ilegible_se_reporta(self) -> None:
        assert vigia_red.es_externa("no-es-una-ip")
        assert not vigia_red.es_externa("0.0.0.0")

    @pytest.mark.skipif(not vigia_red.disponible(), reason="sin vigilancia en esta plataforma")
    def test_este_proceso_en_vivo(self) -> None:
        assert isinstance(vigia_red.conexiones_externas(), list)
