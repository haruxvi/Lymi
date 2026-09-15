"""Interruptor de parada y presupuestos por tarea.

La parada es un archivo, a proposito: la ve cualquier proceso de lymi (la
terminal, `lymi serve`, la interfaz) sin coordinacion, sobrevive a un proceso
colgado y se puede crear a mano. Se consulta antes de cada llamada y de cada paso.

El presupuesto se consulta ANTES de cada llamada con lo ya gastado: lymi no puede
saber cuantos tokens costara la proxima, asi que una sola llamada puede pasar el
tope. Lo que garantiza es que no empieza otra despues de alcanzarlo.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class Detenido(RuntimeError):
    """lymi esta detenido: no se hacen mas llamadas ni pasos."""


class PresupuestoAgotado(RuntimeError):
    """La tarea alcanzo su tope de tokens o de llamadas."""


def archivo_parada() -> Path:
    return Path(os.environ.get("LYMI_PARADA", "runs/PARAR"))


def detener(motivo: str = "") -> Path:
    ruta = archivo_parada()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(motivo or "detenido", encoding="utf-8")
    return ruta


def reanudar() -> bool:
    """Quita la parada. Devuelve False si no estaba detenido."""
    try:
        archivo_parada().unlink()
    except FileNotFoundError:
        return False
    return True


def detenido() -> bool:
    return archivo_parada().exists()


def verificar_parada() -> None:
    if detenido():
        raise Detenido("lymi esta detenido; `lymi resume` para reanudar")


@dataclass(slots=True)
class Presupuesto:
    tokens_remotos: int | None = None
    llamadas: int | None = None
    usados_tokens: int = 0
    usadas_llamadas: int = 0

    def __post_init__(self) -> None:
        for nombre in ("tokens_remotos", "llamadas"):
            valor = getattr(self, nombre)
            if valor is not None and valor <= 0:
                raise ValueError(f"{nombre} debe ser mayor que cero")

    def verificar(self) -> None:
        if self.tokens_remotos is not None and self.usados_tokens >= self.tokens_remotos:
            raise PresupuestoAgotado(
                f"se alcanzo el tope de {self.tokens_remotos:,} tokens remotos ({self.usados_tokens:,} usados)"
            )
        if self.llamadas is not None and self.usadas_llamadas >= self.llamadas:
            raise PresupuestoAgotado(f"se alcanzo el tope de {self.llamadas} llamadas")

    def sumar(self, tokens_remotos: int) -> None:
        self.usadas_llamadas += 1
        self.usados_tokens += tokens_remotos
