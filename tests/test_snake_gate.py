"""Pruebas de la puerta de Snake.

La puerta decide si una corrida "paso". Si castiga una solucion correcta, el
recibo compara contra una linea base de paja sin que nadie lo note: eso paso en
la primera medicion real, con un estado de dataclass congelado.
"""

from __future__ import annotations

import pytest

from lymi.bench.tasks import SnakeTask

_MUTABLE = '''
from dataclasses import dataclass

@dataclass
class Estado:
    ancho: int
    alto: int
    serpiente: list
    comida: tuple
    terminado: bool = False
    puntaje: int = 0

def nuevo_juego(ancho, alto):
    cx, cy = ancho // 2, alto // 2
    return Estado(ancho, alto, [(cx, cy), (cx - 1, cy)], (0, 0))

def paso(estado, direccion):
    if estado.terminado:
        return estado
    cabeza = (estado.serpiente[0][0] + direccion[0], estado.serpiente[0][1] + direccion[1])
    if not (0 <= cabeza[0] < estado.ancho and 0 <= cabeza[1] < estado.alto) or cabeza in estado.serpiente:
        estado.terminado = True
        return estado
    estado.serpiente.insert(0, cabeza)
    if cabeza == estado.comida:
        estado.puntaje += 1
        estado.comida = (0, 0)
    else:
        estado.serpiente.pop()
    return estado

def main():
    pass

if __name__ == "__main__":
    main()
'''

#: Mismo comportamiento con estado inmutable: la forma que escribio la linea base
#: en la primera corrida real y que la puerta vieja reprobaba.
_CONGELADO = '''
from dataclasses import dataclass, replace

@dataclass(frozen=True)
class Estado:
    ancho: int
    alto: int
    serpiente: tuple
    comida: tuple
    terminado: bool = False
    puntaje: int = 0

def nuevo_juego(ancho, alto):
    cx, cy = ancho // 2, alto // 2
    return Estado(ancho, alto, ((cx, cy), (cx - 1, cy)), (0, 0))

def paso(estado, direccion):
    if estado.terminado:
        return estado
    cabeza = (estado.serpiente[0][0] + direccion[0], estado.serpiente[0][1] + direccion[1])
    if not (0 <= cabeza[0] < estado.ancho and 0 <= cabeza[1] < estado.alto) or cabeza in estado.serpiente:
        return replace(estado, terminado=True)
    if cabeza == estado.comida:
        return replace(estado, serpiente=(cabeza, *estado.serpiente), puntaje=estado.puntaje + 1, comida=(0, 0))
    return replace(estado, serpiente=(cabeza, *estado.serpiente[:-1]))

def main():
    pass

if __name__ == "__main__":
    main()
'''

_NAMEDTUPLE = '''
from typing import NamedTuple

class Estado(NamedTuple):
    ancho: int
    alto: int
    serpiente: tuple
    comida: tuple
    terminado: bool = False
    puntaje: int = 0

def nuevo_juego(ancho, alto):
    cx, cy = ancho // 2, alto // 2
    return Estado(ancho, alto, ((cx, cy), (cx - 1, cy)), (0, 0))

def paso(estado, direccion):
    if estado.terminado:
        return estado
    cabeza = (estado.serpiente[0][0] + direccion[0], estado.serpiente[0][1] + direccion[1])
    if not (0 <= cabeza[0] < estado.ancho and 0 <= cabeza[1] < estado.alto) or cabeza in estado.serpiente:
        return estado._replace(terminado=True)
    if cabeza == estado.comida:
        return estado._replace(serpiente=(cabeza, *estado.serpiente), puntaje=estado.puntaje + 1)
    return estado._replace(serpiente=(cabeza, *estado.serpiente[:-1]))
'''


def _bloque(codigo: str) -> str:
    return f"```python\n{codigo}\n```"


class TestPuertaJusta:
    @pytest.mark.parametrize(
        "codigo",
        [_MUTABLE, _CONGELADO, _NAMEDTUPLE],
        ids=["mutable", "dataclass-congelado", "namedtuple"],
    )
    def test_acepta_cualquier_diseno_que_cumpla_el_enunciado(self, codigo: str) -> None:
        r = SnakeTask().gate(_bloque(codigo))
        assert r.passed, r.detail

    def test_regresion_estado_congelado_no_revienta_la_puerta(self) -> None:
        # Antes: "dataclasses.FrozenInstanceError: cannot assign to field 'comida'".
        r = SnakeTask().gate(_bloque(_CONGELADO))
        assert "FrozenInstanceError" not in r.detail


class TestPuertaEstricta:
    def test_reprueba_si_comer_no_hace_crecer(self) -> None:
        roto = _MUTABLE.replace("estado.serpiente.insert(0, cabeza)\n", "estado.serpiente.insert(0, cabeza)\n    estado.serpiente.pop()\n")
        r = SnakeTask().gate(_bloque(roto))
        assert not r.passed
        assert "crecer" in r.detail

    def test_reprueba_si_el_muro_no_termina_el_juego(self) -> None:
        roto = _MUTABLE.replace("estado.terminado = True", "pass")
        r = SnakeTask().gate(_bloque(roto))
        assert not r.passed

    def test_respuesta_sin_codigo(self) -> None:
        assert not SnakeTask().gate("").passed

    def test_codigo_que_revienta_al_importar(self) -> None:
        r = SnakeTask().gate(_bloque("raise SystemExit(3)"))
        assert not r.passed
        assert "fallo al ejecutarse" in r.detail
