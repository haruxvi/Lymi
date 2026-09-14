"""Modo demo: la tuberia completa sin red y sin gastar dinero.

Existe para dos cosas: verificar que runner, ledger, puertas y recibo encajan de
punta a punta, y poder ENSENAR el sistema antes de tener credenciales.

Advertencia que el recibo estampa siempre: aqui las respuestas del modelo estan
guionadas. Los numeros son consistentes y reproducibles, pero **no demuestran
ahorro real**. Eso solo lo demuestra una corrida contra proveedores de verdad.
"""

from __future__ import annotations

from lymi.bench.strategies import BaselineAgent, LymiAgent, _trozos
from lymi.bench.tasks import SnakeTask
from lymi.providers.fake import ScriptedClient, ScriptedLocalClient, ScriptedTurn

#: Solucion correcta de Snake: pasa las tres comprobaciones de la puerta de verdad.
SNAKE_SOLUCION = '''```python
"""Snake sin dependencias externas, con la logica separada de la interfaz."""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass
class Estado:
    ancho: int
    alto: int
    serpiente: list[tuple[int, int]]
    comida: tuple[int, int] | None
    terminado: bool = False
    puntaje: int = 0


def _nueva_comida(ancho, alto, serpiente):
    libres = [(x, y) for x in range(ancho) for y in range(alto) if (x, y) not in serpiente]
    return random.choice(libres) if libres else None


def nuevo_juego(ancho: int = 20, alto: int = 15) -> Estado:
    cx, cy = ancho // 2, alto // 2
    serpiente = [(cx, cy), (cx - 1, cy)]
    return Estado(ancho, alto, serpiente, _nueva_comida(ancho, alto, serpiente))


def paso(estado: Estado, direccion: tuple[int, int]) -> Estado:
    if estado.terminado:
        return estado
    cx, cy = estado.serpiente[0]
    dx, dy = direccion
    nueva = (cx + dx, cy + dy)

    fuera = not (0 <= nueva[0] < estado.ancho and 0 <= nueva[1] < estado.alto)
    if fuera or nueva in estado.serpiente:
        estado.terminado = True
        return estado

    estado.serpiente.insert(0, nueva)
    if nueva == estado.comida:
        estado.puntaje += 1
        estado.comida = _nueva_comida(estado.ancho, estado.alto, estado.serpiente)
    else:
        estado.serpiente.pop()
    return estado


def main() -> None:
    estado = nuevo_juego()
    direccion = (1, 0)
    while not estado.terminado:
        for y in range(estado.alto):
            fila = "".join(
                "#" if (x, y) in estado.serpiente else "*" if (x, y) == estado.comida else "."
                for x in range(estado.ancho)
            )
            print(fila)
        print(f"puntaje: {estado.puntaje}")
        tecla = input("wasd> ").strip().lower()
        direccion = {"w": (0, -1), "s": (0, 1), "a": (-1, 0), "d": (1, 0)}.get(tecla, direccion)
        estado = paso(estado, direccion)
    print(f"fin. puntaje final: {estado.puntaje}")


if __name__ == "__main__":
    main()
```'''

#: Contexto que la tarea arrastra: convenciones del proyecto, ejemplos, guias de
#: estilo. Es lo que un agente ingenuo vuelca entero al modelo caro.
MATERIAL_DEMO = "CONVENCIONES DEL PROYECTO Y EJEMPLOS DE REFERENCIA.\n" + ("x" * 24_000)


def construir_demo() -> tuple[SnakeTask, BaselineAgent, LymiAgent]:
    """Arma la tarea y las dos estrategias con clientes guionados."""
    tarea = SnakeTask()
    tarea.material = MATERIAL_DEMO  # type: ignore[attr-defined]

    # Linea base: se traga los ~24k caracteres de material (~6.100 tokens) mas la
    # consigna, sin cache.
    base_remoto = ScriptedClient(
        [ScriptedTurn(SNAKE_SOLUCION, input_tokens=6_340, output_tokens=980, latency_ms=14_200)]
    )

    # lymi: seis trozos destilados en local (gratis) y una unica llamada remota
    # con el prefijo cacheado.
    # El numero de turnos se DERIVA del material: guionar una cifra fija dejaria
    # que el guion y la estrategia se desincronicen en silencio.
    n_trozos = len(_trozos(MATERIAL_DEMO))
    local = ScriptedLocalClient(
        turns=[
            ScriptedTurn(
                "Convenciones relevantes: dataclasses, sin dependencias externas.",
                input_tokens=1_040,
                output_tokens=48,
                latency_ms=1_900,
            )
            for _ in range(n_trozos)
        ]
    )
    lymi_remoto = ScriptedClient(
        [
            ScriptedTurn(
                SNAKE_SOLUCION,
                input_tokens=210,
                output_tokens=980,
                cache_read_tokens=340,
                cache_write_tokens=0,
                latency_ms=11_800,
            )
        ]
    )

    return tarea, BaselineAgent(base_remoto), LymiAgent(lymi_remoto, local)
