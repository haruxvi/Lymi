"""Las estrategias que el banco de pruebas compara.

`BaselineAgent` es la LINEA BASE PUBLICA. Vive aqui, en el repositorio, y es
ejecutable por cualquiera. Comparar contra una linea base secreta es la
definicion de humo, asi que esta es deliberadamente honesta: hace lo que hace un
agente ingenuo bien escrito, no un hombre de paja.
"""

from __future__ import annotations

from lymi.bench.runner import Recorder
from lymi.bench.tasks import Task
from lymi.ledger import Billing
from lymi.providers.base import LLMClient, Message

SISTEMA = (
    "Eres un agente de programacion e investigacion. Respondes de forma directa "
    "y completa, sin preambulos."
)


class BaselineAgent:
    """Agente ingenuo: todo el material al modelo caro, sin cache, de una vez.

    Es lo que hace la mayoria de los frameworks por defecto, y es contra esto
    que se mide el ahorro. No se le pone freno a proposito.
    """

    name = "baseline"

    def __init__(self, remote: LLMClient) -> None:
        self.remote = remote
        # El modo de la corrida es el de quien paga: fijarlo a mano registraba
        # corridas de suscripcion como api.
        self.billing: Billing = getattr(remote, "billing", Billing.API)

    def solve(self, task: Task, rec: Recorder) -> str:
        material = _material_bruto(task)
        mensajes = [Message("user", f"{material}\n\n{task.prompt()}")]
        # Sin cache_system: el prefijo se paga entero en cada turno.
        return rec.call(self.remote, mensajes, purpose="responder", system=SISTEMA).text


class LymiAgent:
    """Destila en local, razona en remoto, cachea el prefijo estable.

    Las tres palancas de las fases 2 y 3 en su forma minima: el volumen alto lo
    absorbe la maquina del usuario y al modelo caro solo llega material destilado.

    Sin tier local queda solo la palanca de cache. El nombre de la variante lo
    declara, para que el ledger nunca atribuya a lymi un ahorro que vino de una
    configuracion distinta a la que dice su etiqueta.
    """

    def __init__(self, remote: LLMClient, local: LLMClient | None = None) -> None:
        self.remote = remote
        self.local = local
        self.billing: Billing = getattr(remote, "billing", Billing.API)
        self.name = "lymi-local" if local is not None else "lymi-cache"

    def solve(self, task: Task, rec: Recorder) -> str:
        material = _material_bruto(task)

        # 1. El material crudo nunca toca el modelo caro: lo comprime el tier local.
        #    Sin tier local no hay destilacion posible y el material pasa entero.
        if self.local is None:
            return rec.call(
                self.remote,
                [Message("user", f"{material}\n\n{task.prompt()}")],
                purpose="responder",
                system=SISTEMA,
                cache_system=True,
            ).text

        fichas: list[str] = []
        for trozo in _trozos(material):
            ficha = rec.call(
                self.local,
                [Message("user", f"Extrae solo lo relevante para:\n{task.prompt()}\n\n{trozo}")],
                purpose="destilar",
            )
            fichas.append(ficha.text)

        # 2. Una sola llamada remota, con el prefijo estable cacheado.
        destilado = "\n\n".join(fichas)
        return rec.call(
            self.remote,
            [Message("user", f"{destilado}\n\n{task.prompt()}")],
            purpose="responder",
            system=SISTEMA,
            cache_system=True,
        ).text


def _material_bruto(task: Task) -> str:
    """El contexto que la tarea arrastra antes de cualquier optimizacion.

    En la version real esto viene del indice simbolico o de las fuentes web. En
    el modo demo lo aporta el guion, y por eso el recibo se marca como demo.
    """
    return getattr(task, "material", "")


def _trozos(material: str, tamano: int = 4000) -> list[str]:
    if not material:
        return []
    return [material[i : i + tamano] for i in range(0, len(material), tamano)] or [material]
