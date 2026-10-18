"""Voz: dictarle a lymi y que lea sus respuestas, todo en esta maquina.

- **Dictado:** whisper.cpp como programa externo (`whisper-cli`). Es codigo abierto,
  corre sin red y sin telemetria. Se busca en `LYMI_WHISPER`, en el PATH o en la
  carpeta `voz/` de los datos. El modelo se elige por el hardware y **siempre se
  declara cual se uso**: bajar de precision en silencio no es una opcion.
- **Lectura:** la voz del sistema operativo (SAPI en Windows, `say` en macOS,
  `espeak-ng` en Linux). Sin servicios en la nube.

El audio dictado vive solo lo que tarda la transcripcion: un archivo temporal que
se borra al terminar. No se guarda ni pasa por el ledger, como no pasa leer tu
correo: no sale de la maquina ni gasta tokens.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

MAX_BYTES_AUDIO = 12_000_000
"""~6 minutos de WAV mono a 16 kHz. Mas que eso no es un dictado."""
TIMEOUT_TRANSCRIPCION = 180
MAX_CARACTERES_LECTURA = 3000
BINARIOS = ("whisper-cli", "whisper-cpp", "whisper")
MODELOS_POR_PREFERENCIA = ("ggml-small.bin", "ggml-base.bin", "ggml-small-q5_1.bin", "ggml-base-q5_1.bin",
                           "ggml-tiny.bin", "ggml-medium.bin", "ggml-large-v3-turbo.bin")


class VozError(RuntimeError):
    """No hay con que dictar o leer, o el audio no sirve. El mensaje dice como arreglarlo."""


def _sin_ventana() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def carpeta_voz() -> Path:
    return Path(os.environ.get("LYMI_VOZ", "voz"))


def memoria_gb() -> float:
    """RAM total, para sugerir un modelo que la maquina aguante."""
    if os.name == "nt":
        import ctypes

        class Estado(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        estado = Estado()
        estado.dwLength = ctypes.sizeof(Estado)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(estado))
        return estado.ullTotalPhys / 2**30
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30
    except (ValueError, OSError, AttributeError):
        return 8.0


def modelo_sugerido(gb: float | None = None) -> str:
    """Modo bajo rendimiento por hardware (idea de colibri), declarado: tiny < 8 GB < base < 16 GB <= small."""
    gb = memoria_gb() if gb is None else gb
    return "ggml-tiny.bin" if gb < 8 else "ggml-base.bin" if gb < 16 else "ggml-small.bin"


@dataclass(frozen=True, slots=True)
class Transcriptor:
    binario: Path
    modelo: Path

    @property
    def nombre_modelo(self) -> str:
        return self.modelo.name.removeprefix("ggml-").removesuffix(".bin")


def buscar_transcriptor() -> Transcriptor:
    """El whisper.cpp y el modelo con que dictar. Si falta algo, dice que y como conseguirlo."""
    carpeta = carpeta_voz()
    binario: Path | None = None
    if propio := os.environ.get("LYMI_WHISPER"):
        binario = Path(propio)
    else:
        for nombre in BINARIOS:
            if encontrado := shutil.which(nombre):
                binario = Path(encontrado)
                break
        else:
            for nombre in BINARIOS:
                for candidato in (carpeta / nombre, carpeta / f"{nombre}.exe"):
                    if candidato.is_file():
                        binario = candidato
                        break
                if binario:
                    break
    if binario is None or not binario.is_file():
        raise VozError(
            "falta whisper.cpp para dictar. Descarga `whisper-cli` desde "
            "https://github.com/ggml-org/whisper.cpp/releases y dejalo en la carpeta "
            f"{carpeta.resolve()} (o define LYMI_WHISPER con su ruta)"
        )
    if propio := os.environ.get("LYMI_WHISPER_MODELO"):
        modelo = Path(propio)
    else:
        modelos = [carpeta / m for m in MODELOS_POR_PREFERENCIA if (carpeta / m).is_file()]
        modelos += sorted(p for p in carpeta.glob("ggml-*.bin") if p not in modelos)
        sugerido = carpeta / modelo_sugerido()
        modelo = sugerido if sugerido in modelos else (modelos[0] if modelos else sugerido)
    if not modelo.is_file():
        raise VozError(
            f"falta el modelo de whisper. Para esta maquina ({memoria_gb():.0f} GB de RAM) conviene "
            f"{modelo_sugerido()}: descargalo de https://huggingface.co/ggerganov/whisper.cpp y dejalo en "
            f"{carpeta.resolve()}"
        )
    return Transcriptor(binario, modelo)


@dataclass(frozen=True, slots=True)
class Transcripcion:
    texto: str
    modelo: str
    segundos: float


def validar_wav(audio: bytes) -> None:
    if len(audio) > MAX_BYTES_AUDIO:
        raise VozError(f"el audio supera {MAX_BYTES_AUDIO // 1_000_000} MB: dicta en partes mas cortas")
    if len(audio) < 44 or audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
        raise VozError("el audio no es WAV")


def transcribir(audio: bytes, idioma: str = "es", transcriptor: Transcriptor | None = None) -> Transcripcion:
    validar_wav(audio)
    t = transcriptor or buscar_transcriptor()
    inicio = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="lymi-voz-") as carpeta:
        entrada = Path(carpeta) / "dictado.wav"
        entrada.write_bytes(audio)
        salida = Path(carpeta) / "dictado"
        try:
            proc = subprocess.run(
                [str(t.binario), "-m", str(t.modelo), "-f", str(entrada), "-l", idioma, "-nt", "-otxt",
                 "-of", str(salida), "-np"],
                capture_output=True, text=True, errors="replace", timeout=TIMEOUT_TRANSCRIPCION, check=False,
                creationflags=_sin_ventana(),
            )
        except subprocess.TimeoutExpired:
            raise VozError(f"whisper no termino en {TIMEOUT_TRANSCRIPCION} s: prueba un modelo mas chico") from None
        except OSError as exc:
            raise VozError(f"no se pudo ejecutar {t.binario}: {exc}") from None
        texto_archivo = salida.with_suffix(".txt")
        if proc.returncode != 0 or not texto_archivo.is_file():
            detalle = (proc.stderr or proc.stdout or "").strip().splitlines()[-1:] or [f"codigo {proc.returncode}"]
            raise VozError(f"whisper fallo: {detalle[0][:300]}")
        texto = " ".join(texto_archivo.read_text(encoding="utf-8", errors="replace").split())
    return Transcripcion(texto, t.nombre_modelo, round(time.perf_counter() - inicio, 2))


# ---------------------------------------------------------------- lectura en voz alta

_SAPI = (
    "Add-Type -AssemblyName System.Speech; $v = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
    "$e = $v.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -like 'es*' } | Select-Object -First 1; "
    "if ($e) { $v.SelectVoice($e.VoiceInfo.Name) }; $t = [Console]::In.ReadToEnd(); $v.Speak($t)"
)


def motor_de_voz() -> list[str] | None:
    """El comando que lee texto de la entrada estandar con la voz del sistema, o None."""
    if os.name == "nt":
        return ["powershell", "-NoProfile", "-NonInteractive", "-Command", _SAPI]
    if sys.platform == "darwin" and shutil.which("say"):
        return ["say"]
    for nombre in ("espeak-ng", "espeak"):
        if shutil.which(nombre):
            return [nombre, "-v", "es", "--stdin"]
    return None


class Lector:
    """Lee un texto a la vez. Uno nuevo corta el anterior; `callar` corta el actual."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._proceso: subprocess.Popen[str] | None = None

    def hablar(self, texto: str) -> None:
        comando = motor_de_voz()
        if comando is None:
            raise VozError("no hay voz del sistema: en Linux instala espeak-ng")
        texto = limpiar_para_leer(texto)
        if not texto:
            return
        self.callar()
        with self._lock:
            # El texto va por la entrada estandar, nunca en la linea de comandos: no se interpreta.
            self._proceso = subprocess.Popen(
                comando, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True,
                encoding="utf-8", creationflags=_sin_ventana(),
            )
            proceso = self._proceso
        threading.Thread(target=self._enviar, args=(proceso, texto), daemon=True).start()

    @staticmethod
    def _enviar(proceso: subprocess.Popen[str], texto: str) -> None:
        try:
            assert proceso.stdin is not None
            proceso.stdin.write(texto)
            proceso.stdin.close()
        except OSError:
            pass  # lo callaron antes de terminar de escribir

    def callar(self) -> bool:
        with self._lock:
            proceso, self._proceso = self._proceso, None
        if proceso is not None and proceso.poll() is None:
            proceso.kill()
            return True
        return False


def limpiar_para_leer(texto: str) -> str:
    """Markdown a texto para el oido: sin simbolos, sin URLs, sin bloques de codigo."""
    import re

    texto = re.sub(r"```.*?```", " (bloque de codigo) ", texto, flags=re.DOTALL)
    texto = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", texto)
    texto = re.sub(r"https?://\S+", "un enlace", texto)
    texto = re.sub(r"[`*_#>|]+", " ", texto)
    texto = " ".join(texto.split())
    return texto[:MAX_CARACTERES_LECTURA]


def estado() -> dict[str, object]:
    """Que hay para dictar y leer en esta maquina, y que falta."""
    try:
        t = buscar_transcriptor()
        dictado: dict[str, object] = {"disponible": True, "binario": str(t.binario), "modelo": t.nombre_modelo}
    except VozError as exc:
        dictado = {"disponible": False, "motivo": str(exc)}
    dictado["sugerido"] = modelo_sugerido()
    dictado["memoria_gb"] = round(memoria_gb(), 1)
    comando = motor_de_voz()
    lectura = {"disponible": comando is not None, "motor": comando[0] if comando else None}
    return {"dictado": dictado, "lectura": lectura}
