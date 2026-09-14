"""Diagnostico de proveedores.

Responde una sola pregunta: con lo que hay instalado ahora mismo, ¿que puede
correr lymi y que falta para lo demas? Cada carencia viene con el comando exacto
que la soluciona.

Regla: nunca se reporta un proveedor como listo sin haberlo probado. Que el
binario exista no significa que autentique -- una sesion caducada se ve igual que
una sana desde fuera.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import httpx

from lymi.providers.local import DEFAULT_MODEL, DEFAULT_URL, NonLocalEndpointError, assert_loopback


class Estado(StrEnum):
    OK = "ok"
    FALTA = "falta"
    ERROR = "error"


SIMBOLO = {Estado.OK: "+", Estado.FALTA: "-", Estado.ERROR: "!"}


@dataclass(frozen=True, slots=True)
class Chequeo:
    nombre: str
    estado: Estado
    detalle: str
    arreglo: str | None = None
    """El comando exacto que lo soluciona, si lo hay."""


@dataclass(frozen=True, slots=True)
class Diagnostico:
    chequeos: list[Chequeo]

    @property
    def tier_local(self) -> bool:
        """Hay modelo local utilizable."""
        return all(c.estado is Estado.OK for c in self.chequeos if c.nombre.startswith("ollama"))

    @property
    def tier_remoto(self) -> bool:
        """Hay al menos un proveedor remoto utilizable."""
        return any(
            c.estado is Estado.OK
            for c in self.chequeos
            if c.nombre in {"claude code", "anthropic api", "openai api"}
        )

    @property
    def puede_medir(self) -> bool:
        """Hay lo minimo para una corrida real: un remoto que medir."""
        return self.tier_remoto


def _rutas_conocidas() -> tuple[Path, ...]:
    """Donde deja el binario cada instalador oficial.

    Una terminal abierta antes de instalar Ollama arrastra el PATH viejo: el
    binario existe y el servidor responde, pero `which` no lo ve. Buscar en las
    rutas de instalacion evita mandar al usuario a reinstalar algo que ya tiene.
    """
    candidatos: list[Path] = []
    for var, cola in (("LOCALAPPDATA", "Programs/Ollama/ollama.exe"), ("PROGRAMFILES", "Ollama/ollama.exe")):
        raiz = os.environ.get(var)
        if raiz:
            candidatos.append(Path(raiz) / cola)
    candidatos += [
        Path("/usr/local/bin/ollama"),
        Path("/opt/homebrew/bin/ollama"),
        Path.home() / ".local/bin/ollama",
    ]
    return tuple(candidatos)


def ruta_ollama() -> str | None:
    """El binario de ollama, este o no en PATH."""
    en_path = shutil.which("ollama")
    if en_path:
        return en_path
    for candidato in _rutas_conocidas():
        try:
            if candidato.is_file():
                return str(candidato)
        except OSError:
            continue
    return None


def _chequear_ollama_instalado(ruta: str | None = None, *, servidor_vivo: bool = False) -> Chequeo:
    ruta = ruta if ruta is not None else ruta_ollama()
    if ruta and shutil.which("ollama"):
        return Chequeo("ollama binario", Estado.OK, "instalado")
    if ruta:
        return Chequeo(
            "ollama binario",
            Estado.OK,
            f"instalado en {ruta} (no esta en PATH: reinicia la terminal)",
        )
    if servidor_vivo:
        # El servidor responde: el tier local funciona aunque el binario no
        # aparezca (servicio, contenedor, otra maquina de la misma sesion).
        return Chequeo("ollama binario", Estado.OK, "no encontrado, pero el servidor responde")
    return Chequeo(
        "ollama binario",
        Estado.FALTA,
        "no esta en PATH",
        "winget install Ollama.Ollama",
    )


def _chequear_ollama_servidor(url: str) -> tuple[Chequeo, list[str]]:
    """Devuelve el chequeo y los modelos disponibles."""
    try:
        assert_loopback(url, allow_remote=os.getenv("LYMI_ALLOW_REMOTE_LOCAL") == "1")
    except NonLocalEndpointError as exc:
        # Falla ruidosamente: un tier "local" apuntando afuera es una fuga.
        return Chequeo("ollama servidor", Estado.ERROR, str(exc)), []

    try:
        resp = httpx.get(f"{url.rstrip('/')}/api/tags", timeout=3.0)
        resp.raise_for_status()
        modelos = [m.get("name", "") for m in resp.json().get("models", [])]
    except (httpx.HTTPError, ValueError):
        return (
            Chequeo("ollama servidor", Estado.FALTA, f"no responde en {url}", "ollama serve"),
            [],
        )
    if not modelos:
        return Chequeo("ollama servidor", Estado.OK, f"sin modelos en {url}"), []
    return Chequeo("ollama servidor", Estado.OK, f"{len(modelos)} modelos en {url}"), modelos


def _chequear_modelo_local(modelo: str, modelos: list[str]) -> Chequeo:
    if not modelos:
        return Chequeo("ollama modelo", Estado.FALTA, "sin servidor", f"ollama pull {modelo}")
    # Ollama etiqueta como "qwen3:4b"; aceptamos coincidencia por prefijo.
    base = modelo.split(":")[0]
    encontrados = [m for m in modelos if m == modelo or m.split(":")[0] == base]
    if encontrados:
        return Chequeo("ollama modelo", Estado.OK, encontrados[0])
    return Chequeo(
        "ollama modelo",
        Estado.FALTA,
        f"{modelo} no descargado (hay: {', '.join(modelos[:3]) or 'ninguno'})",
        f"ollama pull {modelo}",
    )


def _chequear_claude_code(probar: bool) -> Chequeo:
    from lymi.providers import claude_code

    if not claude_code.disponible():
        return Chequeo(
            "claude code",
            Estado.FALTA,
            "el CLI no esta en PATH",
            "https://claude.com/code",
        )
    if not probar:
        return Chequeo("claude code", Estado.OK, "instalado (sin probar autenticacion)")

    # Que el binario exista no dice nada: una sesion caducada se ve igual desde
    # fuera. La unica comprobacion honesta es una llamada minima.
    try:
        cliente = claude_code.ClaudeCodeClient(model="haiku", timeout=90)
        from lymi.providers.base import Message

        r = cliente.complete([Message("user", "di: ok")], system="Responde solo lo pedido.")
    except claude_code.ClaudeCodeAuthError as exc:
        return Chequeo("claude code", Estado.ERROR, str(exc)[:110], "claude  (y luego /login)")
    except Exception as exc:  # noqa: BLE001 - cualquier fallo aqui es "no utilizable"
        return Chequeo("claude code", Estado.ERROR, f"{type(exc).__name__}: {exc}"[:110])

    gasto = r.usage.input_tokens + r.usage.output_tokens
    return Chequeo("claude code", Estado.OK, f"suscripcion viva ({gasto} tokens en la prueba)")


def _chequear_clave(nombre: str, var: str) -> Chequeo:
    if os.getenv(var):
        return Chequeo(nombre, Estado.OK, f"{var} definida")
    return Chequeo(nombre, Estado.FALTA, f"{var} sin definir", "copia .env.example a .env")


def diagnosticar(
    *,
    url_local: str | None = None,
    modelo_local: str | None = None,
    probar_claude: bool = True,
) -> Diagnostico:
    """Revisa todos los proveedores y devuelve que hay y que falta."""
    url = url_local or os.getenv("LYMI_OLLAMA_URL", DEFAULT_URL)
    modelo = modelo_local or os.getenv("LYMI_LOCAL_MODEL", DEFAULT_MODEL)

    # El servidor se consulta siempre: lo que decide si hay tier local es que
    # responda, no que el binario este en PATH.
    servidor, modelos = _chequear_ollama_servidor(url)
    binario = _chequear_ollama_instalado(servidor_vivo=servidor.estado is Estado.OK)

    return Diagnostico(
        [
            binario,
            servidor,
            _chequear_modelo_local(modelo, modelos),
            _chequear_claude_code(probar_claude),
            _chequear_clave("anthropic api", "ANTHROPIC_API_KEY"),
            _chequear_clave("openai api", "OPENAI_API_KEY"),
        ]
    )
