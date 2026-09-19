"""Indice local del codigo de un repositorio, siempre fresco y barato.

Un agente que no tiene mapa re-explora el repositorio en cada tarea: busca, abre
un archivo entero, sigue un import, vuelve atras. El indice responde lo mismo
con una fraccion del texto: la firma de una funcion en vez del archivo, el cuerpo
de un simbolo en vez del modulo, quien lo llama en vez de un grep a ciegas.

Dos decisiones:

- **Fresco antes de cada consulta.** Se comparan fecha y tamano de cada archivo
  con lo indexado (milisegundos) y solo se vuelve a analizar lo que cambio; si
  el contenido es igual (mismo hash), ni eso. Asi el indice nunca describe codigo
  viejo, incluidos los cambios sin commitear.
- **No se indexa lo que no debe salir.** Un archivo etiquetado `nunca-sale` no
  entra al indice: lo que el indice devuelve puede terminar en un prompt remoto.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from lymi.codigo.extraer import LENGUAJES, MODULO, VERSION, extraer
from lymi.privacidad.etiquetas import EtiquetaError, Etiquetas, Nivel, cargar_etiquetas

IGNORAR = frozenset({
    ".git", "node_modules", ".venv", "venv", "__pycache__", "runs", "dist", "build", "target",
    ".mypy_cache", ".ruff_cache", ".pytest_cache", ".tox", ".next", ".idea", ".vscode",
})
MAX_BYTES_ARCHIVO = 1_000_000
MAX_LINEAS_FRAGMENTO = 400
_ESQUEMA = """
CREATE TABLE IF NOT EXISTS archivos (
    ruta TEXT PRIMARY KEY, lenguaje TEXT NOT NULL, hash TEXT NOT NULL, bytes INTEGER NOT NULL,
    lineas INTEGER NOT NULL, mtime_ns INTEGER NOT NULL, exacto INTEGER NOT NULL,
    esqueleto TEXT NOT NULL, error TEXT
);
CREATE TABLE IF NOT EXISTS simbolos (
    ruta TEXT NOT NULL, nombre TEXT NOT NULL, simple TEXT NOT NULL, tipo TEXT NOT NULL,
    linea INTEGER NOT NULL, linea_fin INTEGER NOT NULL, firma TEXT NOT NULL, doc TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS llamadas (
    ruta TEXT NOT NULL, desde TEXT NOT NULL, hacia TEXT NOT NULL, linea INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS importaciones (ruta TEXT NOT NULL, modulo TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS meta (clave TEXT PRIMARY KEY, valor TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS i_simbolos_simple ON simbolos(simple);
CREATE INDEX IF NOT EXISTS i_simbolos_ruta ON simbolos(ruta);
CREATE INDEX IF NOT EXISTS i_llamadas_hacia ON llamadas(hacia);
CREATE INDEX IF NOT EXISTS i_llamadas_ruta ON llamadas(ruta);
CREATE INDEX IF NOT EXISTS i_importaciones_ruta ON importaciones(ruta);
"""


class IndiceError(ValueError):
    """La raiz o la ruta pedida no son validas."""


def ruta_indice(raiz: Path) -> Path:
    clave = hashlib.sha1(os.path.normcase(str(raiz)).encode("utf-8")).hexdigest()[:12]
    return Path(os.environ.get("LYMI_CODIGO", "runs/codigo")) / f"{clave}.sqlite3"


def relativa(ruta: str) -> str:
    """`./a/b.py` o `a\b.py` -> `a/b.py`, sin tocar nombres que empiezan con punto."""
    texto = ruta.strip().replace("\\", "/")
    while texto.startswith("./"):
        texto = texto[2:]
    return texto


def es_prueba(ruta: str) -> bool:
    partes = PurePosixPath(ruta).parts
    nombre = partes[-1] if partes else ""
    return "tests" in partes[:-1] or "test" in partes[:-1] or nombre.startswith("test_") or ".test." in nombre


@dataclass(slots=True)
class Actualizacion:
    nuevos: int = 0
    cambiados: int = 0
    borrados: int = 0
    reusados: int = 0
    omitidos: list[str] = field(default_factory=list)
    ms: int = 0

    def resumen(self) -> str:
        texto = (
            f"{self.nuevos} nuevos, {self.cambiados} cambiados, {self.borrados} borrados, "
            f"{self.reusados} sin cambios ({self.ms} ms)"
        )
        if self.omitidos:
            texto += f"; {len(self.omitidos)} omitidos por sensibilidad o tamano"
        return texto


class Indice:
    def __init__(self, raiz: Path, *, db: Path | None = None, etiquetas: Etiquetas | None = None) -> None:
        raiz = Path(raiz).resolve()
        if not raiz.is_dir():
            raise IndiceError(f"{raiz} no es una carpeta")
        self.raiz = raiz
        self.etiquetas = etiquetas or Etiquetas()
        self.db = db or ruta_indice(raiz)
        self.db.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_ESQUEMA)
        self.ultima: Actualizacion | None = None
        self._revisar_version()

    def _revisar_version(self) -> None:
        """Un indice hecho por otro extractor tiene datos derivados viejos: se rehace."""
        fila = self._conn.execute("SELECT valor FROM meta WHERE clave = 'version'").fetchone()
        if fila is not None and fila[0] == str(VERSION):
            return
        with self._conn:
            for tabla in ("archivos", "simbolos", "llamadas", "importaciones"):
                self._conn.execute(f"DELETE FROM {tabla}")
            self._conn.execute("INSERT OR REPLACE INTO meta VALUES ('version', ?)", (str(VERSION),))

    def cerrar(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------ indexar

    def _listar(self) -> list[str]:
        rutas: list[str] | None = None
        if (self.raiz / ".git").exists():
            try:
                salida = subprocess.run(
                    ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                    cwd=self.raiz, capture_output=True, timeout=30, check=True, stdin=subprocess.DEVNULL,
                )
                rutas = [r for r in salida.stdout.decode("utf-8", errors="replace").split("\0") if r]
            except (OSError, subprocess.SubprocessError):
                rutas = None
        if rutas is None:
            rutas = []
            for carpeta, subcarpetas, archivos in os.walk(self.raiz):
                subcarpetas[:] = [d for d in subcarpetas if d not in IGNORAR and not d.startswith(".")]
                base = Path(carpeta).relative_to(self.raiz)
                rutas.extend((base / a).as_posix() for a in archivos)
        return sorted(
            r for r in rutas
            if Path(r).suffix.lower() in LENGUAJES and not any(p in IGNORAR for p in PurePosixPath(r).parts)
        )

    def actualizar(self) -> Actualizacion:
        inicio = time.perf_counter()
        informe = Actualizacion()
        previos = {
            f["ruta"]: f for f in self._conn.execute("SELECT ruta, hash, bytes, mtime_ns FROM archivos")
        }
        vistos: set[str] = set()
        with self._conn:
            for rel in self._listar():
                archivo = self.raiz / rel
                try:
                    if archivo.is_symlink() or not archivo.is_file():
                        continue
                    estado = archivo.stat()
                except OSError:
                    continue
                if estado.st_size > MAX_BYTES_ARCHIVO or self.etiquetas.nivel_de(archivo) is Nivel.NUNCA_SALE:
                    informe.omitidos.append(rel)
                    continue
                vistos.add(rel)
                previo = previos.get(rel)
                if previo is not None and previo["mtime_ns"] == estado.st_mtime_ns and previo["bytes"] == estado.st_size:
                    informe.reusados += 1
                    continue
                try:
                    datos = archivo.read_bytes()
                except OSError:
                    vistos.discard(rel)
                    continue
                if b"\0" in datos[:8192]:
                    vistos.discard(rel)
                    continue
                huella = hashlib.sha256(datos).hexdigest()
                if previo is not None and previo["hash"] == huella:
                    self._conn.execute("UPDATE archivos SET mtime_ns = ? WHERE ruta = ?", (estado.st_mtime_ns, rel))
                    informe.reusados += 1
                    continue
                self._guardar(rel, datos, huella, estado.st_mtime_ns)
                if previo is None:
                    informe.nuevos += 1
                else:
                    informe.cambiados += 1
            for rel in set(previos) - vistos:
                self._borrar(rel)
                informe.borrados += 1
        informe.ms = int((time.perf_counter() - inicio) * 1000)
        return informe

    def _borrar(self, rel: str) -> None:
        for tabla in ("archivos", "simbolos", "llamadas", "importaciones"):
            self._conn.execute(f"DELETE FROM {tabla} WHERE ruta = ?", (rel,))

    def _guardar(self, rel: str, datos: bytes, huella: str, mtime_ns: int) -> None:
        texto = datos.decode("utf-8", errors="replace")
        extraido = extraer(texto, rel, LENGUAJES[Path(rel).suffix.lower()])
        self._borrar(rel)
        self._conn.execute(
            "INSERT INTO archivos VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (rel, extraido.lenguaje, huella, len(datos), texto.count("\n") + 1, mtime_ns,
             int(extraido.exacto), extraido.esqueleto, extraido.error),
        )
        self._conn.executemany(
            "INSERT INTO simbolos VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [(rel, s.nombre, s.nombre.rsplit(".", 1)[-1], s.tipo, s.linea, s.linea_fin, s.firma, s.doc)
             for s in extraido.simbolos],
        )
        self._conn.executemany(
            "INSERT INTO llamadas VALUES (?, ?, ?, ?)", [(rel, c.desde, c.hacia, c.linea) for c in extraido.llamadas]
        )
        self._conn.executemany("INSERT INTO importaciones VALUES (?, ?)", [(rel, m) for m in extraido.importaciones])

    # ------------------------------------------------------------ consultas

    def _archivo(self, ruta: str) -> sqlite3.Row:
        rel = relativa(ruta)
        fila = self._conn.execute("SELECT * FROM archivos WHERE ruta = ?", (rel,)).fetchone()
        if fila is None:
            # Solo se sirve lo indexado: una ruta con `..` o absoluta nunca coincide.
            raise IndiceError(f"{ruta!r} no esta en el indice (ruta relativa a la raiz, archivo de codigo)")
        return fila

    def buscar(self, consulta: str, limite: int = 20) -> list[dict[str, Any]]:
        consulta = consulta.strip()
        if not consulta:
            raise IndiceError("consulta vacia")
        patron = "%" + consulta.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        filas = self._conn.execute(
            "SELECT s.*, a.exacto FROM simbolos s JOIN archivos a USING (ruta) "
            "WHERE s.nombre LIKE ? ESCAPE '\\' COLLATE NOCASE",
            (patron,),
        ).fetchall()
        baja = consulta.lower()

        def orden(f: sqlite3.Row) -> tuple:
            simple = f["simple"].lower()
            return (simple != baja, not simple.startswith(baja), es_prueba(f["ruta"]), len(f["nombre"]), f["ruta"])

        return [
            {"nombre": f["nombre"], "tipo": f["tipo"], "ruta": f["ruta"], "linea": f["linea"],
             "firma": f["firma"], "doc": f["doc"], "exacto": bool(f["exacto"])}
            for f in sorted(filas, key=orden)[:limite]
        ]

    def esqueleto(self, ruta: str) -> dict[str, Any]:
        fila = self._archivo(ruta)
        return {
            "ruta": fila["ruta"], "lenguaje": fila["lenguaje"], "exacto": bool(fila["exacto"]),
            "lineas": fila["lineas"], "bytes_archivo": fila["bytes"], "esqueleto": fila["esqueleto"],
            "error": fila["error"],
        }

    def _simbolos(self, nombre: str) -> list[sqlite3.Row]:
        nombre = nombre.strip()
        if not nombre:
            raise IndiceError("nombre vacio")
        return self._conn.execute(
            "SELECT * FROM simbolos WHERE nombre = ? OR nombre LIKE ? ESCAPE '\\' ORDER BY ruta, linea",
            (nombre, "%." + nombre.replace("%", "\\%").replace("_", "\\_")),
        ).fetchall()

    def fragmento(self, nombre: str, limite: int = 3) -> list[dict[str, Any]]:
        """El codigo de un simbolo, no del archivo entero."""
        resultados = []
        for fila in self._simbolos(nombre)[:limite]:
            archivo = self._archivo(fila["ruta"])
            try:
                lineas = (self.raiz / fila["ruta"]).read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            fin = min(fila["linea_fin"], fila["linea"] + MAX_LINEAS_FRAGMENTO - 1)
            if not archivo["exacto"]:
                # Sin analizador no se sabe donde termina: hasta la siguiente definicion.
                siguiente = self._conn.execute(
                    "SELECT MIN(linea) FROM simbolos WHERE ruta = ? AND linea > ?", (fila["ruta"], fila["linea"])
                ).fetchone()[0]
                fin = min((siguiente or len(lineas) + 1) - 1, fila["linea"] + 80)
            codigo = "\n".join(lineas[fila["linea"] - 1 : fin])
            resultados.append({
                "nombre": fila["nombre"], "ruta": fila["ruta"], "linea": fila["linea"], "linea_fin": fin,
                "codigo": codigo, "bytes_archivo": archivo["bytes"], "exacto": bool(archivo["exacto"]),
            })
        return resultados

    def _alcance(self) -> dict[str, set[str]]:
        """Archivos del repositorio que cada archivo Python alcanza por import.

        Con un salto a traves de paquetes: `from lymi.web import Web` importa
        `lymi/web/__init__.py`, que a su vez importa `red.py`, donde vive `Web`.
        """
        conocidas: dict[str, list[str]] = {}
        python: set[str] = set()
        for ruta, lenguaje in self._conn.execute("SELECT ruta, lenguaje FROM archivos"):
            conocidas.setdefault(PurePosixPath(ruta).name, []).append(ruta)
            if lenguaje == "python":
                python.add(ruta)
        modulos: dict[str, list[str]] = {}
        for ruta, modulo in self._conn.execute("SELECT ruta, modulo FROM importaciones"):
            if ruta in python:
                modulos.setdefault(ruta, []).append(modulo)
        directos = {r: set(self._dependencias_internas(r, modulos.get(r, []), conocidas)) for r in python}
        alcance = {}
        for ruta, deps in directos.items():
            total = set(deps)
            for dep in deps:
                if dep.endswith("__init__.py"):
                    total |= directos.get(dep, set())
            alcance[ruta] = total
        return alcance

    def _clasificar(self, simple: str, definiciones: set[str], alcance: dict[str, set[str]]) -> list[dict[str, Any]]:
        """Llamadas a `simple`, marcando cuales estan confirmadas por importacion.

        Sin tipos, `x.obtener()` puede ser el `obtener` de cualquier clase. Una
        llamada se confirma si ocurre en el archivo que define el simbolo o en uno
        que lo importa. Las demas no se esconden: se devuelven como posibles.
        """
        resultados = []
        for f in self._conn.execute(
            "SELECT desde, ruta, linea FROM llamadas WHERE hacia = ? ORDER BY ruta, linea", (simple,)
        ):
            if not definiciones or f["ruta"] in definiciones or f["ruta"] not in alcance:
                confirmado = True
            else:
                confirmado = bool(definiciones & alcance[f["ruta"]])
            resultados.append({"desde": f["desde"], "ruta": f["ruta"], "linea": f["linea"], "confirmado": confirmado})
        return resultados

    def _definiciones(self, nombre: str) -> set[tuple[str, str]]:
        return {(f["simple"], f["ruta"]) for f in self._simbolos(nombre)}

    def llamadores(self, nombre: str) -> list[dict[str, Any]]:
        simple = nombre.strip().rsplit(".", 1)[-1]
        if not simple:
            raise IndiceError("nombre vacio")
        rutas = {ruta for _, ruta in self._definiciones(nombre)}
        return self._clasificar(simple, rutas, self._alcance() if rutas else {})

    def impacto(self, nombre: str, profundidad: int = 3) -> dict[str, Any]:
        """Que se ve afectado si cambia `nombre`: llamadores transitivos confirmados y sus pruebas."""
        profundidad = max(1, min(profundidad, 6))
        simple = nombre.strip().rsplit(".", 1)[-1]
        if not simple:
            raise IndiceError("nombre vacio")
        alcance = self._alcance()
        frontera: set[tuple[str, str | None]] = set(self._definiciones(nombre)) or {(simple, None)}
        vistos: set[tuple[str, str]] = set()
        niveles: list[list[dict[str, Any]]] = []
        posibles = 0
        for _ in range(profundidad):
            por_simple: dict[str, set[str]] = {}
            for s, ruta in frontera:
                por_simple.setdefault(s, set())
                if ruta is not None:
                    por_simple[s].add(ruta)
            nivel = []
            siguiente: set[tuple[str, str | None]] = set()
            for s in sorted(por_simple):
                for f in self._clasificar(s, por_simple[s], alcance):
                    if not f["confirmado"]:
                        posibles += 1
                        continue
                    clave = (f["ruta"], f["desde"])
                    if clave in vistos:
                        continue
                    vistos.add(clave)
                    nivel.append({"simbolo": f["desde"], "ruta": f["ruta"]})
                    if f["desde"] != MODULO:
                        # El llamador esta definido en el archivo donde hace la llamada.
                        siguiente.add((f["desde"].rsplit(".", 1)[-1], f["ruta"]))
            if not nivel:
                break
            niveles.append(nivel)
            frontera = siguiente
        archivos = sorted({ruta for ruta, _ in vistos})
        return {
            "nombre": nombre,
            "niveles": niveles,
            "archivos": [a for a in archivos if not es_prueba(a)],
            "pruebas": [a for a in archivos if es_prueba(a)],
            "posibles": posibles,
            "nota": (
                "llamadas confirmadas por importacion (sin tipos); "
                f"{posibles} llamadas a homonimos en archivos que no importan la definicion quedaron fuera"
            ),
        }

    @staticmethod
    def _dependencias_internas(ruta: str, modulos: list[str], conocidas: dict[str, list[str]]) -> list[str]:
        """Importaciones de Python que apuntan a otro archivo del mismo repositorio.

        `conocidas` agrupa las rutas indexadas por nombre de archivo, para no
        recorrer el repositorio entero por cada import.
        """
        encontradas = []
        carpeta = PurePosixPath(ruta).parent
        for modulo in modulos:
            puntos = len(modulo) - len(modulo.lstrip("."))
            nombre = modulo.lstrip(".").replace(".", "/")
            if puntos:
                base = carpeta
                for _ in range(puntos - 1):
                    base = base.parent
                sufijos = [f"{base / nombre}.py", f"{base / nombre}/__init__.py"] if nombre else []
                exactos = True
            else:
                sufijos = [f"{nombre}.py", f"{nombre}/__init__.py"]
                exactos = False
            for sufijo in sufijos:
                candidatas = conocidas.get(PurePosixPath(sufijo).name, [])
                aciertos = [c for c in candidatas if c == sufijo or (not exactos and c.endswith("/" + sufijo))]
                if aciertos:
                    encontradas.append(aciertos[0])
                    break
        return sorted(set(encontradas) - {ruta})

    def mapa(self, prefijo: str = "", limite: int = 200) -> dict[str, Any]:
        prefijo = relativa(prefijo)
        filas = self._conn.execute(
            "SELECT a.ruta, a.lenguaje, a.exacto, a.lineas, "
            "(SELECT COUNT(*) FROM simbolos s WHERE s.ruta = a.ruta) AS simbolos "
            "FROM archivos a WHERE a.ruta LIKE ? ESCAPE '\\' ORDER BY a.ruta",
            (prefijo.replace("%", "\\%").replace("_", "\\_") + "%",),
        ).fetchall()
        conocidas: dict[str, list[str]] = {}
        for (ruta,) in self._conn.execute("SELECT ruta FROM archivos"):
            conocidas.setdefault(PurePosixPath(ruta).name, []).append(ruta)
        importaciones: dict[str, list[str]] = {}
        for ruta, modulo in self._conn.execute("SELECT ruta, modulo FROM importaciones"):
            importaciones.setdefault(ruta, []).append(modulo)
        archivos = []
        for f in filas[:limite]:
            deps = []
            if f["lenguaje"] == "python":
                deps = self._dependencias_internas(f["ruta"], importaciones.get(f["ruta"], []), conocidas)
            archivos.append({
                "ruta": f["ruta"], "lenguaje": f["lenguaje"], "exacto": bool(f["exacto"]),
                "lineas": f["lineas"], "simbolos": f["simbolos"], "usa": deps,
            })
        lenguajes: dict[str, int] = {}
        for f in filas:
            lenguajes[f["lenguaje"]] = lenguajes.get(f["lenguaje"], 0) + 1
        return {"total": len(filas), "mostrados": len(archivos), "lenguajes": lenguajes, "archivos": archivos}


@contextmanager
def abrir(raiz: Path | str, *, db: Path | None = None, etiquetas: Etiquetas | None = None) -> Iterator[Indice]:
    """Abre el indice, lo pone al dia y lo cierra al salir.

    Sin etiquetas explicitas rigen las del directorio actual (`sensibilidad.yml`),
    las mismas que usa `flow run`, mas el piso fijo.
    """
    if etiquetas is None:
        try:
            etiquetas = cargar_etiquetas(Path("sensibilidad.yml"))
        except EtiquetaError as exc:
            raise IndiceError(str(exc)) from None
    indice = Indice(Path(raiz), db=db, etiquetas=etiquetas)
    try:
        indice.ultima = indice.actualizar()
        yield indice
    finally:
        indice.cerrar()
