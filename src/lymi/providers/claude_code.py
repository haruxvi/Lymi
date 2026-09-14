"""Tu suscripcion de Claude Code como proveedor.

Dos formas de usarla, y la diferencia importa:

- `ClaudeCodeClient` (nivel mensaje): invoca `claude -p` con el prompt de sistema
  reemplazado, las herramientas apagadas y MCP ignorado. Con eso deja de ser un
  agente y pasa a ser una llamada limpia cuyo contexto arma lymi -- que es la
  unica forma de que el ahorro sea demostrable.
- `ClaudeCodeBackend` (nivel tarea): delega la tarea entera al harness de Claude
  Code. Comodo, pero el contexto lo maneja el.

Con la sesion de `/login` el modo de facturacion es `subscription`: cuota fija,
sin costo marginal. El ledger lo mantiene separado del modo `api` porque los
dolares no son comparables; la moneda aqui es tu ventana de uso. Si hay clave de
API en el entorno, el CLI la usa y el modo pasa a ser `api`.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from lymi.ledger import Billing
from lymi.providers.base import Completion, Message, Usage

TIMEOUT_MENSAJE = 300
TIMEOUT_TAREA = 900

#: Herramientas que se apagan para convertir `claude -p` en una llamada limpia.
#: Si alguna quedara viva, el harness podria leer archivos o buscar en la web y
#: el consumo dejaria de reflejar el contexto que lymi decidio enviar.
HERRAMIENTAS_APAGADAS = (
    "Bash", "Read", "Write", "Edit", "NotebookEdit", "Glob", "Grep",
    "WebFetch", "WebSearch", "Task", "TodoWrite",
)


class ClaudeCodeUnavailableError(RuntimeError):
    """El CLI de Claude Code no esta instalado o no es ejecutable."""


class ClaudeCodeAuthError(RuntimeError):
    """El CLI esta instalado pero la sesion no autentica."""


def _leer_usage(payload: dict[str, Any]) -> Usage:
    """Lee el consumo del JSON del CLI de forma defensiva.

    Preferimos reportar ceros -- que el reporte marca como 'sin telemetria' --
    antes que reventar la corrida o, peor, inventar un numero.
    """
    u = payload.get("usage")
    if not isinstance(u, dict):
        return Usage()
    return Usage(
        input_tokens=int(u.get("input_tokens", 0) or 0),
        output_tokens=int(u.get("output_tokens", 0) or 0),
        cache_read_tokens=int(u.get("cache_read_input_tokens", 0) or 0),
        cache_write_tokens=int(u.get("cache_creation_input_tokens", 0) or 0),
    )


def _modelo(payload: dict[str, Any], respaldo: str) -> str:
    """El id real del modelo que respondio.

    `model` suele venir vacio y `modelUsage` trae el id con fecha. Sin esto el
    ledger guardaba el alias ("opus"), que no tiene tarifa ni dice que version
    corrio. Si respondieron varios modelos, quedan todos.
    """
    if payload.get("model"):
        return str(payload["model"])
    usos = payload.get("modelUsage")
    if isinstance(usos, dict) and usos:
        return ",".join(sorted(str(k) for k in usos))
    return respaldo


def _facturacion(entorno: Mapping[str, str] | None = None) -> Billing:
    """Suscripcion o clave de API, segun con que autentica el CLI.

    El JSON no sirve para decidirlo: `total_cost_usd` trae valor tambien con
    suscripcion, porque es el costo equivalente en API (medido el 2026-09-13
    con sesion pro y sin clave: 0.0559 USD por un "di: ok"). Lo que decide es el
    entorno: con clave, `claude -p` la usa; sin clave, usa la sesion de /login.
    """
    env = os.environ if entorno is None else entorno
    if env.get("ANTHROPIC_API_KEY") or env.get("ANTHROPIC_AUTH_TOKEN"):
        return Billing.API
    return Billing.SUBSCRIPTION


def _revisar_error(payload: dict[str, Any]) -> None:
    """Levanta si el CLI reporto un fallo.

    `is_error` es la unica senal fiable: una llamada fallida puede venir con
    `subtype: "success"` y codigo de salida 0. Confiar en esos dos registraria
    fallos como exitos con 0 tokens y corromperia el ledger en silencio.
    """
    if not payload.get("is_error"):
        return
    detalle = str(payload.get("result") or payload.get("terminal_reason") or "sin detalle")
    if "authenticate" in detalle.lower() or "oauth" in detalle.lower():
        raise ClaudeCodeAuthError(
            f"{detalle}. Abre una terminal, ejecuta `claude` y usa /login."
        )
    raise RuntimeError(f"claude -p fallo: {detalle[:400]}")


def _resolver_binario(binario: str) -> str:
    ruta = shutil.which(binario)
    if ruta is None:
        raise ClaudeCodeUnavailableError(
            f"No se encontro {binario!r} en PATH. Instala Claude Code o usa el "
            "modo api con una clave."
        )
    return ruta


def _ejecutar(cmd: list[str], *, timeout: int, cwd: Path | None = None) -> tuple[dict, int]:
    """Corre el CLI y devuelve (payload, latencia_ms)."""
    inicio = time.perf_counter()
    proc = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd, check=False
    )
    latencia = int((time.perf_counter() - inicio) * 1000)

    if not proc.stdout.strip():
        err = (proc.stderr or "").strip()[:400] or f"codigo de salida {proc.returncode}"
        raise RuntimeError(f"claude no devolvio salida: {err}")

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"claude devolvio algo que no es JSON: {proc.stdout[:200]}") from exc

    _revisar_error(payload)
    return payload, latencia


class ClaudeCodeClient:
    """Proveedor a nivel mensaje sobre la suscripcion."""

    provider = "claude-code"
    tier = "frontier"

    def __init__(
        self,
        model: str = "opus",
        *,
        binary: str = "claude",
        timeout: int = TIMEOUT_MENSAJE,
    ) -> None:
        self.binary = _resolver_binario(binary)
        self.model = model
        self.timeout = timeout
        self.billing = _facturacion()

    def _cmd(self, prompt: str, system: str | None) -> list[str]:
        cmd = [
            self.binary, "-p", prompt,
            "--output-format", "json",
            "--model", self.model,
            # Sin herramientas, sin MCP, sin skills: una llamada, no un agente.
            "--disallowedTools", *HERRAMIENTAS_APAGADAS,
            "--strict-mcp-config",
            "--disable-slash-commands",
            "--no-session-persistence",
        ]
        if system is not None:
            # Reemplaza el prompt de sistema por completo; no lo anade.
            cmd += ["--system-prompt", system]
        return cmd

    def complete(
        self,
        messages: list[Message],
        *,
        system: str | None = None,
        max_tokens: int = 16000,
        cache_system: bool = False,
    ) -> Completion:
        # El CLI toma un prompt unico, no una lista de turnos: el historial se
        # aplana con marcas de rol para que el modelo lo distinga.
        if len(messages) == 1:
            prompt = messages[0].content
        else:
            prompt = "\n\n".join(f"[{m.role}]\n{m.content}" for m in messages)

        payload, latencia = _ejecutar(self._cmd(prompt, system), timeout=self.timeout)

        return Completion(
            text=str(payload.get("result", "")),
            usage=_leer_usage(payload),
            model=_modelo(payload, self.model),
            provider=self.provider,
            billing=self.billing,
            tier=self.tier,
            latency_ms=latencia,
            stop_reason=payload.get("stop_reason"),
            raw=payload,
        )


class ClaudeCodeBackend:
    """Delega una tarea completa al harness de Claude Code, con herramientas.

    Aqui lymi NO controla el contexto: el ahorro solo puede venir de entregarle
    menos trabajo, no de recortar el prompt.
    """

    provider = "claude-code"
    tier = "frontier"

    def __init__(
        self,
        binary: str = "claude",
        *,
        model: str | None = None,
        timeout: int = TIMEOUT_TAREA,
    ) -> None:
        self.binary = _resolver_binario(binary)
        self.model = model
        self.timeout = timeout
        self.billing = _facturacion()

    def run_task(self, prompt: str, *, cwd: str | None = None) -> Completion:
        cmd = [self.binary, "-p", prompt, "--output-format", "json"]
        if self.model:
            cmd += ["--model", self.model]

        workdir = Path(cwd).resolve() if cwd else None
        if workdir is not None and not workdir.is_dir():
            raise NotADirectoryError(f"cwd invalido: {workdir}")

        payload, latencia = _ejecutar(cmd, timeout=self.timeout, cwd=workdir)

        return Completion(
            text=str(payload.get("result", "")),
            usage=_leer_usage(payload),
            model=_modelo(payload, self.model or "claude-code"),
            provider=self.provider,
            billing=self.billing,
            tier=self.tier,
            latency_ms=latencia,
            stop_reason=payload.get("stop_reason"),
            raw=payload,
        )


def disponible(binary: str = "claude") -> bool:
    return shutil.which(binary) is not None
