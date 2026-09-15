"""Suite destructiva del ejecutor del host.

La puerta de `ARQUITECTURA_AGENTE_SEGURO.md`: cada intento de romper el sistema
termina bloqueado o deshecho sin perdida.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from lymi.ejecutor import (
    CapacidadDenegada,
    Comando,
    Diario,
    DiarioError,
    Ejecutor,
    EjecutorError,
    Perfil,
    PerfilError,
    cargar_perfil,
    deshacer,
)
from lymi.privacidad.etiquetas import Nivel


@pytest.fixture
def entorno(tmp_path):
    base = tmp_path / "proyecto"
    trabajo = base / "salidas"
    trabajo.mkdir(parents=True)
    diario = Diario(tmp_path / "diario" / "corrida1")
    perfil = Perfil.por_defecto(base)
    perfil.comandos["python"] = Comando("python", sys.executable)
    return Ejecutor(perfil, diario, base=base), base, trabajo, diario


class TestZonasVetadas:
    def test_el_sistema_operativo_aunque_el_perfil_lo_permita(self, tmp_path) -> None:
        sistema = Path(os.environ.get("SystemRoot", "/etc"))
        perfil = Perfil(escribibles=[sistema], legibles=[sistema])
        ejecutor = Ejecutor(perfil, Diario(tmp_path / "d"), base=tmp_path)
        with pytest.raises(CapacidadDenegada, match="zona protegida"):
            ejecutor.escribir(str(sistema / "lymi-prueba.txt"), "x")
        assert not (sistema / "lymi-prueba.txt").exists()

    def test_credenciales_del_usuario(self, tmp_path) -> None:
        casa = Path.home()
        ejecutor = Ejecutor(Perfil(escribibles=[casa], legibles=[casa]), Diario(tmp_path / "d"), base=tmp_path)
        with pytest.raises(CapacidadDenegada, match="zona protegida"):
            ejecutor.escribir("~/.ssh/authorized_keys", "ssh-rsa ATAQUE")
        with pytest.raises(CapacidadDenegada):
            ejecutor.leer("~/.aws/credentials")

    def test_el_agente_no_toca_su_propia_auditoria(self, entorno) -> None:
        ejecutor, base, *_ = entorno
        ejecutor.perfil.escribibles.append(base)
        for ruta in ("runs/lymi.sqlite3", "runs/PARAR", ".git/config"):
            with pytest.raises(CapacidadDenegada, match="zona protegida"):
                ejecutor.escribir(ruta, "x")

    def test_salir_de_la_carpeta_con_puntos(self, entorno) -> None:
        ejecutor, *_ = entorno
        with pytest.raises(CapacidadDenegada, match="fuera de las carpetas escribibles"):
            ejecutor.escribir("salidas/../../fuera.txt", "x")

    @pytest.mark.parametrize(
        "ruta", ["\\\\servidor\\compartido\\x.txt", "salidas/nota.txt:oculto", "salidas/CON.txt", "salidas/nul"]
    )
    def test_formas_de_ruta_peligrosas(self, entorno, ruta) -> None:
        ejecutor, *_ = entorno
        with pytest.raises(CapacidadDenegada):
            ejecutor.escribir(ruta, "x")

    def test_un_enlace_que_apunta_afuera(self, entorno, tmp_path) -> None:
        ejecutor, _, trabajo, _ = entorno
        afuera = tmp_path / "afuera"
        afuera.mkdir()
        try:
            (trabajo / "atajo").symlink_to(afuera, target_is_directory=True)
        except OSError:
            pytest.skip("este sistema no permite crear enlaces simbolicos sin privilegios")
        with pytest.raises(CapacidadDenegada):
            ejecutor.escribir("salidas/atajo/robado.txt", "x")
        assert not (afuera / "robado.txt").exists()


class TestDeshacer:
    def test_sobrescribir_borrar_y_mover_se_deshacen_sin_perdida(self, entorno) -> None:
        ejecutor, _, trabajo, diario = entorno
        (trabajo / "importante.txt").write_text("original", encoding="utf-8")
        (trabajo / "otro.txt").write_text("otro", encoding="utf-8")

        ejecutor.escribir("salidas/importante.txt", "sobrescrito")
        ejecutor.escribir("salidas/nuevo.txt", "creado")
        ejecutor.borrar("salidas/otro.txt")
        ejecutor.mover("salidas/nuevo.txt", "salidas/movido.txt")

        assert not (trabajo / "otro.txt").exists()
        informe = deshacer(diario.carpeta)

        assert (trabajo / "importante.txt").read_text(encoding="utf-8") == "original"
        assert (trabajo / "otro.txt").read_text(encoding="utf-8") == "otro"
        assert not (trabajo / "nuevo.txt").exists()
        assert not (trabajo / "movido.txt").exists()
        assert len(informe) == 4

    def test_borrar_nunca_elimina_de_verdad(self, entorno) -> None:
        ejecutor, _, trabajo, diario = entorno
        (trabajo / "x.txt").write_text("contenido", encoding="utf-8")
        ejecutor.borrar("salidas/x.txt")
        copias = list((diario.carpeta / "copias").iterdir())
        assert [c.read_text(encoding="utf-8") for c in copias] == ["contenido"]

    def test_no_se_deshace_dos_veces(self, entorno) -> None:
        ejecutor, _, _, diario = entorno
        ejecutor.escribir("salidas/a.txt", "a")
        deshacer(diario.carpeta)
        with pytest.raises(DiarioError, match="ya se deshizo"):
            deshacer(diario.carpeta)

    def test_sin_diario(self, tmp_path) -> None:
        with pytest.raises(DiarioError):
            deshacer(tmp_path / "no-existe")


class TestComandos:
    def test_fuera_de_la_lista_blanca(self, entorno) -> None:
        ejecutor, *_ = entorno
        with pytest.raises(CapacidadDenegada, match="lista blanca"):
            ejecutor.ejecutar("powershell", ["Remove-Item", "-Recurse", "C:\\"])

    def test_subcomando_no_permitido(self, entorno) -> None:
        ejecutor, *_ = entorno
        ejecutor.perfil.comandos["git"] = Comando("git", "git", frozenset({"status", "diff"}))
        with pytest.raises(CapacidadDenegada, match="solo se permite"):
            ejecutor.ejecutar("git", ["push", "--force"])

    def test_corre_sin_shell_y_sin_secretos_del_entorno(self, entorno, monkeypatch) -> None:
        ejecutor, _, _, diario = entorno
        monkeypatch.setenv("LYMI_SECRETO_DE_PRUEBA", "no-debe-llegar")
        codigo = "import os; print(os.environ.get('LYMI_SECRETO_DE_PRUEBA')); print('a && echo b')"
        salida = ejecutor.ejecutar("python", ["-c", codigo])
        assert salida["codigo"] == 0
        assert salida["stdout"].splitlines() == ["None", "a && echo b"]
        assert '"op": "comando"' in (diario.carpeta / "diario.jsonl").read_text(encoding="utf-8")

    def test_tiempo_limite(self, entorno) -> None:
        ejecutor, *_ = entorno
        with pytest.raises(EjecutorError, match="supero"):
            ejecutor.ejecutar("python", ["-c", "import time; time.sleep(5)"], timeout=0.5)

    def test_rechaza_bat_y_cmd(self, entorno, tmp_path) -> None:
        ejecutor, *_ = entorno
        lote = tmp_path / "lote.cmd"
        lote.write_text("@echo off", encoding="utf-8")
        ejecutor.perfil.comandos["lote"] = Comando("lote", str(lote))
        with pytest.raises(CapacidadDenegada, match="cmd.exe"):
            ejecutor.ejecutar("lote", [])


class TestLimites:
    def test_tope_de_archivos_tocados(self, entorno) -> None:
        ejecutor, *_ = entorno
        ejecutor.perfil.max_archivos = 2
        ejecutor.escribir("salidas/a.txt", "a")
        ejecutor.escribir("salidas/b.txt", "b")
        ejecutor.escribir("salidas/a.txt", "a2")  # el mismo archivo no cuenta dos veces
        with pytest.raises(CapacidadDenegada, match="2 archivos"):
            ejecutor.escribir("salidas/c.txt", "c")

    def test_tope_de_bytes(self, entorno) -> None:
        ejecutor, *_ = entorno
        ejecutor.perfil.max_bytes = 10
        with pytest.raises(CapacidadDenegada, match="bytes"):
            ejecutor.escribir("salidas/grande.txt", "x" * 11)

    def test_leer_reporta_la_etiqueta(self, entorno) -> None:
        ejecutor, base, *_ = entorno
        (base / ".env").write_text("CLAVE=secreta", encoding="utf-8")
        assert ejecutor.leer(".env").nivel is Nivel.NUNCA_SALE


class TestPerfil:
    def test_por_defecto_sin_comandos_y_solo_salidas(self, tmp_path) -> None:
        perfil = cargar_perfil(tmp_path / "no-existe.yml", tmp_path)
        assert perfil.comandos == {}
        assert perfil.escribibles == [(tmp_path / "salidas").resolve()]

    @pytest.mark.parametrize("contenido", [
        "comandos: {powershell: {}}",
        "comandos: {limpiar: {ejecutable: cmd}}",
        "escribibles: ['/']",
        "escribibles: ['~']",
        "clave_rara: 1",
        "max_archivos: -3",
    ])
    def test_perfiles_peligrosos_o_invalidos(self, tmp_path, contenido) -> None:
        archivo = tmp_path / "ejecutor.yml"
        archivo.write_text(contenido, encoding="utf-8")
        with pytest.raises(PerfilError):
            cargar_perfil(archivo, tmp_path)

    def test_perfil_valido(self, tmp_path) -> None:
        archivo = tmp_path / "ejecutor.yml"
        archivo.write_text(
            "escribibles: [trabajo]\nlegibles: [docs]\ncomandos: {git: {subcomandos: [status, diff]}}\nmax_archivos: 5",
            encoding="utf-8",
        )
        perfil = cargar_perfil(archivo, tmp_path)
        assert perfil.escribibles == [(tmp_path / "trabajo").resolve()]
        assert perfil.comandos["git"].subcomandos == frozenset({"status", "diff"})
        assert perfil.max_archivos == 5
