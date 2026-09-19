"""Memoria de lymi: notas en markdown, con promocion antes de volverse verdad.

Tres estados, en tres carpetas, para que se vea con cualquier editor (Obsidian
incluido):

- `afirmaciones/`: lo que anoto un agente. Puede venir de una pagina web con
  malas intenciones, asi que nunca se presenta como hecho.
- `hechos/`: lo que una persona reviso y promovio, o escribio ella misma.
- `descartadas/`: lo que se rechazo. No se borra: la memoria es auditable.

Cualquier otro `.md` bajo la raiz (por ejemplo, tu vault) cuenta como hecho
escrito por ti.

La busqueda es lexica (BM25), en local y gratis, y devuelve `ruta:linea` para que
un agente pueda citar de donde saco algo y lymi pueda comprobarlo.

Nada con aspecto de secreto entra a la memoria: lo que se guarda aqui puede
terminar, dias despues, en un prompt.
"""

from __future__ import annotations

import os
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from lymi.privacidad import EgressBloqueado, Redactor, sanear
from lymi.web.investigar import Pasaje, puntuar, trocear

ESTADOS = ("afirmaciones", "hechos", "descartadas")
MAX_CARACTERES = 4000
MAX_ARCHIVOS = 3000
MAX_BYTES_NOTA = 200_000
_ID = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{6}$")


class MemoriaError(ValueError):
    """La nota no se puede guardar, o el id no existe."""


def raiz_memoria() -> Path:
    return Path(os.environ.get("LYMI_MEMORIA", "memoria"))


@dataclass(slots=True)
class Nota:
    id: str
    estado: str
    """afirmacion | hecho | descartada | propia"""
    texto: str
    fuente: str
    agente: str
    corrida: str | None
    creada: str
    ruta: Path
    linea_texto: int
    """Linea donde empieza el texto dentro del archivo (despues del frontmatter)."""


@dataclass(slots=True)
class Recuerdo:
    nota: Nota
    fragmento: str
    linea: int
    puntaje: float


def _leer(ruta: Path, estado: str) -> Nota | None:
    try:
        crudo = ruta.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    meta: dict[str, Any] = {}
    cuerpo, linea = crudo, 1
    if crudo.startswith("---\n"):
        fin = crudo.find("\n---\n", 4)
        if fin != -1:
            try:
                meta = yaml.safe_load(crudo[4:fin]) or {}
            except yaml.YAMLError:
                meta = {}
            cuerpo = crudo[fin + 5 :]
            linea = crudo[: fin + 5].count("\n") + 1
    if not isinstance(meta, dict):
        meta = {}
    return Nota(
        id=str(meta.get("id") or ruta.stem), estado=estado, texto=cuerpo.strip(),
        fuente=str(meta.get("fuente") or ""), agente=str(meta.get("agente") or "usuario"),
        corrida=meta.get("corrida"), creada=str(meta.get("creada") or ""), ruta=ruta, linea_texto=linea,
    )


class Memoria:
    def __init__(self, raiz: Path | None = None) -> None:
        self.raiz = Path(raiz or raiz_memoria())

    # ------------------------------------------------------------ escribir

    def anotar(
        self, texto: str, *, fuente: str, agente: str = "usuario", corrida: str | None = None, hecho: bool = False
    ) -> Nota:
        """Guarda una nota. Los agentes siempre escriben afirmaciones; solo una persona escribe hechos."""
        texto = sanear(texto).texto.strip()
        if not texto:
            raise MemoriaError("la nota esta vacia")
        if len(texto) > MAX_CARACTERES:
            raise MemoriaError(f"la nota supera {MAX_CARACTERES} caracteres: resume antes de guardar")
        redactor = Redactor()
        try:
            redactor.redactar(f"{texto}\n{fuente}")
        except EgressBloqueado as exc:
            raise MemoriaError(f"no se guarda: {exc}") from None
        secretos = {k: v for k, v in redactor.conteo.items() if k in {"CLAVE_API", "TOKEN", "CREDENCIAL", "TARJETA"}}
        if secretos:
            raise MemoriaError(f"no se guarda: la nota lleva {', '.join(sorted(secretos)).lower().replace('_', ' ')}")

        ahora = datetime.now(UTC)
        nota_id = f"{ahora:%Y%m%d-%H%M%S}-{secrets.token_hex(3)}"
        carpeta = self.raiz / ("hechos" if hecho else "afirmaciones")
        carpeta.mkdir(parents=True, exist_ok=True)
        meta = {
            "id": nota_id, "estado": "hecho" if hecho else "afirmacion", "fuente": fuente[:500],
            "agente": agente[:120], "corrida": corrida, "creada": ahora.isoformat(timespec="seconds"),
        }
        encabezado = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False)
        ruta = carpeta / f"{nota_id}.md"
        ruta.write_text(f"---\n{encabezado}---\n{texto}\n", encoding="utf-8")
        nota = _leer(ruta, "hecho" if hecho else "afirmacion")
        assert nota is not None
        return nota

    def _mover(self, nota_id: str, desde: str, hacia: str) -> Nota:
        if not _ID.match(nota_id):
            raise MemoriaError(f"id invalido: {nota_id!r}")
        origen = self.raiz / desde / f"{nota_id}.md"
        if not origen.exists():
            raise MemoriaError(f"no hay una nota {nota_id} en {desde}/")
        destino = self.raiz / hacia / origen.name
        destino.parent.mkdir(parents=True, exist_ok=True)
        crudo = origen.read_text(encoding="utf-8")
        estado = {"hechos": "hecho", "descartadas": "descartada"}[hacia]
        marca = f"{estado}_el: '{datetime.now(UTC).isoformat(timespec='seconds')}'\n"
        crudo = crudo.replace("estado: afirmacion\n", f"estado: {estado}\n{marca}", 1)
        destino.write_text(crudo, encoding="utf-8")
        origen.unlink()
        nota = _leer(destino, estado)
        assert nota is not None
        return nota

    def promover(self, nota_id: str) -> Nota:
        return self._mover(nota_id, "afirmaciones", "hechos")

    def descartar(self, nota_id: str) -> Nota:
        return self._mover(nota_id, "afirmaciones", "descartadas")

    # ------------------------------------------------------------ leer

    def listar(self, estado: str = "afirmaciones") -> list[Nota]:
        carpeta = self.raiz / estado
        if not carpeta.is_dir():
            return []
        singular = {"afirmaciones": "afirmacion", "hechos": "hecho", "descartadas": "descartada"}[estado]
        notas = [n for r in sorted(carpeta.glob("*.md")) if (n := _leer(r, singular)) is not None]
        return notas

    def _todas(self) -> list[Nota]:
        """Afirmaciones, hechos y las notas propias del usuario (cualquier otro .md)."""
        notas = self.listar("hechos") + self.listar("afirmaciones")
        if not self.raiz.is_dir():
            return notas
        vistas = 0
        for ruta in sorted(self.raiz.rglob("*.md")):
            relativa = ruta.relative_to(self.raiz).parts
            if relativa[0] in ESTADOS or any(p.startswith(".") for p in relativa):
                continue
            vistas += 1
            if vistas > MAX_ARCHIVOS:
                break
            try:
                if ruta.stat().st_size > MAX_BYTES_NOTA:
                    continue
            except OSError:
                continue
            if (nota := _leer(ruta, "propia")) is not None:
                notas.append(nota)
        return notas

    def buscar(self, consulta: str, n: int = 5, *, solo_hechos: bool = False) -> list[Recuerdo]:
        consulta = consulta.strip()
        if not consulta:
            raise MemoriaError("consulta vacia")
        notas = [x for x in self._todas() if not solo_hechos or x.estado in {"hecho", "propia"}]
        pasajes: list[Pasaje] = []
        dueno: list[tuple[Nota, int]] = []
        for nota in notas:
            desplazamiento = 0
            for trozo in trocear(nota.texto, tam=700):
                posicion = nota.texto.find(trozo[:40], desplazamiento)
                linea = nota.linea_texto + (nota.texto.count("\n", 0, posicion) if posicion >= 0 else 0)
                desplazamiento = max(posicion, 0)
                pasajes.append(Pasaje(len(dueno), trozo))
                dueno.append((nota, linea))
        resultados = []
        for pasaje in puntuar(consulta, pasajes):
            if pasaje.puntaje <= 0 or len(resultados) >= n:
                break
            nota, linea = dueno[pasaje.fuente]
            resultados.append(Recuerdo(nota, pasaje.texto, linea, pasaje.puntaje))
        return resultados


def formato(recuerdos: list[Recuerdo], raiz: Path) -> str:
    """Texto para un agente: cada recuerdo con su estado y su `ruta:linea`."""
    if not recuerdos:
        return "la memoria no tiene nada sobre eso"
    etiquetas = {"hecho": "hecho", "propia": "nota del usuario", "afirmacion": "SIN REVISAR"}
    bloques = []
    for r in recuerdos:
        try:
            ruta = r.nota.ruta.relative_to(raiz.parent).as_posix()
        except ValueError:
            ruta = r.nota.ruta.as_posix()
        fuente = f"; fuente: {r.nota.fuente}" if r.nota.fuente else ""
        bloques.append(f"[{etiquetas[r.nota.estado]}] {ruta}:{r.linea}{fuente}\n{r.fragmento}")
    aviso = ""
    if any(r.nota.estado == "afirmacion" for r in recuerdos):
        aviso = "\n\n(Lo SIN REVISAR lo anoto un agente y nadie lo confirmo: no lo presentes como hecho.)"
    return "\n\n".join(bloques) + aviso
