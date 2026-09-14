"""Expresiones cron de cinco campos: minuto, hora, dia del mes, mes, dia de la semana.

Sin dependencia externa a proposito: calcular la siguiente ejecucion es codigo
pequeno, se prueba a fondo y no ata el programador de tareas a una libreria cuyo
mantenimiento no controlamos.

Semantica de cron clasico (Vixie):

- Si el dia del mes Y el dia de la semana estan restringidos (ninguno empieza por
  `*`), basta con que coincida CUALQUIERA de los dos.
- `7` y `0` son domingo.
- `5/15` significa "desde 5, cada 15".

Zonas horarias: el calculo recorre la hora de pared de la zona indicada. En un
cambio de horario hacia atras, una hora de pared repetida se ejecuta una sola vez.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ALIAS = {
    "@hourly": "0 * * * *",
    "@daily": "0 0 * * *",
    "@midnight": "0 0 * * *",
    "@weekly": "0 0 * * 0",
    "@monthly": "0 0 1 * *",
    "@yearly": "0 0 1 1 *",
    "@annually": "0 0 1 1 *",
}

_MESES = {n: i for i, n in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), start=1
)}
_DIAS = {n: i for i, n in enumerate(("sun", "mon", "tue", "wed", "thu", "fri", "sat"))}

_CAMPOS: tuple[tuple[str, int, int, dict[str, int]], ...] = (
    ("minuto", 0, 59, {}),
    ("hora", 0, 23, {}),
    ("dia del mes", 1, 31, {}),
    ("mes", 1, 12, _MESES),
    ("dia de la semana", 0, 7, _DIAS),
)

HORIZONTE = timedelta(days=366 * 5)
"""Hasta donde se busca la siguiente ejecucion. Cinco anos cubren el 29 de febrero."""


class CronError(ValueError):
    """Expresion invalida, o que no ocurre dentro del horizonte."""


def _valor(texto: str, nombre: str, minimo: int, maximo: int, nombres: dict[str, int]) -> int:
    t = texto.lower()
    if t in nombres:
        return nombres[t]
    if not t.isdigit():
        raise CronError(f"{nombre}: {texto!r} no es un numero valido")
    valor = int(t)
    if not minimo <= valor <= maximo:
        raise CronError(f"{nombre}: {valor} fuera de rango ({minimo}-{maximo})")
    return valor


def _campo(texto: str, nombre: str, minimo: int, maximo: int, nombres: dict[str, int]) -> frozenset[int]:
    valores: set[int] = set()
    for parte in texto.split(","):
        if not parte:
            raise CronError(f"{nombre}: la lista tiene un elemento vacio")
        rango, barra, texto_paso = parte.partition("/")
        paso = 1
        if barra:
            if not texto_paso.isdigit() or int(texto_paso) == 0:
                raise CronError(f"{nombre}: paso invalido {texto_paso!r}")
            paso = int(texto_paso)

        if rango == "*":
            inicio, fin = minimo, maximo
        elif "-" in rango:
            a, _, b = rango.partition("-")
            inicio = _valor(a, nombre, minimo, maximo, nombres)
            fin = _valor(b, nombre, minimo, maximo, nombres)
            if inicio > fin:
                raise CronError(f"{nombre}: rango invertido {rango!r}")
        else:
            inicio = _valor(rango, nombre, minimo, maximo, nombres)
            fin = maximo if barra else inicio

        valores.update(range(inicio, fin + 1, paso))
    return frozenset(valores)


@dataclass(frozen=True, slots=True)
class Cron:
    expresion: str
    minutos: frozenset[int]
    horas: frozenset[int]
    dias_mes: frozenset[int]
    meses: frozenset[int]
    dias_semana: frozenset[int]
    """0 = domingo."""
    dom_restringido: bool
    dow_restringido: bool

    def _dia_valido(self, momento: datetime) -> bool:
        coincide_dom = momento.day in self.dias_mes
        # Python: lunes = 0. Cron: domingo = 0.
        coincide_dow = (momento.weekday() + 1) % 7 in self.dias_semana
        if self.dom_restringido and self.dow_restringido:
            return coincide_dom or coincide_dow
        if self.dom_restringido:
            return coincide_dom
        if self.dow_restringido:
            return coincide_dow
        return True

    def siguiente(self, desde: datetime, zona: tzinfo = UTC) -> datetime:
        """Primera ejecucion estrictamente posterior a `desde`, en UTC."""
        if desde.tzinfo is None:
            raise CronError("`desde` debe llevar zona horaria")

        momento = desde.astimezone(zona).replace(tzinfo=None, second=0, microsecond=0) + timedelta(minutes=1)
        limite = momento + HORIZONTE
        while momento <= limite:
            if momento.month not in self.meses:
                anio, mes = (momento.year + 1, 1) if momento.month == 12 else (momento.year, momento.month + 1)
                momento = momento.replace(year=anio, month=mes, day=1, hour=0, minute=0)
                continue
            if not self._dia_valido(momento):
                momento = (momento + timedelta(days=1)).replace(hour=0, minute=0)
                continue
            if momento.hour not in self.horas:
                momento = (momento + timedelta(hours=1)).replace(minute=0)
                continue
            if momento.minute not in self.minutos:
                momento += timedelta(minutes=1)
                continue
            return momento.replace(tzinfo=zona).astimezone(UTC)
        raise CronError(f"{self.expresion!r} no ocurre en los proximos cinco anos")


def parsear(expresion: str) -> Cron:
    """Convierte una expresion cron (o un alias como `@daily`) en un `Cron`."""
    original = expresion.strip()
    texto = ALIAS.get(original.lower(), original)
    partes = texto.split()
    if len(partes) != 5:
        raise CronError(
            f"se esperaban 5 campos (minuto hora dia-del-mes mes dia-de-la-semana), llegaron {len(partes)}"
        )
    minutos, horas, dias_mes, meses, dias_semana = (
        _campo(parte, *especificacion) for parte, especificacion in zip(partes, _CAMPOS, strict=True)
    )
    return Cron(
        expresion=original,
        minutos=minutos,
        horas=horas,
        dias_mes=dias_mes,
        meses=meses,
        dias_semana=frozenset(0 if d == 7 else d for d in dias_semana),
        dom_restringido=not partes[2].startswith("*"),
        dow_restringido=not partes[4].startswith("*"),
    )


def zona_horaria(nombre: str | None) -> tzinfo:
    """Zona IANA por nombre. Sin nombre, UTC."""
    if not nombre or nombre.upper() == "UTC":
        return UTC
    try:
        return ZoneInfo(nombre)
    except (ZoneInfoNotFoundError, ValueError):
        raise CronError(f"zona horaria desconocida {nombre!r} (en Windows requiere el paquete tzdata)") from None
