"""Lectura del correo que Thunderbird ya tiene en tu disco. Solo lectura.

Por que asi y no con IMAP: Thunderbird ya resolvio la parte dificil (OAuth de
Gmail, varias cuentas, carpetas) y guarda el correo en archivos mbox. lymi no ve
tu contrasena ni tu token, no abre ninguna conexion y no le pide permisos a
nadie: abre archivos locales en modo lectura.

Tres decisiones que importan:

- **Sin segunda copia.** El indice guarda posiciones, fechas y banderas; jamas
  asuntos, remitentes ni cuerpos. Tu correo vive en un solo lugar: el archivo de
  Thunderbird. Cada consulta vuelve a leer de ahi.
- **Indice incremental.** Recorrer 190 MB con la libreria estandar tarda unos 15
  segundos; contar separadores de mensaje tarda uno, y al llegar correo nuevo
  solo se lee la cola del archivo.
- **Nunca se escribe.** Ni en los mbox ni en los `.msf` (el indice interno de
  Thunderbird, formato suyo que puede cambiar). Un borrador se deja como archivo
  `.eml` aparte, y lo envias tu.
"""

from __future__ import annotations

import configparser
import email
import email.policy
import hashlib
import os
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Self

TROZO = 1 << 20
TAM_CABECERA = 8192
MAX_BYTES_MENSAJE = 2 << 20
"""Cuanto se lee de un mensaje: lo demas son adjuntos que no se leen."""
MAX_CARACTERES_CUERPO = 20_000
SEPARADOR = re.compile(rb"(?:^|\n)(From [^\n]*\n)")
# Banderas de Thunderbird que usamos. Solo estas dos: el resto de los bits no
# estan documentados de forma estable y no vale la pena adivinarlos.
LEIDO = 0x0001
BORRADO = 0x0008
_ESQUEMA = """
CREATE TABLE IF NOT EXISTS carpetas (
    carpeta TEXT PRIMARY KEY, archivo TEXT NOT NULL, bytes INTEGER NOT NULL, mtime_ns INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS mensajes (
    carpeta TEXT NOT NULL, n INTEGER NOT NULL, inicio INTEGER NOT NULL, largo INTEGER NOT NULL,
    fecha TEXT, leido INTEGER NOT NULL DEFAULT 0, borrado INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (carpeta, n)
);
CREATE INDEX IF NOT EXISTS i_mensajes_fecha ON mensajes(carpeta, fecha);
"""


class CorreoError(RuntimeError):
    """No hay buzon que leer, o la carpeta pedida no existe."""


@dataclass(slots=True)
class Mensaje:
    carpeta: str
    n: int
    """Numero dentro de la carpeta, de mas viejo a mas nuevo. Es el id que se usa."""
    fecha: datetime | None
    de: str = ""
    para: str = ""
    asunto: str = ""
    cuerpo: str = ""
    adjuntos: list[str] = field(default_factory=list)
    leido: bool = False
    boletin: bool = False
    """Envio masivo, segun sus cabeceras y su remitente. Sin modelo de por medio."""
    para_mi: bool = True
    """Alguna de tus direcciones aparece en Para o CC. Si no, nadie te escribio a ti."""
    avisos: list[str] = field(default_factory=list)
    truncado: bool = False

    @property
    def id(self) -> str:
        return f"{self.carpeta}:{self.n}"

    def resumen(self) -> str:
        cuando = self.fecha.strftime("%Y-%m-%d %H:%M") if self.fecha else "sin fecha"
        marca = " " if self.leido else "*"
        return f"{marca} {self.id:<14} {cuando}  {self.de[:32]:<32} {self.asunto[:60]}"


def raiz_perfiles() -> Path:
    if (personal := os.environ.get("LYMI_CORREO")):
        return Path(personal)
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", "")) / "Thunderbird"
    casa = Path.home()
    mac = casa / "Library" / "Thunderbird"
    return mac if mac.is_dir() else casa / ".thunderbird"


def perfil_por_defecto(raiz: Path | None = None) -> Path:
    """El perfil que Thunderbird usa, segun su propio `profiles.ini`."""
    raiz = raiz or raiz_perfiles()
    if (raiz / "ImapMail").is_dir() or (raiz / "Mail").is_dir():
        return raiz  # ya apunta a un perfil (util para LYMI_CORREO y las pruebas)
    ini = raiz / "profiles.ini"
    candidatos: list[Path] = []
    if ini.is_file():
        config = configparser.ConfigParser()
        try:
            config.read(ini, encoding="utf-8")
        except (configparser.Error, OSError):
            config = configparser.ConfigParser()
        for seccion in config.sections():
            datos = config[seccion]
            if "path" not in datos:
                continue
            ruta = Path(datos["path"])
            if not ruta.is_absolute():
                ruta = raiz / ruta
            candidatos.insert(0, ruta) if datos.get("default", "0") == "1" else candidatos.append(ruta)
    if not candidatos and (perfiles := raiz / "Profiles").is_dir():
        candidatos = sorted(perfiles.iterdir(), key=lambda p: p.name.endswith("default-release"), reverse=True)
    for candidato in candidatos:
        if (candidato / "ImapMail").is_dir() or (candidato / "Mail").is_dir():
            return candidato
    raise CorreoError(
        f"no encontre un perfil de Thunderbird en {raiz}. Instala Thunderbird y sincroniza tu cuenta, "
        "o define LYMI_CORREO con la carpeta del perfil"
    )


def _texto(valor: object) -> str:
    """Decodifica una cabecera (=?UTF-8?B?...?=) sin reventar si viene rota."""
    if valor is None:
        return ""
    try:
        return str(make_header(decode_header(str(valor)))).strip()
    except (UnicodeDecodeError, LookupError, ValueError):
        return str(valor).strip()


class Buzon:
    """Las carpetas mbox de un perfil de Thunderbird."""

    def __init__(self, perfil: Path | None = None, db: Path | None = None) -> None:
        self.perfil = Path(perfil) if perfil is not None else perfil_por_defecto()
        if not self.perfil.is_dir():
            raise CorreoError(f"{self.perfil} no es una carpeta de perfil")
        clave = hashlib.sha1(os.path.normcase(str(self.perfil)).encode()).hexdigest()[:12]
        self.db = db or Path(os.environ.get("LYMI_CORREO_INDICE", "runs/correo")) / f"{clave}.sqlite3"
        self.db.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_ESQUEMA)
        self._mias: frozenset[str] | None = None

    def cerrar(self) -> None:
        self._conn.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_) -> None:
        self.cerrar()

    # ------------------------------------------------------------ descubrir

    def _archivos(self) -> dict[str, Path]:
        """Carpetas mbox del perfil: un archivo sin extension que empieza con `From `."""
        encontradas: dict[str, Path] = {}
        for base in ("ImapMail", "Mail"):
            raiz = self.perfil / base
            if not raiz.is_dir():
                continue
            for ruta in raiz.rglob("*"):
                if not ruta.is_file() or ruta.suffix in {".msf", ".dat", ".json", ".sqlite"}:
                    continue
                try:
                    if ruta.stat().st_size == 0 or ruta.open("rb").read(5) != b"From ":
                        continue
                except OSError:
                    continue
                partes = [p.removesuffix(".sbd") for p in ruta.relative_to(raiz).parts]
                encontradas["/".join(partes)] = ruta
        return encontradas

    def carpetas(self) -> list[dict[str, object]]:
        datos = []
        for nombre, ruta in sorted(self._archivos().items()):
            self._indexar(nombre, ruta)
            fila = self._conn.execute(
                "SELECT COUNT(*) total, SUM(1 - leido) sin_leer FROM mensajes WHERE carpeta = ? AND borrado = 0",
                (nombre,),
            ).fetchone()
            datos.append({
                "carpeta": nombre, "mensajes": fila["total"] or 0, "sin_leer": fila["sin_leer"] or 0,
                "bytes": ruta.stat().st_size,
            })
        return datos

    def resolver(self, carpeta: str) -> str:
        """`INBOX` vale por `imap.gmail.com/INBOX` mientras no haya dos iguales."""
        archivos = self._archivos()
        if carpeta in archivos:
            return carpeta
        buscado = carpeta.strip("/").lower()
        coincidencias = [n for n in archivos if n.lower().endswith("/" + buscado) or n.lower() == buscado]
        if len(coincidencias) == 1:
            return coincidencias[0]
        disponibles = ", ".join(sorted(archivos)[:8]) or "ninguna"
        problema = "es ambigua" if coincidencias else "no existe"
        raise CorreoError(f"la carpeta {carpeta!r} {problema}. Hay: {disponibles}")

    def _ruta(self, carpeta: str) -> tuple[str, Path]:
        nombre = self.resolver(carpeta)
        return nombre, self._archivos()[nombre]

    # ------------------------------------------------------------ indexar

    def _indexar(self, carpeta: str, ruta: Path) -> None:
        """Anota donde empieza cada mensaje. Si el archivo solo crecio, lee la cola."""
        estado = ruta.stat()
        previo = self._conn.execute("SELECT * FROM carpetas WHERE carpeta = ?", (carpeta,)).fetchone()
        if previo and previo["bytes"] == estado.st_size and previo["mtime_ns"] == estado.st_mtime_ns:
            return
        desde, ultimo = 0, 0
        if previo and estado.st_size > previo["bytes"]:
            fila = self._conn.execute(
                "SELECT n, inicio, largo FROM mensajes WHERE carpeta = ? ORDER BY n DESC LIMIT 1", (carpeta,)
            ).fetchone()
            if fila is not None:
                with ruta.open("rb") as f:
                    f.seek(fila["inicio"])
                    if f.read(5) == b"From ":
                        # El archivo es el mismo y crecio: se relee solo el ultimo
                        # mensaje (pudo completarse) y lo que vino despues.
                        desde, ultimo = fila["inicio"], fila["n"] - 1
        if desde == 0:
            self._conn.execute("DELETE FROM mensajes WHERE carpeta = ?", (carpeta,))

        # Las cabeceras se sacan del mismo bloque que ya esta en memoria: volver a
        # buscar cada mensaje en el disco costaba 15 s en un buzon de 5.000 correos.
        posiciones: list[int] = []
        cabeceras: list[bytes] = []
        with ruta.open("rb") as f:
            f.seek(desde)
            posicion = desde
            cola = b""
            if desde == 0 and ruta.open("rb").read(5) == b"From ":
                posiciones.append(0)
                cabeceras.append(b"")
            while True:
                datos = f.read(TROZO)
                if not datos:
                    break
                bloque = cola + datos
                base = posicion - len(cola)
                for m in SEPARADOR.finditer(bloque):
                    inicio = base + m.start(1)
                    if inicio < desde or (posiciones and inicio <= posiciones[-1]):
                        continue
                    if posiciones and not cabeceras[-1]:
                        cabeceras[-1] = bloque[max(0, posiciones[-1] - base) : m.start(1)][:TAM_CABECERA]
                    posiciones.append(inicio)
                    cabeceras.append(bloque[m.start(1) : m.start(1) + TAM_CABECERA])
                if posiciones and len(cabeceras[-1]) < TAM_CABECERA:
                    resto = bloque[max(0, posiciones[-1] - base) :][:TAM_CABECERA]
                    if len(resto) > len(cabeceras[-1]):
                        cabeceras[-1] = resto
                posicion += len(datos)
                cola = bloque[-6:]

        filas = []
        for i, inicio in enumerate(posiciones):
            fin = posiciones[i + 1] if i + 1 < len(posiciones) else estado.st_size
            fecha, leido, borrado = _cabeceras_rapidas(cabeceras[i])
            filas.append((carpeta, ultimo + i + 1, inicio, fin - inicio, fecha, leido, borrado))
        with self._conn:
            self._conn.executemany(
                "INSERT OR REPLACE INTO mensajes (carpeta, n, inicio, largo, fecha, leido, borrado)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                filas,
            )
            self._conn.execute(
                "INSERT OR REPLACE INTO carpetas VALUES (?, ?, ?, ?)",
                (carpeta, str(ruta), estado.st_size, estado.st_mtime_ns),
            )

    # ------------------------------------------------------------ leer

    def listar(
        self, carpeta: str = "INBOX", *, n: int = 20, dias: int | None = None, solo_sin_leer: bool = False
    ) -> list[Mensaje]:
        carpeta, ruta = self._ruta(carpeta)
        self._indexar(carpeta, ruta)
        condicion = "carpeta = ? AND borrado = 0"
        parametros: list[object] = [carpeta]
        if solo_sin_leer:
            condicion += " AND leido = 0"
        if dias is not None:
            condicion += " AND fecha >= ?"
            parametros.append((datetime.now(UTC) - timedelta(days=dias)).isoformat())
        filas = self._conn.execute(
            f"SELECT n FROM mensajes WHERE {condicion} ORDER BY COALESCE(fecha, '') DESC, n DESC LIMIT ?",
            (*parametros, max(1, min(n, 200))),
        ).fetchall()
        return [self.leer(carpeta, f["n"]) for f in filas]

    def leer(self, carpeta: str, n: int) -> Mensaje:
        carpeta, ruta = self._ruta(carpeta)
        self._indexar(carpeta, ruta)
        fila = self._conn.execute(
            "SELECT * FROM mensajes WHERE carpeta = ? AND n = ?", (carpeta, n)
        ).fetchone()
        if fila is None:
            raise CorreoError(f"no hay un mensaje {n} en {carpeta}")
        with ruta.open("rb") as f:
            f.seek(fila["inicio"])
            crudo = f.read(min(fila["largo"], MAX_BYTES_MENSAJE))
        truncado = fila["largo"] > MAX_BYTES_MENSAJE
        if crudo.startswith(b"From "):
            crudo = crudo.split(b"\n", 1)[1] if b"\n" in crudo else crudo
        mensaje = email.message_from_bytes(crudo, policy=email.policy.default)
        return _convertir(mensaje, carpeta, n, bool(fila["leido"]), truncado, self.direcciones())

    def direcciones(self) -> frozenset[str]:
        """Tus direcciones, segun las identidades que Thunderbird ya tiene configuradas."""
        if self._mias is None:
            texto = ""
            prefs = self.perfil / "prefs.js"
            if prefs.is_file():
                try:
                    texto = prefs.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    texto = ""
            self._mias = frozenset(
                d.lower() for d in re.findall(
                    r'user_pref\("mail\.identity\.id\d+\.useremail",\s*"([^"]+)"\)', texto
                )
            )
        return self._mias


def _cabeceras_rapidas(crudo: bytes) -> tuple[str | None, int, int]:
    """Fecha y banderas sin parsear el mensaje entero: se hace para cada mensaje."""
    fecha: str | None = None
    leido = borrado = 0
    for linea in crudo.split(b"\n", 60)[:60]:
        if not linea.strip():
            break
        if linea[:5].lower() == b"date:":
            try:
                momento = parsedate_to_datetime(linea[5:].decode("utf-8", "replace").strip())
            except (TypeError, ValueError):
                continue
            if momento.tzinfo is None:
                momento = momento.replace(tzinfo=UTC)
            fecha = momento.astimezone(UTC).isoformat()
        elif linea[:17].lower() == b"x-mozilla-status:":
            try:
                banderas = int(linea.split(b":", 1)[1].strip(), 16)
            except ValueError:
                continue
            leido = int(bool(banderas & LEIDO))
            borrado = int(bool(banderas & BORRADO))
    return fecha, leido, borrado


CABECERAS_MASIVAS = (
    "List-Unsubscribe", "List-Unsubscribe-Post", "List-Id", "Feedback-ID", "Auto-Submitted",
    "X-Campaign-Id", "X-Campaignid", "X-SES-Outgoing", "X-SG-EID", "X-Mailgun-Sid",
)
SUBDOMINIOS_MASIVOS = frozenset({
    "news", "newsletter", "email", "mail", "mailer", "mailing", "marketing", "updates", "notifications",
})
BUZONES_MASIVOS = frozenset({
    "noreply", "no-reply", "donotreply", "do-not-reply", "newsletter", "news", "notifications",
    "notification", "updates", "marketing", "mailer", "mailer-daemon", "campaign", "bounce",
})
_DIRECCION = re.compile(r"[\w.+-]+@[\w.-]+")


def _es_masivo(mensaje: EmailMessage) -> bool:
    """Envio masivo por sus propias cabeceras o por la forma del remitente.

    Medido con correo real: muchos boletines (`hello@news.railway.app`) no traen
    `List-Unsubscribe`, pero se anuncian en el subdominio desde el que salen.
    """
    if any(mensaje.get(c) for c in CABECERAS_MASIVAS):
        return True
    if (mensaje.get("Precedence", "") or "").lower() in {"bulk", "list", "junk"}:
        return True
    encontrada = _DIRECCION.search(str(mensaje.get("From", "")))
    if encontrada is None:
        return False
    buzon, _, dominio = encontrada.group(0).lower().partition("@")
    partes = dominio.split(".")
    return buzon in BUZONES_MASIVOS or (len(partes) > 2 and partes[0] in SUBDOMINIOS_MASIVOS)


def _convertir(
    mensaje: EmailMessage, carpeta: str, n: int, leido: bool, truncado: bool, mias: frozenset[str] = frozenset()
) -> Mensaje:
    from lymi.privacidad import sanear
    from lymi.web import senales_inyeccion
    from lymi.web.markdown import html_a_markdown

    fecha = None
    if (crudo := mensaje.get("Date")) is not None:
        try:
            fecha = parsedate_to_datetime(str(crudo))
            fecha = fecha.replace(tzinfo=UTC) if fecha.tzinfo is None else fecha.astimezone(UTC)
        except (TypeError, ValueError):
            fecha = None

    cuerpo, adjuntos = "", []
    for parte in mensaje.walk():
        disposicion = (parte.get_content_disposition() or "").lower()
        if disposicion == "attachment":
            adjuntos.append(_texto(parte.get_filename()) or parte.get_content_type())
            continue
        tipo = parte.get_content_type()
        if tipo not in {"text/plain", "text/html"} or cuerpo and tipo == "text/html":
            continue
        try:
            texto = parte.get_content()
        except (LookupError, UnicodeDecodeError, ValueError):
            continue
        if tipo == "text/html":
            texto = html_a_markdown(texto, "").markdown
        if not cuerpo or (tipo == "text/plain" and len(texto) > len(cuerpo)):
            cuerpo = texto

    # El correo es texto ajeno, y ademas dirigido: se sanea y se avisa si trae
    # instrucciones para un modelo.
    cuerpo = sanear(cuerpo).texto.strip()
    if len(cuerpo) > MAX_CARACTERES_CUERPO:
        cuerpo, truncado = cuerpo[:MAX_CARACTERES_CUERPO], True
    avisos = []
    if senales := senales_inyeccion(cuerpo):
        avisos.append(f"el mensaje intenta dar instrucciones a un modelo: {senales[0]!r}")
    if truncado:
        avisos.append("contenido truncado")
    boletin = _es_masivo(mensaje)
    destinatarios = {
        d.lower()
        for campo in ("To", "Cc")
        for d in _DIRECCION.findall(str(mensaje.get(campo, "")))
    }
    return Mensaje(
        carpeta=carpeta, n=n, fecha=fecha, boletin=boletin,
        para_mi=not mias or bool(destinatarios & mias),
        de=sanear(_texto(mensaje.get("From"))).texto, para=sanear(_texto(mensaje.get("To"))).texto,
        asunto=sanear(_texto(mensaje.get("Subject"))).texto, cuerpo=cuerpo, adjuntos=adjuntos[:20],
        leido=leido, avisos=avisos, truncado=truncado,
    )
