"""Tareas del banco de pruebas.

Cada tarea trae una PUERTA objetiva. Sin puerta, "ahorrar tokens" degenera en
"romper el agente y celebrar la factura baja": la puerta es lo que convierte una
medicion de costo en una medicion util.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

#: Guion que ejercita el codigo generado para Snake. Se ejecuta en un proceso
#: aparte, contra el modulo que produjo el agente.
SNAKE_HARNESS = '''
import importlib.util, sys, json

spec = importlib.util.spec_from_file_location("solucion", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
# @dataclass consulta sys.modules[cls.__module__]: sin registrar el modulo
# antes de ejecutarlo, toda solucion que use dataclasses reprueba por un
# fallo del arnes, no del codigo evaluado.
sys.modules["solucion"] = mod
spec.loader.exec_module(mod)

import dataclasses

fallos = []


def con_comida(estado, posicion):
    """Coloca la comida sin exigir un diseno concreto de estado.

    El enunciado no dice si el estado es mutable, y `paso` "devuelve el estado
    nuevo" invita justo al diseno inmutable. Asignar el atributo a secas
    reprobaba soluciones correctas con dataclass congelado: la puerta medía la
    implementacion, no el comportamiento pedido.
    """
    try:
        estado.comida = posicion
        return estado
    except (AttributeError, TypeError):
        pass
    if dataclasses.is_dataclass(estado):
        return dataclasses.replace(estado, comida=posicion)
    if hasattr(estado, "_replace"):
        return estado._replace(comida=posicion)
    if hasattr(estado, "model_copy"):
        return estado.model_copy(update={"comida": posicion})
    raise TypeError(f"no se puede colocar la comida en {type(estado).__name__}")


# 1. La serpiente avanza en la direccion indicada.
estado = mod.nuevo_juego(ancho=10, alto=10)
antes = list(estado.serpiente)
estado = mod.paso(estado, (1, 0))
if list(estado.serpiente)[0] == antes[0]:
    fallos.append("la serpiente no avanzo")

# 2. Comer hace crecer el cuerpo.
estado = mod.nuevo_juego(ancho=10, alto=10)
cabeza = estado.serpiente[0]
estado = con_comida(estado, (cabeza[0] + 1, cabeza[1]))
largo_antes = len(estado.serpiente)
estado = mod.paso(estado, (1, 0))
if len(estado.serpiente) != largo_antes + 1:
    fallos.append("comer no hizo crecer la serpiente")

# 3. Chocar contra el muro termina el juego.
estado = mod.nuevo_juego(ancho=4, alto=4)
for _ in range(8):
    estado = mod.paso(estado, (1, 0))
    if estado.terminado:
        break
if not estado.terminado:
    fallos.append("chocar contra el muro no termino el juego")

print(json.dumps(fallos))
'''


@dataclass(frozen=True, slots=True)
class GateResult:
    """Veredicto de la puerta de una tarea."""

    passed: bool
    score: float
    """0..1. Permite distinguir 'fallo total' de 'casi lo logra'."""
    detail: str


class Task(ABC):
    """Una tarea del banco de pruebas."""

    id: str
    title: str
    kind: str
    """'correctitud' | 'ahorro' | 'escalamiento' -- determina como se reporta."""

    @abstractmethod
    def prompt(self) -> str:
        """El enunciado que recibe el agente."""

    @abstractmethod
    def gate(self, output: str) -> GateResult:
        """Verifica objetivamente si el resultado sirve."""


def _extraer_codigo(salida: str) -> str:
    """Saca el bloque de codigo Python de una respuesta en markdown."""
    bloques = re.findall(r"```(?:python)?\n(.*?)```", salida, re.DOTALL)
    return bloques[0] if bloques else salida


class SnakeTask(Task):
    """Puerta de CORRECTITUD. Proyecto minusculo: no mide ahorro y no pretende
    hacerlo. Su trabajo es impedir que recortar contexto rompa al agente."""

    id = "snake"
    title = "Snake en Python"
    kind = "correctitud"

    def prompt(self) -> str:
        return (
            "Escribe el juego Snake en Python, en un solo archivo, sin dependencias "
            "externas. La logica debe ser verificable sin interfaz grafica:\n\n"
            "- `nuevo_juego(ancho, alto)` devuelve un estado con los atributos "
            "`serpiente` (lista de tuplas, la cabeza primero), `comida` (tupla), "
            "`terminado` (bool) y `puntaje` (int).\n"
            "- `paso(estado, direccion)` avanza un turno y devuelve el estado nuevo. "
            "`direccion` es una tupla como (1, 0).\n"
            "- Comer la comida hace crecer la serpiente y suma puntaje.\n"
            "- Chocar contra un muro o contra el propio cuerpo pone `terminado` en True.\n"
            "- `main()` corre el juego en la terminal, protegido por "
            "`if __name__ == '__main__':`.\n\n"
            "Responde solo con el codigo en un bloque ```python."
        )

    def gate(self, output: str) -> GateResult:
        codigo = _extraer_codigo(output)
        if not codigo.strip():
            return GateResult(False, 0.0, "la respuesta no contiene codigo")

        with tempfile.TemporaryDirectory() as tmp:
            solucion = Path(tmp) / "solucion.py"
            solucion.write_text(codigo, encoding="utf-8")
            harness = Path(tmp) / "harness.py"
            harness.write_text(SNAKE_HARNESS, encoding="utf-8")

            try:
                proc = subprocess.run(
                    [sys.executable, str(harness), str(solucion)],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                return GateResult(False, 0.0, "el codigo no termino en 30 s")

        if proc.returncode != 0:
            err = (proc.stderr or "").strip().splitlines()
            return GateResult(False, 0.0, f"el codigo fallo al ejecutarse: {err[-1] if err else '?'}")

        try:
            fallos = json.loads(proc.stdout.strip())
        except (json.JSONDecodeError, ValueError):
            return GateResult(False, 0.0, "el arnes no devolvio un resultado legible")

        total = 3
        ok = total - len(fallos)
        return GateResult(
            passed=not fallos,
            score=ok / total,
            detail="las 3 comprobaciones pasaron" if not fallos else "; ".join(fallos),
        )


class ResearchTask(Task):
    """Puerta de AHORRO. Aqui vive el mayor margen: el agente ingenuo vuelca
    paginas crudas al modelo caro."""

    id = "research"
    title = "Investigacion con fuentes"
    kind = "ahorro"

    #: Elementos que una respuesta util tiene que contener. Objetivo y verificable.
    REQUISITOS = ("licencia", "contexto", "precio", "local")

    def prompt(self) -> str:
        return (
            "Investiga y compara los modelos de lenguaje abiertos que corren en una "
            "GPU de 4 GB de VRAM. Para cada uno indica licencia, ventana de contexto "
            "y precio o coste de ejecucion, y di cuales pueden correr en local.\n\n"
            "Cita cada afirmacion con la URL de su fuente."
        )

    def gate(self, output: str) -> GateResult:
        urls = set(re.findall(r"https?://[^\s\)\]]+", output))
        presentes = [r for r in self.REQUISITOS if r in output.lower()]

        tiene_citas = len(urls) >= 3
        cobertura = len(presentes) / len(self.REQUISITOS)
        score = round(cobertura * (1.0 if tiene_citas else 0.5), 3)

        faltan = [r for r in self.REQUISITOS if r not in presentes]
        detalle = f"{len(urls)} fuentes citadas; cubre {len(presentes)}/{len(self.REQUISITOS)} requisitos"
        if faltan:
            detalle += f" (faltan: {', '.join(faltan)})"

        return GateResult(passed=tiene_citas and cobertura >= 0.75, score=score, detail=detalle)


@dataclass(slots=True)
class RepoTask(Task):
    """Puerta de ESCALAMIENTO. La misma tarea sobre repositorios de tamano
    creciente. No produce un porcentaje: produce una curva.

    Es la unica prueba que puede falsar la afirmacion central del proyecto.
    """

    repo_path: Path
    lineas: int
    id: str = "repo"
    title: str = "Modificacion acotada sobre repositorio"
    kind: str = "escalamiento"

    def __post_init__(self) -> None:
        self.id = f"repo-{self.lineas // 1000}k"
        self.title = f"Repositorio de ~{self.lineas // 1000}k lineas"

    def prompt(self) -> str:
        return (
            f"En el repositorio {self.repo_path.name}, localiza la funcion que valida "
            "las credenciales de entrada y anadele registro estructurado de los intentos "
            "fallidos, sin cambiar su firma publica.\n\n"
            "Devuelve solo el diff unificado."
        )

    def gate(self, output: str) -> GateResult:
        # Puerta minima verificable sin ejecutar el repositorio: el diff tiene que
        # ser un diff, tocar un solo archivo y no alterar la firma.
        if "---" not in output or "+++" not in output:
            return GateResult(False, 0.0, "la respuesta no es un diff unificado")
        archivos = set(re.findall(r"^\+\+\+ [ab]/(.+)$", output, re.MULTILINE))
        if len(archivos) != 1:
            return GateResult(False, 0.3, f"toca {len(archivos)} archivos; se esperaba 1")
        if re.search(r"^-\s*def ", output, re.MULTILINE):
            return GateResult(False, 0.5, "elimino o cambio una firma de funcion")
        return GateResult(True, 1.0, f"diff acotado a {archivos.pop()}")


def tareas_base() -> list[Task]:
    """Las tareas que corren sin configuracion adicional."""
    return [SnakeTask(), ResearchTask()]
