"""lymi como programa de escritorio: una ventana propia, sin navegador.

La ventana muestra la misma interfaz de `lymi ui`, servida en un puerto loopback
que elige el sistema al arrancar. Mientras la ventana esta abierta, la agenda
corre: el informe de las 08:00 no depende de acordarse de `lymi serve`.

Lo que se cuida aqui, ademas de lo que ya cuida la interfaz (host, token, CSP):

- **Una sola instancia.** Dos procesos revisando la misma agenda podrian lanzar
  dos veces la misma programacion. El segundo solo abre otra ventana.
- **La ventana no es un navegador.** Sin devtools, sin menu contextual, sin
  descargas, sin `file://`, sin almacenamiento persistente.
- **Un motor web que no llama a casa.** Por defecto, Qt WebEngine (Chromium
  abierto, sin servicios de Google ni de Microsoft). WebView2, el de Windows, se
  probo y abre conexiones a Microsoft que ninguna bandera apaga: solo se usa si
  se pide (`LYMI_MOTOR=edge`) y queda avisado. `--verificar-red` mide con quien
  habla todo el arbol de procesos, en vez de creerlo.
- **Los datos viven fuera del programa.** El instalado no tiene permisos de
  escritura donde esta; todo va a la carpeta de datos (`LYMI_HOME`).
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Self

log = logging.getLogger("lymi.escritorio")

TITULO = "lymi"
FONDO = "#191324"  # el --papel de riso.css: sin destello blanco al abrir
EJEMPLOS = ("workflows", "agencias")
MOTORES = ("qt", "edge")
AVISO_EDGE = (
    "Motor WebView2 de Microsoft: abre conexiones a Microsoft (datos de diagnostico de Windows) "
    "que lymi no puede apagar. Elegido a proposito con LYMI_MOTOR=edge."
)

ARGUMENTOS_MOTOR = (
    "--disable-features=ElasticOverscroll,msSmartScreenProtection,AutofillServerCommunication"
    " --disable-background-networking --disable-component-update --disable-domain-reliability"
    " --disable-sync --no-pings --metrics-recording-only"
)
"""Banderas de Chromium para ambos motores. La ventana solo muestra loopback, asi
que nada de esto le quita una funcion: le quita llamadas a casa."""


# ---------------------------------------------------------------- carpetas


def hogar() -> Path:
    """Donde viven los datos de lymi instalado: ledger, agenda, workflows, memoria."""
    if propia := os.environ.get("LYMI_HOME"):
        return Path(propia).expanduser()
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "lymi"
    base = os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
    return Path(base) / "lymi"


def recursos() -> Path:
    """Donde estan los ejemplos que trae lymi: el paquete congelado o el repositorio."""
    congelado = getattr(sys, "_MEIPASS", None)
    return Path(congelado) if congelado else Path(__file__).resolve().parents[2]


def preparar_hogar(destino: Path, origen: Path) -> list[str]:
    """Crea la carpeta de datos y copia los ejemplos que falten. Nunca pisa nada.

    Devuelve las carpetas copiadas. Una carpeta que ya existe se respeta entera:
    si la persona borro un workflow de ejemplo, no vuelve a aparecer.
    """
    destino.mkdir(parents=True, exist_ok=True)
    (destino / "runs").mkdir(exist_ok=True)
    copiadas: list[str] = []
    for nombre in EJEMPLOS:
        fuente, meta = origen / nombre, destino / nombre
        if fuente.is_dir() and not meta.exists():
            shutil.copytree(fuente, meta)
            copiadas.append(nombre)
    return copiadas


# ---------------------------------------------------------------- instancia


@contextlib.contextmanager
def instancia_unica(ruta: Path) -> Iterator[bool]:
    """True si este proceso es el unico; el candado se suelta al salir o al morir."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    archivo = ruta.open("a+b")
    try:
        archivo.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(archivo.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(archivo, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            yield False
            return
        yield True
    finally:
        archivo.close()  # cerrar suelta el candado en ambos sistemas


# ---------------------------------------------------------------- servidor


@dataclass(slots=True)
class Servidor:
    url: str
    servidor: Any
    hilo: threading.Thread

    def cerrar(self, espera: float = 35.0) -> None:
        """Pide salir y espera: las corridas en curso terminan y se anotan en el ledger."""
        self.servidor.should_exit = True
        self.hilo.join(espera)


def crear_app_escritorio(
    datos: Path, puerto: int, *, local: Any = None, remoto: Any = None, avisos: Any = None
) -> Any:
    """La interfaz de siempre, con la agenda corriendo en su ciclo de vida y los avisos compartidos."""
    from lymi.triggers.servidor import ConfigServidor, ciclo_agenda
    from lymi.ui.app import ConfigUI, crear_app_ui

    runs = datos / "runs"
    app = crear_app_ui(
        ConfigUI(
            ledger=runs / "lymi.sqlite3",
            workflows=datos / "workflows",
            memoria=runs / "aprobaciones.sqlite3",
            hosts=frozenset({f"127.0.0.1:{puerto}"}),
            agencias=datos / "agencias",
            agenda=runs / "agenda.sqlite3",
            ganchos=runs / "ganchos.sqlite3",
            sesiones=runs / "sesiones",
            agenda_activa=True,
            avisos=avisos,
            avisos_nativos=avisos is not None,
        )
    )
    app.router.lifespan_context = ciclo_agenda(
        ConfigServidor(
            ledger=runs / "lymi.sqlite3",
            agenda=runs / "agenda.sqlite3",
            ganchos=runs / "ganchos.sqlite3",
            local=local,
            remote=remoto,
            avisos=avisos,
        )
    )
    return app


def puerto_libre() -> tuple[socket.socket, int]:
    """Reserva un puerto loopback. El llamador construye la app con el y luego la sirve."""
    toma = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    toma.bind(("127.0.0.1", 0))
    return toma, toma.getsockname()[1]


def arrancar(app: Any, toma: socket.socket, puerto: int, *, espera: float = 15.0) -> Servidor:
    """Sirve `app` en la toma reservada, en un hilo aparte, y espera a que responda."""
    import uvicorn

    servidor = uvicorn.Server(uvicorn.Config(app, log_config=None, log_level="warning", lifespan="on"))
    hilo = threading.Thread(target=servidor.run, kwargs={"sockets": [toma]}, name="lymi-servidor", daemon=True)
    hilo.start()
    limite = time.monotonic() + espera
    while not servidor.started:
        if not hilo.is_alive() or time.monotonic() > limite:
            servidor.should_exit = True
            raise RuntimeError("la interfaz no arranco; mira runs/escritorio.log")
        time.sleep(0.05)
    return Servidor(f"http://127.0.0.1:{puerto}/", servidor, hilo)


# ---------------------------------------------------------------- ventana


class MotorError(RuntimeError):
    """El motor pedido no esta instalado. Nunca se cambia por otro en silencio."""


def elegir_motor(pedido: str | None = None) -> str:
    motor = (pedido or os.environ.get("LYMI_MOTOR") or "qt").strip().lower()
    if motor not in MOTORES:
        raise MotorError(f"motor desconocido {motor!r}; opciones: {', '.join(MOTORES)}")
    if motor == "qt":
        import importlib.util

        if importlib.util.find_spec("qtpy") is None or importlib.util.find_spec("PySide6") is None:
            raise MotorError(
                "Falta el motor Qt WebEngine. Instala: uv sync --extra escritorio\n"
                "(LYMI_MOTOR=edge usa el de Windows, que envia diagnostico a Microsoft.)"
            )
    return motor


ICONO = Path(__file__).resolve().parent / "ui" / "static" / "icono.png"


class Bandeja:
    """lymi en la bandeja del sistema: sigue vivo con la ventana cerrada y avisa.

    Cerrar la ventana la esconde: la agenda sigue corriendo y los avisos (una
    programacion que termino, algo que espera tu aprobacion, un evento en 15
    minutos) llegan como notificaciones del sistema. Salir de verdad es desde el
    menu de la bandeja. Todo se crea y se usa en el hilo de Qt.
    """

    def __init__(self, avisos: Any, abrir: Any, salir: Any) -> None:
        from qtpy.QtCore import QTimer
        from qtpy.QtGui import QAction, QIcon
        from qtpy.QtWidgets import QMenu, QSystemTrayIcon

        self.avisos = avisos
        self.abrir = abrir
        self.cursor = avisos.ultimo() if avisos is not None else 0
        self.ultimo_enlace = ""
        self.avisado_de_bandeja = False
        icono = QIcon(str(ICONO))
        self.icono = QSystemTrayIcon(icono)
        self.icono.setToolTip("lymi")
        menu = QMenu()
        self._acciones = []
        for texto, funcion in (("Abrir lymi", lambda: abrir("")), ("Detener todo", self._detener), (None, None),
                               ("Salir de lymi", salir)):
            if texto is None:
                menu.addSeparator()
                continue
            accion = QAction(texto, menu)
            accion.triggered.connect(funcion)
            menu.addAction(accion)
            self._acciones.append(accion)
        self._menu = menu
        self.icono.setContextMenu(menu)
        self.icono.activated.connect(self._activado)
        self.icono.messageClicked.connect(lambda: abrir(self.ultimo_enlace))
        self.icono.show()
        self._reloj = QTimer()
        self._reloj.timeout.connect(self._mirar)
        self._reloj.start(3000)

    @staticmethod
    def disponible() -> bool:
        from qtpy.QtWidgets import QSystemTrayIcon

        return QSystemTrayIcon.isSystemTrayAvailable()

    def _activado(self, razon: Any) -> None:
        from qtpy.QtWidgets import QSystemTrayIcon

        if razon in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.abrir("")

    def _detener(self) -> None:
        from lymi.control import detener

        detener("detenido desde la bandeja")
        self.notificar("lymi detenido", "Ninguna corrida hace otra llamada ni otro paso. Reanuda desde la app.", "")

    def notificar(self, titulo: str, texto: str, enlace: str) -> None:
        log.info("aviso en la bandeja: %s", titulo)
        self.ultimo_enlace = enlace
        self.icono.showMessage(titulo, texto or " ", self.icono.icon(), 8000)

    def _mirar(self) -> None:
        if self.avisos is None:
            return
        nuevos = self.avisos.despues_de(self.cursor)
        if not nuevos:
            return
        self.cursor = nuevos[-1].id
        ultimo = nuevos[-1]
        extra = f" (+{len(nuevos) - 1} avisos mas)" if len(nuevos) > 1 else ""
        self.notificar(ultimo.titulo, f"{ultimo.texto}{extra}", ultimo.enlace)

    def se_escondio(self) -> None:
        if not self.avisado_de_bandeja:
            self.avisado_de_bandeja = True
            self.notificar("lymi sigue aqui", "La agenda sigue corriendo y te aviso lo importante. "
                           "Para salir, clic derecho en el icono.", "")


def ventana(url: str, motor: str = "qt", *, cerrar_tras: float | None = None, avisos: Any = None) -> None:
    """Abre la ventana y bloquea hasta salir de lymi. Debe correr en el hilo principal.

    Con el motor Qt y bandeja disponible, cerrar la ventana la esconde (ver `Bandeja`).
    `cerrar_tras`: sale sola a los N segundos, para pruebas sin nadie delante.
    """
    if motor == "qt":
        os.environ["QT_API"] = "pyside6"
        # Se suman a las que ya hubiera (en Linux a veces hacen falta las del sistema).
        previas = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
        os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = f"{previas} {ARGUMENTOS_MOTOR}".strip()
    else:
        log.warning(AVISO_EDGE)
        os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = ARGUMENTOS_MOTOR
    import webview

    webview.settings["ALLOW_DOWNLOADS"] = False
    webview.settings["ALLOW_FILE_URLS"] = False
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
    webview.settings["SHOW_DEFAULT_MENUS"] = False
    vista = webview.create_window(
        TITULO, url, width=1360, height=860, min_size=(960, 620), background_color=FONDO, text_select=True
    )
    estado = {"saliendo": False, "bandeja": None}

    def salir() -> None:
        estado["saliendo"] = True
        if estado["bandeja"] is not None:
            estado["bandeja"].icono.hide()
        vista.destroy()

    def abrir(enlace: str) -> None:
        vista.show()
        vista.restore()
        if enlace.startswith("#/"):
            vista.evaluate_js(f"location.hash = {json.dumps(enlace)}")

    def al_cerrar() -> bool:
        if estado["saliendo"] or estado["bandeja"] is None:
            return True
        vista.hide()
        estado["bandeja"].se_escondio()
        return False  # cancela el cierre: lymi sigue en la bandeja

    vista.events.closing += al_cerrar

    if motor == "qt":
        from qtpy.QtGui import QIcon
        from qtpy.QtWidgets import QApplication

        # pywebview reutiliza esta QApplication: la bandeja nace en el hilo de Qt.
        app = QApplication.instance() or QApplication(sys.argv)
        app.setWindowIcon(QIcon(str(ICONO)))
        app.setApplicationName("lymi")
        if Bandeja.disponible():
            estado["bandeja"] = Bandeja(avisos, abrir, salir)
        else:
            log.info("sin bandeja del sistema: cerrar la ventana sale de lymi")

    if cerrar_tras:
        cierre = threading.Timer(cerrar_tras, salir)
        cierre.daemon = True
        cierre.start()
    webview.start(gui="qt" if motor == "qt" else "edgechromium", private_mode=True, debug=False)


class Vigia:
    """Muestrea las conexiones externas del arbol de procesos mientras la ventana vive."""

    def __init__(self, segundos: float, cada: float = 2.0) -> None:
        self.segundos, self.cada = segundos, cada
        self.vistas: dict[tuple[str, str, int], int] = {}
        self.muestras = 0
        self.error: str | None = None
        self._alto = threading.Event()
        self._hilo = threading.Thread(target=self._correr, name="lymi-vigia", daemon=True)
        self._inicio = 0.0

    def __enter__(self) -> Self:
        self._inicio = time.monotonic()
        self._hilo.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._alto.set()
        self._hilo.join(10)

    def _correr(self) -> None:
        from lymi import vigia_red

        limite = self._inicio + self.segundos
        while not self._alto.is_set() and time.monotonic() < limite:
            try:
                for clave in {(c.protocolo, c.remoto, c.puerto) for c in vigia_red.conexiones_externas()}:
                    self.vistas[clave] = self.vistas.get(clave, 0) + 1
            except (OSError, NotImplementedError, subprocess.SubprocessError) as exc:
                self.error = str(exc)
                return
            self.muestras += 1
            self._alto.wait(self.cada)

    def informe(self, motor: str) -> str:
        if self.error:
            return f"No se pudo vigilar la red: {self.error}"
        duracion = min(time.monotonic() - self._inicio, self.segundos)
        cabeza = f"Motor {motor}: {self.muestras} muestras en {duracion:.0f} s."
        if not self.vistas:
            return f"{cabeza}\n0 conexiones fuera de esta maquina."
        lineas = [f"  {p} {h}:{puerto}  (en {n} muestras)" for (p, h, puerto), n in sorted(self.vistas.items())]
        return "\n".join(
            [
                cabeza,
                f"{len(self.vistas)} destinos fuera de esta maquina:",
                *lineas,
                "Las corridas que lanzaste durante la prueba tambien aparecen aqui (y en el ledger).",
            ]
        )


def avisar(mensaje: str, *, error: bool = True) -> None:
    """Un aviso visible aunque no haya consola (el ejecutable de ventana no tiene)."""
    (log.error if error else log.info)(mensaje)
    if sys.stderr is not None:
        print(mensaje, file=sys.stderr)
    elif os.name == "nt":
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, mensaje, TITULO, 0x10 if error else 0x40)


def _registrar(runs: Path) -> None:
    manejador = RotatingFileHandler(runs / "escritorio.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    manejador.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    raiz = logging.getLogger()
    raiz.addHandler(manejador)
    raiz.setLevel(logging.INFO)


# ---------------------------------------------------------------- arranque


SALIDA_RED = 3
"""Codigo de salida si `verificar` encontro conexiones fuera de la maquina: el CI falla."""


def correr(motor: str | None = None, verificar: float | None = None, cerrar_tras: float | None = None) -> int:
    """Abre lymi de escritorio. `verificar`: segundos vigilando la red del arbol de procesos."""
    try:
        motor = elegir_motor(motor)
    except MotorError as exc:
        avisar(str(exc))
        return 1
    datos = hogar()
    try:
        copiadas = preparar_hogar(datos, recursos())
    except OSError as exc:
        avisar(f"No se pudo preparar la carpeta de datos {datos}:\n{exc}")
        return 1
    # Todo lymi resuelve rutas relativas a la carpeta actual: aqui es la de datos.
    os.chdir(datos)
    runs = datos / "runs"
    _registrar(runs)
    if copiadas:
        log.info("primer arranque: ejemplos copiados en %s: %s", datos, ", ".join(copiadas))

    marca = runs / "escritorio.url"
    with instancia_unica(runs / "escritorio.candado") as unica:
        if not unica:
            # Ya hay una lymi abierta: otra ventana sobre la misma, sin otra agenda.
            try:
                url = marca.read_text(encoding="utf-8").strip()
            except OSError:
                avisar("lymi ya esta abierto.", error=False)
                return 0
            ventana(url, motor)
            return 0

        from lymi.bench.wiring import proveedores

        local, etiqueta_local, remoto, etiqueta_remota = proveedores()
        log.info("local: %s | remoto: %s", etiqueta_local or "no disponible", etiqueta_remota or "no disponible")
        toma, puerto = puerto_libre()
        try:
            from lymi.avisos import Avisos

            avisos = Avisos()
            servidor = arrancar(
                crear_app_escritorio(datos, puerto, local=local, remoto=remoto, avisos=avisos), toma, puerto
            )
        except RuntimeError as exc:
            avisar(str(exc))
            return 1
        marca.write_text(servidor.url, encoding="utf-8")
        log.info("interfaz en %s con motor %s", servidor.url, motor)
        vigia = Vigia(verificar) if verificar else None
        try:
            with vigia or contextlib.nullcontext():
                ventana(servidor.url, motor, cerrar_tras=cerrar_tras, avisos=avisos)
        finally:
            with contextlib.suppress(OSError):
                marca.unlink()
            servidor.cerrar()
            log.info("cerrado")
        if vigia is not None:
            limpio = not (vigia.vistas or vigia.error)
            avisar(vigia.informe(motor), error=not limpio)
            return 0 if limpio else SALIDA_RED
    return 0


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(prog="lymi-escritorio", description="lymi en una ventana propia.")
    p.add_argument("--motor", choices=MOTORES, help="qt (por defecto) o edge (WebView2 de Microsoft).")
    p.add_argument(
        "--verificar-red", type=float, metavar="SEGUNDOS", help="vigila con quien habla la ventana; informa al cerrar."
    )
    p.add_argument("--cerrar-tras", type=float, metavar="SEGUNDOS", help="cierra la ventana sola (pruebas).")
    args = p.parse_args(argv)
    return correr(args.motor, args.verificar_red, args.cerrar_tras)


if __name__ == "__main__":
    sys.exit(main())
