"""Voz: dictado con whisper.cpp y lectura con la voz del sistema, sin red y sin guardar audio."""

from __future__ import annotations

import struct
import subprocess
import sys
import time
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from lymi import voz
from lymi.ui.app import ConfigUI, crear_app_ui

TOKEN = "v" * 40


def wav(segundos: float = 0.5) -> bytes:
    muestras = int(16000 * segundos)
    datos = b"\x00\x00" * muestras
    return (b"RIFF" + struct.pack("<I", 36 + len(datos)) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, 16000, 32000, 2, 16)
            + b"data" + struct.pack("<I", len(datos)) + datos)


@pytest.fixture
def carpeta(tmp_path, monkeypatch) -> Path:
    destino = tmp_path / "voz"
    destino.mkdir()
    monkeypatch.setenv("LYMI_VOZ", str(destino))
    monkeypatch.delenv("LYMI_WHISPER", raising=False)
    monkeypatch.delenv("LYMI_WHISPER_MODELO", raising=False)
    monkeypatch.setattr(voz.shutil, "which", lambda _nombre: None)  # el PATH de quien corre la suite no cuenta
    return destino


class TestTranscriptor:
    def test_sin_whisper_dice_de_donde_sacarlo(self, carpeta) -> None:
        with pytest.raises(voz.VozError, match="github.com/ggml-org/whisper.cpp"):
            voz.buscar_transcriptor()

    def test_sin_modelo_sugiere_uno_por_hardware(self, carpeta) -> None:
        (carpeta / "whisper-cli.exe").write_bytes(b"MZ")
        with pytest.raises(voz.VozError, match=r"conviene ggml-(tiny|base|small)\.bin"):
            voz.buscar_transcriptor()

    def test_elige_el_sugerido_si_esta(self, carpeta, monkeypatch) -> None:
        (carpeta / "whisper-cli.exe").write_bytes(b"MZ")
        for nombre in ("ggml-tiny.bin", "ggml-base.bin"):
            (carpeta / nombre).write_bytes(b"x")
        monkeypatch.setattr(voz, "memoria_gb", lambda: 12.0)
        t = voz.buscar_transcriptor()
        assert t.nombre_modelo == "base" and t.binario.name == "whisper-cli.exe"

    def test_modelo_por_hardware(self) -> None:
        assert [voz.modelo_sugerido(g) for g in (4, 12, 32)] == ["ggml-tiny.bin", "ggml-base.bin", "ggml-small.bin"]


class TestTranscribir:
    def test_solo_wav_y_con_tope(self) -> None:
        with pytest.raises(voz.VozError, match="no es WAV"):
            voz.validar_wav(b"ID3 mp3...")
        with pytest.raises(voz.VozError, match="supera"):
            voz.validar_wav(b"RIFF" + b"\x00" * voz.MAX_BYTES_AUDIO)

    def test_llama_a_whisper_y_borra_el_audio(self, tmp_path, monkeypatch) -> None:
        vistos: dict = {}

        def falso(cmd, **kw):
            entrada = Path(cmd[cmd.index("-f") + 1])
            vistos["audio"] = entrada
            vistos["existia"] = entrada.is_file()
            Path(cmd[cmd.index("-of") + 1] + ".txt").write_text("  hola   lymi \n", encoding="utf-8")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(voz.subprocess, "run", falso)
        t = voz.Transcriptor(tmp_path / "whisper-cli.exe", tmp_path / "ggml-base.bin")
        r = voz.transcribir(wav(), "es", t)
        assert r.texto == "hola lymi" and r.modelo == "base"
        assert vistos["existia"] and not vistos["audio"].exists()  # el audio no se queda en disco

    def test_un_fallo_de_whisper_se_explica(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(voz.subprocess, "run",
                            lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "error: modelo corrupto"))
        with pytest.raises(voz.VozError, match="modelo corrupto"):
            voz.transcribir(wav(), "es", voz.Transcriptor(tmp_path / "w", tmp_path / "ggml-tiny.bin"))


class TestLectura:
    def test_markdown_para_el_oido(self) -> None:
        texto = "## Hoy\n- **Reunion** a las 9 con [Ana](https://x.cl)\n```py\nprint(1)\n```\nVer https://ejemplo.com"
        assert voz.limpiar_para_leer(texto) == "Hoy - Reunion a las 9 con Ana (bloque de codigo) Ver un enlace"

    def test_el_texto_va_por_la_entrada_estandar(self, tmp_path, monkeypatch) -> None:
        salida = tmp_path / "leido.txt"
        guion = f"import sys; open(r'{salida}', 'w', encoding='utf-8').write(sys.stdin.read())"
        monkeypatch.setattr(voz, "motor_de_voz", lambda: [sys.executable, "-c", guion])
        lector = voz.Lector()
        lector.hablar('Hola "; rm -rf / ; echo "')  # en la linea de comandos seria peligroso; por stdin es texto
        limite = time.monotonic() + 10
        while not (salida.exists() and salida.read_text(encoding="utf-8")) and time.monotonic() < limite:
            time.sleep(0.05)
        assert salida.read_text(encoding="utf-8") == 'Hola "; rm -rf / ; echo "'

    def test_callar_corta_lo_que_suena(self, monkeypatch) -> None:
        monkeypatch.setattr(voz, "motor_de_voz", lambda: [sys.executable, "-c", "import time; time.sleep(30)"])
        lector = voz.Lector()
        lector.hablar("algo largo")
        assert lector.callar() is True and lector.callar() is False


def test_api_de_voz(tmp_path, carpeta, monkeypatch) -> None:
    monkeypatch.setattr(voz, "motor_de_voz", lambda: None)
    config = ConfigUI(ledger=tmp_path / "l.sqlite3", workflows=tmp_path, memoria=tmp_path / "m.sqlite3",
                      hosts=frozenset({"testserver"}), token=TOKEN, proveedores=lambda: (None, None, None, None))
    with TestClient(crear_app_ui(config)) as c:
        c.headers.update({"X-Lymi-Token": TOKEN})
        e = c.get("/api/voz").json()
        assert not e["dictado"]["disponible"] and "whisper" in e["dictado"]["motivo"] and not e["lectura"]["disponible"]
        r = c.post("/api/voz/transcribir", content=wav(), headers={"Content-Type": "audio/wav"})
        assert r.status_code == 400 and "whisper" in r.json()["error"]
        assert c.post("/api/voz/transcribir", content=b"x" * (voz.MAX_BYTES_AUDIO + 1)).status_code == 413
        assert c.post("/api/voz/hablar", json={"texto": "hola"}).status_code == 400  # sin voz del sistema, se dice
        assert c.post("/api/voz/callar", json={}).json() == {"callado": False}
        assert c.post("/api/voz/transcribir", content=wav(), headers={"X-Lymi-Token": "otro"}).status_code == 403
