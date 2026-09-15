"""Las operaciones cerradas del ejecutor.

Seis operaciones y ninguna mas: leer, listar, escribir, mover, borrar y ejecutar
un comando de la lista blanca. Nada de shell:

- Los comandos corren con `shell=False`, sin stdin y con un entorno minimo: las
  claves de API del entorno de lymi no le llegan al programa.
- Se rechazan `.bat` y `.cmd`: Windows los pasa por cmd.exe y reinterpreta los
  argumentos, que es justo el hueco que la lista blanca existe para cerrar.
- Hay tope de archivos distintos tocados por corrida y de bytes por escritura.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lymi.ejecutor.capacidades import CapacidadDenegada, Perfil
from lymi.ejecutor.diario import Diario
from lymi.privacidad.etiquetas import Etiquetas, Nivel

LIMITE_LECTURA = 200_000
LIMITE_SALIDA = 20_000
LIMITE_LISTADO = 1000
ENTORNO_MINIMO = ("PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "TEMP", "TMP", "HOME", "USERPROFILE", "LANG")


class EjecutorError(RuntimeError):
    """La operacion estaba permitida pero no se pudo completar."""


@dataclass(frozen=True, slots=True)
class Lectura:
    ruta: str
    texto: str
    nivel: Nivel
    truncado: bool = False


class Ejecutor:
    def __init__(self, perfil: Perfil, diario: Diario, *, base: Path | None = None,
                 etiquetas: Etiquetas | None = None) -> None:
        self.perfil = perfil
        self.diario = diario
        self.base = (base or Path.cwd()).resolve()
        self.etiquetas = etiquetas or Etiquetas()
        self._tocados: set[str] = set()

    def _tocar(self, ruta: Path) -> None:
        clave = os.path.normcase(str(ruta))
        if clave not in self._tocados and len(self._tocados) >= self.perfil.max_archivos:
            raise CapacidadDenegada(f"se alcanzo el tope de {self.perfil.max_archivos} archivos tocados")
        self._tocados.add(clave)

    # ------------------------------------------------------------ lectura

    def leer(self, ruta: str) -> Lectura:
        archivo = self.perfil.resolver_lectura(ruta, self.base)
        if not archivo.is_file():
            raise EjecutorError(f"{archivo} no es un archivo")
        with archivo.open("rb") as f:
            datos = f.read(LIMITE_LECTURA + 1)
        return Lectura(
            ruta=str(archivo),
            texto=datos[:LIMITE_LECTURA].decode("utf-8", errors="replace"),
            nivel=self.etiquetas.nivel_de(archivo),
            truncado=len(datos) > LIMITE_LECTURA,
        )

    def listar(self, ruta: str) -> list[dict[str, Any]]:
        carpeta = self.perfil.resolver_lectura(ruta, self.base)
        if not carpeta.is_dir():
            raise EjecutorError(f"{carpeta} no es una carpeta")
        entradas = []
        for hijo in sorted(carpeta.iterdir(), key=lambda p: p.name.lower())[:LIMITE_LISTADO]:
            es_archivo = hijo.is_file()
            entradas.append({
                "nombre": hijo.name,
                "tipo": "archivo" if es_archivo else "carpeta",
                "bytes": hijo.stat().st_size if es_archivo else None,
            })
        return entradas

    # ------------------------------------------------------------ efectos

    def escribir(self, ruta: str, contenido: str) -> dict[str, Any]:
        archivo = self.perfil.resolver_escritura(ruta, self.base)
        datos = contenido.encode("utf-8")
        if len(datos) > self.perfil.max_bytes:
            raise CapacidadDenegada(f"la escritura supera {self.perfil.max_bytes} bytes")
        if archivo.is_dir():
            raise EjecutorError(f"{archivo} es una carpeta")
        self._tocar(archivo)
        archivo.parent.mkdir(parents=True, exist_ok=True)
        self.diario.antes_de_escribir(archivo)
        temporal = archivo.with_name(archivo.name + ".lymi-tmp")
        temporal.write_bytes(datos)
        temporal.replace(archivo)
        return {"ruta": str(archivo), "bytes": len(datos)}

    def mover(self, origen: str, destino: str) -> dict[str, Any]:
        desde = self.perfil.resolver_escritura(origen, self.base)
        hasta = self.perfil.resolver_escritura(destino, self.base)
        if not desde.is_file():
            raise EjecutorError(f"{desde} no es un archivo")
        if hasta.is_dir():
            raise EjecutorError(f"{hasta} es una carpeta; indica el nombre del archivo destino")
        self._tocar(desde)
        self._tocar(hasta)
        hasta.parent.mkdir(parents=True, exist_ok=True)
        self.diario.antes_de_mover(desde, hasta)
        os.replace(desde, hasta)
        return {"origen": str(desde), "destino": str(hasta)}

    def borrar(self, ruta: str) -> dict[str, Any]:
        archivo = self.perfil.resolver_escritura(ruta, self.base)
        if not archivo.is_file():
            raise EjecutorError(f"{archivo} no es un archivo (solo se borran archivos)")
        self._tocar(archivo)
        self.diario.borrar(archivo)
        return {"ruta": str(archivo), "en_diario": True}

    def ejecutar(self, nombre: str, args: list[str], *, cwd: str | None = None, timeout: float = 60.0) -> dict[str, Any]:
        comando = self.perfil.comandos.get(nombre)
        if comando is None:
            raise CapacidadDenegada(f"el comando {nombre!r} no esta en la lista blanca del perfil")
        if not all(isinstance(a, str) for a in args):
            raise CapacidadDenegada("los argumentos deben ser texto")
        if comando.subcomandos is not None and (not args or args[0] not in comando.subcomandos):
            permitidos = ", ".join(sorted(comando.subcomandos)) or "ninguno"
            raise CapacidadDenegada(f"{nombre}: solo se permite {permitidos}")

        ejecutable = shutil.which(comando.ejecutable) or (
            comando.ejecutable if Path(comando.ejecutable).is_file() else None
        )
        if ejecutable is None:
            raise EjecutorError(f"no se encontro el ejecutable de {nombre!r}")
        if Path(ejecutable).suffix.lower() in {".bat", ".cmd"}:
            raise CapacidadDenegada(
                f"{nombre}: los .bat y .cmd pasan por cmd.exe y reinterpretan los argumentos"
            )

        if cwd is not None:
            directorio = self.perfil.resolver_escritura(cwd, self.base)
        elif self.perfil.escribibles:
            directorio = self.perfil.escribibles[0]
        else:
            raise CapacidadDenegada("el perfil no tiene carpetas escribibles donde correr comandos")
        directorio.mkdir(parents=True, exist_ok=True)

        entorno = {k: os.environ[k] for k in ENTORNO_MINIMO if k in os.environ}
        try:
            proceso = subprocess.run(
                [ejecutable, *args], cwd=directorio, env=entorno, capture_output=True, text=True,
                timeout=timeout, check=False, stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired:
            self.diario.comando(nombre, args, -1)
            raise EjecutorError(f"{nombre} supero {timeout:g} s") from None
        self.diario.comando(nombre, args, proceso.returncode)
        return {
            "codigo": proceso.returncode,
            "stdout": (proceso.stdout or "")[:LIMITE_SALIDA],
            "stderr": (proceso.stderr or "")[:LIMITE_SALIDA],
        }
