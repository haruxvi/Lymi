"""Motor de workflows: ejecucion, efectos, secretos, reintentos, validacion y plan."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import ClassVar

import httpx
import pytest
from pydantic import ValidationError

from lymi.flows.engine import EntradaError, ejecutar_flujo, preparar_inputs
from lymi.flows.nodes import PasoError, extraer_json
from lymi.flows.plan import planificar, resumir
from lymi.flows.schema import Workflow, cargar
from lymi.ledger import Billing, Ledger
from lymi.providers.base import Completion, Usage
from lymi.providers.fake import ScriptedClient, ScriptedLocalClient, ScriptedTurn

EJEMPLO = Path(__file__).parent.parent / "workflows" / "triage-de-leads.yml"


async def _sin_espera(_segundos: float) -> None:
    return None


def _sin_red(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"no deberia haber trafico de red: {request.url}")


@pytest.fixture
def ledger(tmp_path):
    led = Ledger(tmp_path / "flujos.sqlite3")
    yield led
    led.close()


def correr(flujo: Workflow, inputs: dict | None = None, *, handler=_sin_red, **opciones):
    async def _ir():
        transporte = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transporte, follow_redirects=False) as cliente:
            return await ejecutar_flujo(
                flujo, inputs or {}, http_client=cliente, espera=_sin_espera, **opciones
            )

    return asyncio.run(_ir())


def wf(**datos) -> Workflow:
    return Workflow.model_validate({"name": "prueba", "inputs": {}, "integrations": {}} | datos)


LEAD = [
    {"id": "extraer", "type": "llm", "tier": "local", "output": "json", "prompt": "Extrae: {{ inputs.correo }}"},
    {"id": "clasificar", "type": "llm", "tier": "local", "output": "json",
     "prompt": "Clasifica: {{ steps.extraer.output }}"},
    {"id": "ficha", "type": "transform",
     "set": {"empresa": "{{ steps.extraer.output.empresa }}", "score": "{{ steps.clasificar.output.score }}"}},
    {"id": "redactar", "type": "llm", "tier": "remote", "when": "steps.clasificar.output.score > 0.7",
     "prompt": "Redacta para {{ steps.ficha.output.empresa }}"},
]


def _local(score: float) -> ScriptedLocalClient:
    return ScriptedLocalClient(
        turns=[
            ScriptedTurn('```json\n{"empresa": "Acme", "presupuesto_usd": 9000}\n```', input_tokens=400, output_tokens=30),
            ScriptedTurn(f'{{"score": {score}}}', input_tokens=120, output_tokens=8),
        ]
    )


class Intermitente:
    """Cliente que falla las primeras N llamadas."""

    provider = "intermitente"
    model = "claude-opus-5"
    billing = Billing.API
    tier = "frontier"

    def __init__(self, fallos: int) -> None:
        self.fallos = fallos
        self.llamadas = 0

    def complete(self, messages, *, system=None, max_tokens=4096, cache_system=False) -> Completion:
        self.llamadas += 1
        if self.llamadas <= self.fallos:
            raise ConnectionError("red caida")
        return Completion(
            text="ok", usage=Usage(input_tokens=10, output_tokens=2), model=self.model,
            provider=self.provider, billing=self.billing, tier=self.tier, latency_ms=1,
        )


class TestEjecucion:
    def test_flujo_completo(self, ledger: Ledger) -> None:
        remoto = ScriptedClient([ScriptedTurn("Hola Acme, hablemos.", input_tokens=300, output_tokens=40)])
        flujo = wf(inputs={"correo": {"type": "string"}}, steps=LEAD)

        r = correr(flujo, {"correo": "Somos Acme"}, ledger=ledger, local=_local(0.9), remote=remoto)

        assert r.ok
        assert [e.status for e in r.pasos] == ["ok", "ok", "ok", "ok"]
        assert r.salidas["ficha"] == {"empresa": "Acme", "score": 0.9}
        assert r.salidas["redactar"] == "Hola Acme, hablemos."
        t = ledger.totals(r.run_id)
        assert t["n_calls"] == 3  # el transform no llama a nadie
        assert t["local_tokens"] == 558
        assert t["remote_tokens"] == 340

    def test_condicion_falsa_omite_y_no_gasta(self, ledger: Ledger) -> None:
        remoto = ScriptedClient([ScriptedTurn("no deberia usarse", input_tokens=999)])
        flujo = wf(inputs={"correo": {}}, steps=LEAD)

        r = correr(flujo, {"correo": "x"}, ledger=ledger, local=_local(0.2), remote=remoto)

        assert r.ok
        assert r.pasos[-1].status == "omitido"
        assert remoto.exhausted is False
        assert ledger.totals(r.run_id)["remote_tokens"] == 0

    def test_reintenta_fallos_transitorios(self, ledger: Ledger) -> None:
        cliente = Intermitente(fallos=2)
        flujo = wf(steps=[{"id": "a", "type": "llm", "tier": "remote", "prompt": "hola", "retries": 2}])
        r = correr(flujo, ledger=ledger, remote=cliente)
        assert r.ok
        assert r.pasos[0].intentos == 3

    def test_agota_reintentos_y_falla(self, ledger: Ledger) -> None:
        cliente = Intermitente(fallos=5)
        flujo = wf(steps=[{"id": "a", "type": "llm", "tier": "remote", "prompt": "hola", "retries": 1}])
        r = correr(flujo, ledger=ledger, remote=cliente)
        assert not r.ok
        assert r.pasos[0].status == "fallo"
        assert cliente.llamadas == 2
        assert ledger.totals(r.run_id)["status"] == "failed"

    def test_sin_proveedor_falla_sin_reintentar(self, ledger: Ledger) -> None:
        flujo = wf(steps=[{"id": "a", "type": "llm", "tier": "local", "prompt": "hola", "retries": 3}])
        r = correr(flujo, ledger=ledger)
        assert not r.ok
        assert r.pasos[0].intentos == 1
        assert "lymi setup" in r.pasos[0].detalle

    def test_json_con_texto_alrededor(self) -> None:
        assert extraer_json('Claro, aqui va:\n{"a": 1}\nSaludos') == {"a": 1}

    def test_sin_json_falla(self) -> None:
        with pytest.raises(PasoError):
            extraer_json("aqui no hay nada")


SLACK = {"slack": {"type": "http", "allow_hosts": ["hooks.slack.com"]}}


def _aviso(**extra) -> dict:
    return {
        "id": "avisar", "type": "http", "integration": "slack", "method": "POST",
        "url": "https://hooks.slack.com/services/${SLACK_PATH}", "body": {"text": "{{ inputs.msg }}"}, **extra,
    }


class TestEfectosYSecretos:
    def test_sin_aprobacion_no_sale_nada(self, ledger: Ledger) -> None:
        enviadas: list[httpx.Request] = []
        flujo = wf(inputs={"msg": {}}, integrations=SLACK, steps=[_aviso()])

        r = correr(
            flujo, {"msg": "hola"}, ledger=ledger, entorno={"SLACK_PATH": "T0/B0/x"},
            handler=lambda req: enviadas.append(req) or httpx.Response(200),
        )

        assert not r.ok
        assert r.pasos[0].status == "rechazado"
        assert enviadas == []

    def test_aprobado_envia_y_el_secreto_no_llega_al_ledger(self, ledger: Ledger) -> None:
        enviadas: list[httpx.Request] = []
        vistas: list[str] = []

        def aprobar(_paso: str, vista: str) -> bool:
            vistas.append(vista)
            return True

        flujo = wf(inputs={"msg": {}}, integrations=SLACK, steps=[_aviso()])
        r = correr(
            flujo, {"msg": "hola"}, ledger=ledger, aprobar=aprobar,
            entorno={"SLACK_PATH": "T0/B0/SECRETO123"},
            handler=lambda req: enviadas.append(req) or httpx.Response(200, json={"ok": True}),
        )

        assert r.ok
        assert str(enviadas[0].url) == "https://hooks.slack.com/services/T0/B0/SECRETO123"
        assert "SECRETO123" not in vistas[0]
        volcado = "".join(ledger.conn.iterdump())
        assert "SECRETO123" not in volcado
        assert "hooks.slack.com" in volcado

    def test_una_plantilla_no_puede_expandir_secretos(self, ledger: Ledger) -> None:
        enviadas: list[httpx.Request] = []
        flujo = wf(
            inputs={"item": {}},
            integrations={"api": {"type": "http", "allow_hosts": ["api.ejemplo.com"]}},
            steps=[{"id": "leer", "type": "http", "integration": "api",
                    "url": "https://api.ejemplo.com/items/{{ inputs.item }}?k=${CLAVE}"}],
        )

        r = correr(
            flujo, {"item": "${ROBADO}/../admin"}, ledger=ledger,
            entorno={"CLAVE": "k1", "ROBADO": "no-debe-salir"},
            handler=lambda req: enviadas.append(req) or httpx.Response(200, json={}),
        )

        assert r.ok
        url = str(enviadas[0].url)
        assert "no-debe-salir" not in url
        assert "/admin" not in url  # el valor va escapado: no cambia la ruta
        assert "k=k1" in url

    def test_host_fuera_de_la_lista_blanca(self, ledger: Ledger) -> None:
        flujo = wf(
            inputs={"dest": {}},
            integrations={"api": {"type": "http", "allow_hosts": ["api.ejemplo.com"]}},
            steps=[{"id": "leer", "type": "http", "integration": "api",
                    "url": "https://{{ inputs.dest }}/x", "retries": 2}],
        )
        r = correr(flujo, {"dest": "evil.com"}, ledger=ledger)
        assert not r.ok
        assert r.pasos[0].intentos == 1
        assert "allow_hosts" in r.pasos[0].detalle

    def test_http_plano_solo_hacia_loopback(self, ledger: Ledger) -> None:
        flujo = wf(
            integrations={"api": {"type": "http", "allow_hosts": ["api.ejemplo.com"]}},
            steps=[{"id": "leer", "type": "http", "integration": "api", "url": "http://api.ejemplo.com/x"}],
        )
        r = correr(flujo, ledger=ledger)
        assert not r.ok
        assert "https" in r.pasos[0].detalle


class TestValidacion:
    def test_efectos_no_se_reintentan(self) -> None:
        with pytest.raises(ValidationError, match="dos veces"):
            wf(integrations=SLACK, inputs={"msg": {}}, steps=[_aviso(retries=2)])

    def test_secretos_fuera_de_la_url_se_rechazan(self) -> None:
        with pytest.raises(ValidationError, match="solo se admite"):
            wf(steps=[{"id": "a", "type": "llm", "tier": "remote", "prompt": "usa ${API_KEY}"}])

    def test_leer_un_paso_futuro(self) -> None:
        with pytest.raises(ValidationError, match="todavia no se ha ejecutado"):
            wf(steps=[
                {"id": "a", "type": "llm", "tier": "local", "prompt": "{{ steps.b.output }}"},
                {"id": "b", "type": "transform", "set": {"x": 1}},
            ])

    def test_input_no_declarado(self) -> None:
        with pytest.raises(ValidationError, match="no esta declarado"):
            wf(steps=[{"id": "a", "type": "transform", "set": {"x": "{{ inputs.fantasma }}"}}])

    def test_integracion_inexistente(self) -> None:
        with pytest.raises(ValidationError, match="no declarada"):
            wf(steps=[{"id": "a", "type": "tool", "integration": "crm", "tool": "buscar"}])

    def test_integracion_de_otro_tipo(self) -> None:
        with pytest.raises(ValidationError, match="se esperaba mcp"):
            wf(integrations=SLACK, steps=[{"id": "a", "type": "tool", "integration": "slack", "tool": "x"}])

    def test_condicion_con_llamadas(self) -> None:
        with pytest.raises(ValidationError, match="condicion invalida"):
            wf(steps=[{"id": "a", "type": "transform", "set": {}, "when": "len(steps) > 0"}])

    def test_campos_desconocidos(self) -> None:
        with pytest.raises(ValidationError):
            wf(steps=[{"id": "a", "type": "transform", "set": {}, "sett": {}}])

    def test_el_ejemplo_del_repo_es_valido(self) -> None:
        flujo = cargar(EJEMPLO)
        assert [p.id for p in flujo.steps] == ["extraer", "clasificar", "ficha", "redactar", "avisar"]


class TestEntradas:
    INPUTS: ClassVar[dict] = {
        "n": {"type": "number"},
        "activo": {"type": "boolean", "required": False, "default": True},
        "datos": {"type": "object", "required": False},
    }

    def _flujo(self) -> Workflow:
        return wf(inputs=self.INPUTS, steps=[{"id": "a", "type": "transform", "set": {}}])

    def test_convierte_tipos(self) -> None:
        valores = preparar_inputs(self._flujo(), {"n": "42", "datos": '{"a": 1}'})
        assert valores == {"n": 42, "activo": True, "datos": {"a": 1}}

    def test_falta_requerido(self) -> None:
        with pytest.raises(EntradaError, match="requerida"):
            preparar_inputs(self._flujo(), {})

    def test_entrada_desconocida(self) -> None:
        with pytest.raises(EntradaError, match="desconocidas"):
            preparar_inputs(self._flujo(), {"n": 1, "intruso": 2})

    def test_numero_invalido(self) -> None:
        with pytest.raises(EntradaError):
            preparar_inputs(self._flujo(), {"n": "cuarenta"})


class TestPlan:
    def test_plan_del_ejemplo(self) -> None:
        filas = planificar(cargar(EJEMPLO))
        resumen = resumir(filas)
        assert resumen.total == 5
        assert resumen.locales == 2
        assert resumen.remotos == 1
        assert resumen.con_efectos == 1
        assert resumen.condicionales == 2
        assert filas[-1].efectos
        assert filas[-1].destino == "POST hooks.slack.com"
