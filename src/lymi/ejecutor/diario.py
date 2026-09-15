"""Diario de deshacer.

Antes de modificar, mover o borrar un archivo, se guarda como estaba. Borrar es
mover al diario: nada se elimina de verdad, ni siquiera al deshacer (lo que se
quita al deshacer tambien va al diario). Un comando no se puede deshacer, pero
queda anotado con su codigo de salida.

El diario vive en `runs/diario/<corrida>/`, que el ejecutor tiene vetado: el
agente no puede reescribir su propio historial.
"""

from __future__ import annotations

import json
import os
import shutil
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


class DiarioError(RuntimeError):
    """No hay diario para esa corrida, o ya se deshizo."""


def raiz_diario() -> Path:
    return Path(os.environ.get("LYMI_DIARIO", "runs/diario"))


@dataclass(slots=True)
class Diario:
    carpeta: Path

    def __post_init__(self) -> None:
        (self.carpeta / "copias").mkdir(parents=True, exist_ok=True)

    @property
    def _registro(self) -> Path:
        return self.carpeta / "diario.jsonl"

    def _anotar(self, entrada: dict) -> None:
        entrada = {"ts": datetime.now(UTC).isoformat(timespec="seconds"), **entrada}
        with self._registro.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entrada, ensure_ascii=False) + "\n")

    def _guardar_copia(self, ruta: Path) -> str:
        nombre = uuid.uuid4().hex
        shutil.copy2(ruta, self.carpeta / "copias" / nombre)
        return nombre

    def antes_de_escribir(self, ruta: Path) -> None:
        if ruta.exists():
            self._anotar({"op": "modificado", "ruta": str(ruta), "copia": self._guardar_copia(ruta)})
        else:
            self._anotar({"op": "creado", "ruta": str(ruta)})

    def antes_de_mover(self, origen: Path, destino: Path) -> None:
        copia = self._guardar_copia(destino) if destino.exists() else None
        self._anotar({"op": "movido", "origen": str(origen), "destino": str(destino), "copia_destino": copia})

    def borrar(self, ruta: Path) -> None:
        nombre = uuid.uuid4().hex
        shutil.move(str(ruta), self.carpeta / "copias" / nombre)
        self._anotar({"op": "borrado", "ruta": str(ruta), "copia": nombre})

    def comando(self, nombre: str, args: list[str], codigo: int) -> None:
        self._anotar({"op": "comando", "nombre": nombre, "args": args, "codigo": codigo})


def deshacer(carpeta: Path) -> list[str]:
    """Deshace una corrida en orden inverso. Devuelve lo que hizo, en palabras."""
    registro = carpeta / "diario.jsonl"
    if not registro.exists():
        raise DiarioError(f"no hay diario en {carpeta}")
    marca = carpeta / "DESHECHO"
    if marca.exists():
        raise DiarioError(f"esa corrida ya se deshizo ({marca.read_text(encoding='utf-8').strip()})")

    entradas = [json.loads(linea) for linea in registro.read_text(encoding="utf-8").splitlines() if linea.strip()]
    copias = carpeta / "copias"
    papelera = carpeta / "retirados"
    papelera.mkdir(exist_ok=True)

    def apartar(ruta: Path) -> None:
        if ruta.exists():
            shutil.move(str(ruta), papelera / uuid.uuid4().hex)

    informe: list[str] = []
    for e in reversed(entradas):
        op = e["op"]
        if op == "creado":
            ruta = Path(e["ruta"])
            if ruta.exists():
                apartar(ruta)
                informe.append(f"quitado {ruta} (guardado en el diario)")
        elif op in {"modificado", "borrado"}:
            ruta = Path(e["ruta"])
            apartar(ruta)
            ruta.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(copias / e["copia"], ruta)
            informe.append(f"restaurado {ruta}")
        elif op == "movido":
            origen, destino = Path(e["origen"]), Path(e["destino"])
            if destino.exists():
                origen.parent.mkdir(parents=True, exist_ok=True)
                apartar(origen)
                shutil.move(str(destino), origen)
            if e.get("copia_destino"):
                shutil.copy2(copias / e["copia_destino"], destino)
            informe.append(f"devuelto {destino} a {origen}")
        elif op == "comando":
            informe.append(f"no se puede deshacer: comando {e['nombre']} {' '.join(e['args'])} (codigo {e['codigo']})")

    marca.write_text(datetime.now(UTC).isoformat(timespec="seconds"), encoding="utf-8")
    return informe
