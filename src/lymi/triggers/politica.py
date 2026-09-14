"""Politica de ejecucion desatendida.

Un workflow que corre sin nadie delante -- programado o disparado por un webhook
-- no puede pedir aprobacion en el momento. Quien lo configura autoriza de
antemano, por nombre, cada paso con efectos que puede ejecutar. Todo lo demas se
rechaza.

Vive en un solo modulo a proposito: la agenda y los webhooks aplican la misma
regla, y dos copias de una regla de seguridad terminan divergiendo.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from lymi.flows.schema import Workflow


def validar_preaprobados(flujo: Workflow, aprobados: Iterable[str]) -> frozenset[str]:
    """Comprueba que cada paso preaprobado existe y tiene efectos."""
    pasos = {p.id: p for p in flujo.steps}
    autorizados = frozenset(aprobados)
    for paso_id in sorted(autorizados):
        if paso_id not in pasos:
            raise ValueError(f"{paso_id!r} no es un paso de {flujo.name}")
        if not pasos[paso_id].efectos:
            raise ValueError(f"{paso_id!r} no tiene efectos: no hace falta preaprobarlo")
    return autorizados


def efectos_sin_autorizar(flujo: Workflow, aprobados: frozenset[str]) -> list[str]:
    """Pasos con efectos que se rechazaran si llegan a ejecutarse sin nadie delante."""
    return [p.id for p in flujo.steps if p.efectos and p.id not in aprobados]


def aprobador_desatendido(aprobados: frozenset[str]) -> Callable[[str, str], bool]:
    """Aprueba solo los pasos autorizados de antemano; rechaza todo lo demas."""

    def aprobar(paso_id: str, _vista: str) -> bool:
        return paso_id in aprobados

    return aprobar
