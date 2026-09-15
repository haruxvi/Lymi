"""Capacidades del ejecutor: que rutas se leen, cuales se escriben y que comandos corren.

Tres capas, de afuera hacia adentro:

1. **Zonas vetadas fijas.** El sistema operativo, los programas instalados y las
   carpetas de credenciales (`.ssh`, `.aws`, `.kube`...) no se tocan aunque el
   perfil diga otra cosa. Lo mismo `runs/` (ledger, diario, parada) y `.git`: un
   agente no puede reescribir su propia auditoria.
2. **Forma de la ruta.** Se rechazan rutas de red (UNC), flujos alternativos de
   NTFS (`archivo:oculto`) y nombres de dispositivo de Windows (`CON`, `NUL`...),
   que abren caminos que una comprobacion de prefijos no ve.
3. **Perfil.** Lista blanca de carpetas legibles y escribibles, y de comandos. Por
   defecto solo se escribe en `./salidas` y no corre ningun comando.

Las rutas se resuelven antes de comprobarlas: un enlace simbolico que apunta
afuera se juzga por su destino, no por su nombre.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_DISPOSITIVOS = frozenset(
    {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
)
_UNIDAD = re.compile(r"^[A-Za-z]:")

SHELLS = frozenset({
    "cmd", "powershell", "pwsh", "bash", "sh", "zsh", "fish", "dash", "wsl", "wscript", "cscript",
    "mshta", "rundll32", "regsvr32", "reg", "regedit", "schtasks", "sc", "net", "netsh", "sudo", "su",
    "runas", "env", "xargs", "find",
})
"""Programas que anulan el ejecutor: cualquier comando podria pasar a traves de ellos."""


class CapacidadDenegada(PermissionError):
    """La operacion pide algo que el perfil o las zonas vetadas no permiten."""


class PerfilError(ValueError):
    """`ejecutor.yml` invalido o peligroso."""


def denegadas_fijas() -> list[Path]:
    casa = Path.home()
    zonas = [casa / n for n in (".ssh", ".gnupg", ".aws", ".azure", ".kube", ".docker", ".netrc", ".pypirc")]
    zonas.append(casa / ".config" / "gcloud")
    if sys.platform == "win32":
        for variable in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData"):
            valor = os.environ.get(variable)
            if valor:
                zonas.append(Path(valor))
        appdata = os.environ.get("APPDATA")
        if appdata:
            zonas.append(Path(appdata) / "Microsoft")
    else:
        zonas.extend(Path(p) for p in ("/etc", "/bin", "/sbin", "/usr", "/boot", "/lib", "/lib64", "/var",
                                        "/System", "/Library", "/private/etc"))
    return [z.resolve() for z in zonas]


def dentro(ruta: Path, raiz: Path) -> bool:
    """Si `ruta` es `raiz` o esta debajo, sin distinguir mayusculas donde el sistema no lo hace."""
    r, b = os.path.normcase(str(ruta)), os.path.normcase(str(raiz))
    return r == b or r.startswith(b.rstrip("\\/") + os.sep)


def validar_forma(texto: str) -> None:
    if not texto or "\x00" in texto:
        raise CapacidadDenegada("ruta vacia o con byte nulo")
    if texto.startswith(("\\\\", "//")):
        raise CapacidadDenegada("las rutas de red (UNC) no estan permitidas")
    sin_unidad = texto[2:] if _UNIDAD.match(texto) else texto
    if ":" in sin_unidad:
        raise CapacidadDenegada("los flujos alternativos de archivo (ruta:flujo) no estan permitidos")
    for parte in Path(texto).parts:
        base = parte.rstrip(" .").split(".")[0].lower()
        if base in _DISPOSITIVOS:
            raise CapacidadDenegada(f"{parte!r} es un nombre de dispositivo de Windows")


def expandir(texto: str, base: Path) -> Path:
    ruta = Path(os.path.expandvars(os.path.expanduser(texto)))
    return (ruta if ruta.is_absolute() else base / ruta).resolve()


@dataclass(frozen=True, slots=True)
class Comando:
    nombre: str
    ejecutable: str
    subcomandos: frozenset[str] | None = None
    """Primer argumento permitido (ej. git: status, diff). `None` = cualquiera."""


@dataclass(slots=True)
class Perfil:
    escribibles: list[Path] = field(default_factory=list)
    legibles: list[Path] = field(default_factory=list)
    comandos: dict[str, Comando] = field(default_factory=dict)
    protegidas: list[Path] = field(default_factory=list)
    max_archivos: int = 50
    """Archivos distintos que una corrida puede modificar, mover o borrar."""
    max_bytes: int = 5_000_000

    @classmethod
    def por_defecto(cls, base: Path) -> Perfil:
        base = base.resolve()
        return cls(
            escribibles=[base / "salidas"],
            legibles=[base],
            protegidas=[base / "runs", base / ".git"],
        )

    def zona_vetada(self, ruta: Path) -> Path | None:
        for zona in (*denegadas_fijas(), *self.protegidas):
            if dentro(ruta, zona):
                return zona
        return None

    def resolver_lectura(self, texto: str, base: Path) -> Path:
        validar_forma(texto)
        ruta = expandir(texto, base)
        if (zona := self.zona_vetada(ruta)) is not None:
            raise CapacidadDenegada(f"{ruta} esta en una zona protegida ({zona})")
        if not any(dentro(ruta, r) for r in (*self.legibles, *self.escribibles)):
            raise CapacidadDenegada(f"{ruta} esta fuera de las carpetas legibles del perfil")
        return ruta

    def resolver_escritura(self, texto: str, base: Path) -> Path:
        validar_forma(texto)
        ruta = expandir(texto, base)
        if (zona := self.zona_vetada(ruta)) is not None:
            raise CapacidadDenegada(f"{ruta} esta en una zona protegida ({zona})")
        if not any(dentro(ruta, r) for r in self.escribibles):
            raise CapacidadDenegada(f"{ruta} esta fuera de las carpetas escribibles del perfil")
        return ruta


def cargar_perfil(ruta: Path | None, base: Path) -> Perfil:
    """Lee `ejecutor.yml`. Sin archivo: solo se escribe en ./salidas y no corre ningun comando."""
    base = base.resolve()
    if ruta is None or not ruta.exists():
        return Perfil.por_defecto(base)
    try:
        datos = yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise PerfilError(f"no se pudo leer {ruta}: {exc}") from None
    if not isinstance(datos, dict):
        raise PerfilError(f"{ruta}: se esperaba un mapa en la raiz")
    permitidas = {"escribibles", "legibles", "comandos", "max_archivos", "max_bytes"}
    if extra := set(datos) - permitidas:
        raise PerfilError(f"{ruta}: claves desconocidas: {', '.join(sorted(extra))}")

    def rutas(clave: str) -> list[Path]:
        valores = datos.get(clave, [])
        if not isinstance(valores, list) or not all(isinstance(v, str) for v in valores):
            raise PerfilError(f"{ruta}: `{clave}` debe ser una lista de rutas")
        return [expandir(v, base) for v in valores]

    perfil = Perfil.por_defecto(base)
    escribibles = rutas("escribibles")
    for carpeta in escribibles:
        if carpeta.parent == carpeta or carpeta == Path.home().resolve():
            raise PerfilError(f"{carpeta} es demasiado amplia para escribir: elige una carpeta de trabajo")
        if (zona := perfil.zona_vetada(carpeta)) is not None:
            raise PerfilError(f"{carpeta} esta dentro de una zona protegida ({zona})")
    if escribibles:
        perfil.escribibles = escribibles
    perfil.legibles = [*perfil.legibles, *rutas("legibles")]

    comandos = datos.get("comandos", {}) or {}
    if not isinstance(comandos, dict):
        raise PerfilError(f"{ruta}: `comandos` debe ser un mapa nombre -> opciones")
    for nombre, opciones in comandos.items():
        opciones = opciones or {}
        if not isinstance(opciones, dict) or set(opciones) - {"ejecutable", "subcomandos"}:
            raise PerfilError(f"{ruta}: comando {nombre!r}: opciones validas: ejecutable, subcomandos")
        ejecutable = str(opciones.get("ejecutable") or nombre)
        if Path(ejecutable).stem.lower() in SHELLS or str(nombre).lower() in SHELLS:
            raise PerfilError(
                f"{ruta}: {nombre!r} es un interprete de comandos; permitirlo anula el ejecutor"
            )
        sub = opciones.get("subcomandos")
        if sub is not None and (not isinstance(sub, list) or not all(isinstance(s, str) for s in sub)):
            raise PerfilError(f"{ruta}: comando {nombre!r}: `subcomandos` debe ser una lista")
        perfil.comandos[str(nombre)] = Comando(str(nombre), ejecutable, None if sub is None else frozenset(sub))

    for clave in ("max_archivos", "max_bytes"):
        if clave in datos:
            valor = datos[clave]
            if not isinstance(valor, int) or valor <= 0:
                raise PerfilError(f"{ruta}: `{clave}` debe ser un entero positivo")
            setattr(perfil, clave, valor)
    return perfil
