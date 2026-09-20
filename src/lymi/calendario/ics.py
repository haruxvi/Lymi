"""Calendario: archivos `.ics` locales, leidos con la libreria estandar.

Mismo criterio que el correo: lymi no se conecta a Google ni guarda una segunda
copia de tu agenda. Lee los `.ics` que ya tienes en disco (exportados, o los que
tu cliente sincroniza) y expande las repeticiones al vuelo.

Se implementa el subconjunto de RFC 5545 que aparece en un calendario real:
`VEVENT` con fecha o fecha-hora, zona horaria por `TZID`, repeticiones
`DAILY/WEEKLY/MONTHLY/YEARLY` con `INTERVAL`, `COUNT`, `UNTIL` y `BYDAY`, y las
excepciones de `EXDATE`. Lo que no se entiende se omite y se dice, en vez de
inventar un evento que no existe.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MAX_BYTES = 10_000_000
MAX_REPETICIONES = 500
"""Tope al expandir una repeticion: una regla infinita no puede colgar a lymi."""
DIAS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
_PLEGADO = re.compile(r"\r?\n[ \t]")
_ESCAPES = {"\\n": "\n", "\\N": "\n", "\\,": ",", "\\;": ";", "\\\\": "\\"}


class CalendarioError(ValueError):
    """No hay calendarios que leer."""


@dataclass(frozen=True, slots=True)
class Evento:
    titulo: str
    inicio: datetime
    fin: datetime
    todo_el_dia: bool = False
    lugar: str = ""
    calendario: str = ""
    uid: str = ""

    def cuando(self) -> str:
        if self.todo_el_dia:
            return f"{self.inicio:%d/%m} todo el dia"
        return f"{self.inicio:%d/%m %H:%M}-{self.fin:%H:%M}"

    def resumen(self) -> str:
        lugar = f"  ({self.lugar})" if self.lugar else ""
        return f"{self.cuando()}  {self.titulo}{lugar}"


@dataclass(slots=True)
class _Base:
    """Un VEVENT tal como viene, antes de expandir sus repeticiones."""

    titulo: str
    inicio: datetime
    fin: datetime
    todo_el_dia: bool
    lugar: str
    uid: str
    calendario: str
    rrule: dict[str, str] = field(default_factory=dict)
    excepciones: set[datetime] = field(default_factory=set)


def raiz_calendarios() -> Path:
    return Path(os.environ.get("LYMI_CALENDARIO", "calendario"))


def _desescapar(valor: str) -> str:
    for viejo, nuevo in _ESCAPES.items():
        valor = valor.replace(viejo, nuevo)
    return valor.strip()


def _parametros(crudo: str) -> dict[str, str]:
    partes = crudo.split(";")[1:]
    datos = {}
    for parte in partes:
        clave, _, valor = parte.partition("=")
        datos[clave.strip().upper()] = valor.strip().strip('"')
    return datos


def _fecha(valor: str, parametros: dict[str, str]) -> tuple[datetime, bool]:
    """Devuelve (momento, es_todo_el_dia). Las fechas sin hora son todo el dia."""
    valor = valor.strip()
    if parametros.get("VALUE") == "DATE" or (len(valor) == 8 and "T" not in valor):
        dia = datetime.strptime(valor, "%Y%m%d").replace(tzinfo=UTC)
        return dia, True
    if valor.endswith("Z"):
        return datetime.strptime(valor, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC), False
    # RFC 5545 permite la "hora flotante": sin Z y sin TZID, vale la hora local de
    # quien lo lee. Se construye sin zona a proposito y se le pone una abajo.
    momento = datetime.strptime(valor, "%Y%m%dT%H%M%S")  # noqa: DTZ007
    zona = parametros.get("TZID")
    if zona:
        try:
            return momento.replace(tzinfo=ZoneInfo(zona)), False
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return momento.astimezone(), False


def leer(texto: str, calendario: str = "") -> tuple[list[_Base], list[str]]:
    """VEVENTs de un archivo ics. Devuelve (eventos, avisos)."""
    texto = _PLEGADO.sub("", texto)  # RFC 5545: una linea larga se parte y continua con espacio
    eventos: list[_Base] = []
    avisos: list[str] = []
    for bloque in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", texto, re.DOTALL | re.IGNORECASE):
        campos: dict[str, tuple[str, dict[str, str]]] = {}
        excepciones: set[datetime] = set()
        for linea in bloque.splitlines():
            nombre, _, valor = linea.partition(":")
            if not valor:
                continue
            clave = nombre.split(";")[0].strip().upper()
            parametros = _parametros(nombre)
            if clave == "EXDATE":
                for uno in valor.split(","):
                    try:
                        excepciones.add(_fecha(uno, parametros)[0])
                    except ValueError:
                        continue
            else:
                campos[clave] = (valor.strip(), parametros)
        if "DTSTART" not in campos:
            continue
        if campos.get("STATUS", ("", {}))[0].upper() == "CANCELLED":
            continue
        try:
            inicio, todo_el_dia = _fecha(*campos["DTSTART"])
        except ValueError:
            avisos.append(f"{calendario}: un evento tiene una fecha que no entiendo; se omite")
            continue
        if "DTEND" in campos:
            try:
                fin = _fecha(*campos["DTEND"])[0]
            except ValueError:
                fin = inicio + timedelta(days=1 if todo_el_dia else 0, hours=0 if todo_el_dia else 1)
        elif "DURATION" in campos:
            fin = inicio + _duracion(campos["DURATION"][0])
        else:
            fin = inicio + timedelta(days=1) if todo_el_dia else inicio + timedelta(hours=1)
        rrule = {}
        if "RRULE" in campos:
            for parte in campos["RRULE"][0].split(";"):
                clave, _, valor = parte.partition("=")
                rrule[clave.strip().upper()] = valor.strip().upper()
        eventos.append(_Base(
            titulo=_desescapar(campos.get("SUMMARY", ("(sin titulo)", {}))[0]),
            inicio=inicio, fin=fin, todo_el_dia=todo_el_dia,
            lugar=_desescapar(campos.get("LOCATION", ("", {}))[0]),
            uid=campos.get("UID", ("", {}))[0], calendario=calendario,
            rrule=rrule, excepciones=excepciones,
        ))
    return eventos, avisos


def _duracion(valor: str) -> timedelta:
    m = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", valor.strip().upper())
    if not m:
        return timedelta(hours=1)
    dias, horas, minutos, segundos = (int(x) if x else 0 for x in m.groups())
    return timedelta(days=dias, hours=horas, minutes=minutos, seconds=segundos)


def _paso(inicio: datetime, freq: str, intervalo: int, k: int) -> tuple[datetime | None, datetime]:
    """La k-esima repeticion y un momento de referencia para saber cuando parar.

    El mes que no tiene ese dia simplemente no tiene ocurrencia (RFC 5545): un
    evento del 31 salta febrero, no se corre al 28. Por eso puede devolver None y
    aparte una referencia, que sirve para cortar el bucle.
    """
    if freq == "DAILY":
        momento = inicio + timedelta(days=intervalo * k)
        return momento, momento
    if freq == "WEEKLY":
        momento = inicio + timedelta(weeks=intervalo * k)
        return momento, momento
    if freq == "MONTHLY":
        total = inicio.month - 1 + intervalo * k
        ano, mes = inicio.year + total // 12, total % 12 + 1
    else:
        ano, mes = inicio.year + intervalo * k, inicio.month
    referencia = inicio.replace(year=ano, month=mes, day=1)
    try:
        return inicio.replace(year=ano, month=mes), referencia
    except ValueError:
        return None, referencia  # ese mes no tiene ese dia: no hay ocurrencia


def expandir(base: _Base, desde: datetime, hasta: datetime) -> list[Evento]:
    """Las apariciones del evento dentro de la ventana, repeticiones incluidas."""
    largo = base.fin - base.inicio

    def armar(inicio: datetime) -> Evento:
        return Evento(
            titulo=base.titulo, inicio=inicio, fin=inicio + largo, todo_el_dia=base.todo_el_dia,
            lugar=base.lugar, calendario=base.calendario, uid=base.uid,
        )

    if not base.rrule:
        return [armar(base.inicio)] if base.inicio < hasta and base.fin > desde else []

    freq = base.rrule.get("FREQ", "")
    if freq not in {"DAILY", "WEEKLY", "MONTHLY", "YEARLY"}:
        return []
    intervalo = max(1, int(base.rrule.get("INTERVAL", "1") or 1))
    cuenta = int(base.rrule["COUNT"]) if base.rrule.get("COUNT", "").isdigit() else None
    limite = None
    if "UNTIL" in base.rrule:
        try:
            limite = _fecha(base.rrule["UNTIL"], {})[0]
        except ValueError:
            limite = None
    dias_semana = [DIAS[d] for d in base.rrule.get("BYDAY", "").split(",") if d in DIAS]

    apariciones: list[Evento] = []
    vistas = 0
    for k in range(MAX_REPETICIONES):
        momento, referencia = _paso(base.inicio, freq, intervalo, k)
        if referencia >= hasta or (limite is not None and referencia > limite + timedelta(days=31)):
            break
        if momento is None:
            continue
        candidatos = [momento]
        if freq == "WEEKLY" and dias_semana:
            lunes = momento - timedelta(days=momento.weekday())
            candidatos = [lunes + timedelta(days=d) for d in dias_semana]
        for candidato in candidatos:
            if candidato < base.inicio or (limite is not None and candidato > limite):
                continue
            # La ocurrencia cuenta para COUNT aunque despues la quite un EXDATE:
            # asi lo define el RFC, y asi no se estira la serie una semana de mas.
            vistas += 1
            if cuenta is not None and vistas > cuenta:
                return apariciones
            if candidato in base.excepciones:
                continue
            if candidato < hasta and candidato + largo > desde:
                apariciones.append(armar(candidato))
    return apariciones


class Calendario:
    """Los archivos `.ics` de una carpeta."""

    def __init__(self, raiz: Path | None = None) -> None:
        self.raiz = Path(raiz or raiz_calendarios())

    def archivos(self) -> list[Path]:
        if not self.raiz.is_dir():
            return []
        return sorted(p for p in self.raiz.rglob("*.ics") if p.is_file())

    def eventos(self, desde: datetime, hasta: datetime) -> tuple[list[Evento], list[str]]:
        archivos = self.archivos()
        if not archivos:
            raise CalendarioError(
                f"no hay archivos .ics en {self.raiz}. Exporta tu calendario ahi, "
                "o define LYMI_CALENDARIO con la carpeta que los tiene"
            )
        encontrados: list[Evento] = []
        avisos: list[str] = []
        for archivo in archivos:
            try:
                if archivo.stat().st_size > MAX_BYTES:
                    avisos.append(f"{archivo.name}: demasiado grande, se omite")
                    continue
                texto = archivo.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                avisos.append(f"{archivo.name}: {exc}")
                continue
            bases, mas_avisos = leer(texto, archivo.stem)
            avisos.extend(mas_avisos)
            for base in bases:
                encontrados.extend(expandir(base, desde, hasta))
        encontrados.sort(key=lambda e: (e.inicio, e.titulo))
        return encontrados, avisos

    def dia(self, cuando: date | None = None) -> tuple[list[Evento], list[str]]:
        cuando = cuando or datetime.now().astimezone().date()
        inicio = datetime.combine(cuando, time.min).astimezone()
        return self.eventos(inicio, inicio + timedelta(days=1))
