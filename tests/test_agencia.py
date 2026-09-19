"""Agencia: delegacion sincronica y asincronica, ayudantes, mensajes, topes y seguridad.

El modelo es un guion por agente: las pruebas ejercitan el motor, no la suerte
de un modelo. La corrida real con el modelo local se hace aparte.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from lymi.agencia import AgenciaError, arbol, cargar_agencia, correr_agencia, enrutar
from lymi.agencia.definicion import Agencia
from lymi.bench.runner import Recorder
from lymi.cli import app
from lymi.control import detener
from lymi.flows.engine import ejecutar_flujo
from lymi.flows.plan import planificar
from lymi.flows.schema import Workflow
from lymi.ledger import Billing, Ledger
from lymi.providers.base import Completion, Usage

RAIZ_PROYECTO = Path(__file__).resolve().parent.parent


class Guion:
    """Modelo falso: responde segun el agente (primera linea del sistema) y su turno."""

    provider = "guion"
    model = "guion-1"
    billing = Billing.LOCAL
    tier = "local"

    def __init__(self, respuestas: dict[str, list], demoras: dict[str, float] | None = None) -> None:
        self.respuestas = {k: list(v) for k, v in respuestas.items()}
        self.demoras = demoras or {}
        self.recibidos: list[tuple[str, str]] = []
        self._candado = threading.Lock()

    def complete(self, messages, *, system=None, max_tokens=4096, cache_system=False) -> Completion:
        agente = (system or "").splitlines()[0].removeprefix("Eres ").rstrip(".")
        with self._candado:
            cola = self.respuestas.get(agente)
            respuesta = cola.pop(0) if cola else {"accion": "terminar", "resultado": f"{agente}: sin guion"}
            self.recibidos.append((agente, messages[-1].content))
        if callable(respuesta):
            respuesta = respuesta()
        time.sleep(self.demoras.get(agente, 0.01))
        texto = respuesta if isinstance(respuesta, str) else json.dumps(respuesta)
        return Completion(text=texto, usage=Usage(input_tokens=10, output_tokens=5), model=self.model,
                          provider=self.provider, billing=self.billing, tier=self.tier, latency_ms=1)

    def vio(self, agente: str, fragmento: str) -> bool:
        return any(a == agente and fragmento in texto for a, texto in self.recibidos)


def agencia(limites: dict | None = None, **cambios) -> Agencia:
    datos = {
        "name": "prueba",
        "limites": limites or {},
        "departamentos": {
            "dir": {"descripcion": "direccion", "agentes": {
                "jefe": {"descripcion": "reparte", "rol": "Coordinas.", "delega_a": ["inv", "prod", "cont"]},
            }},
            "inv": {"descripcion": "investigacion", "agentes": {
                "a": {"descripcion": "investiga", "rol": "Investigas.", "herramientas": ["codigo.buscar"],
                      "puede_crear": True, "delega_a": ["cont.r"]},
            }},
            "prod": {"descripcion": "producto", "agentes": {
                "b": {"descripcion": "producto", "rol": "Construyes.", "delega_a": ["cont.r"]},
            }},
            "cont": {"descripcion": "contenido", "agentes": {
                "r": {"descripcion": "redacta", "rol": "Redactas.", "herramientas": ["pc.escribir"]},
            }},
        },
    }
    datos.update(cambios)
    return Agencia.model_validate(datos)


def T(resultado: str) -> dict:
    return {"accion": "terminar", "resultado": resultado}


@pytest.fixture
def ledger(tmp_path):
    led = Ledger(tmp_path / "l.sqlite3")
    yield led
    led.close()


def correr(ag: Agencia, guion: Guion, ledger: Ledger, texto: str = "haz algo", agente: str = "dir", **kw):
    return asyncio.run(correr_agencia(ag, texto, ledger=ledger, local=guion, agente=agente, **kw))


def por_agente(resultado, agente: str):
    return next(t for t in resultado.tareas if t.agente == agente)


class TestColaboracion:
    def test_el_escenario_completo(self, ledger) -> None:
        """Dos colaboran con mensajes, otros trabajan en paralelo, uno crea un ayudante
        y otro deriva parte de su tarea."""
        guion = Guion(
            {
                "dir.jefe": [
                    {"accion": "delegar", "a": "inv", "tarea": "investiga X", "esperar": False},
                    {"accion": "delegar", "a": "prod", "tarea": "prepara Y", "esperar": False},
                    {"accion": "enviar", "a": "t2", "texto": "prioriza la parte de precios"},
                    {"accion": "esperar", "tareas": []},
                    T("resumen final"),
                ],
                "inv.a": [
                    {"accion": "crear", "rol": "Lees codigo.", "tarea": "busca Cliente",
                     "herramientas": ["codigo.buscar"], "esperar": True},
                    T("investigacion lista"),
                ],
                "inv.a>ayudante1": [T("dato del ayudante")],
                "prod.b": [
                    {"accion": "delegar", "a": "cont.r", "tarea": "redacta la parte Z", "esperar": True},
                    T("producto listo"),
                ],
                "cont.r": [T("parte Z redactada")],
            },
            demoras={"inv.a>ayudante1": 0.4, "dir.jefe": 0.02},
        )
        r = correr(agencia(), guion, ledger)

        assert r.ok, r.detalle
        assert r.resultado == "resumen final"
        assert {t.estado for t in r.tareas} == {"hecha"}
        a, b = por_agente(r, "inv.a"), por_agente(r, "prod.b")
        ayudante, redactor = por_agente(r, "inv.a>ayudante1"), por_agente(r, "cont.r")
        assert a.paralela and b.paralela
        assert (ayudante.padre, ayudante.origen) == (a.id, "creada")
        assert (redactor.padre, redactor.origen) == (b.id, "delegada")
        # El mensaje del jefe llego mientras `a` esperaba a su ayudante.
        assert guion.vio("inv.a", "prioriza la parte de precios")
        # El jefe recibio los dos resultados al esperar.
        assert guion.vio("dir.jefe", "investigacion lista") and guion.vio("dir.jefe", "producto listo")
        assert r.max_simultaneos >= 2
        lineas = arbol(r.tareas)
        assert lineas[0].startswith("t1 dir.jefe") and any("└─ " in linea for linea in lineas)

    def test_cada_llamada_queda_en_el_ledger_con_su_tarea(self, ledger) -> None:
        guion = Guion({"dir.jefe": [{"accion": "delegar", "a": "prod", "tarea": "x"}, T("ok")],
                       "prod.b": [T("hecho")]})
        r = correr(agencia(), guion, ledger)
        propositos = [f[0] for f in ledger.conn.execute(
            "SELECT purpose FROM calls WHERE run_id = ? ORDER BY rowid", (r.run_id,))]
        assert propositos == ["agente:t1:dir.jefe", "agente:t2:prod.b", "agente:t1:dir.jefe"]

    def test_la_traza_no_guarda_el_contenido(self, ledger) -> None:
        guion = Guion({"dir.jefe": [{"accion": "delegar", "a": "prod", "tarea": "dato-secreto-123"}, T("ok")]})
        r = correr(agencia(), guion, ledger, texto="otro-dato-secreto-456")
        traza = (Path(os.environ["LYMI_TRAZAS"]) / f"{r.run_id}.jsonl").read_text(encoding="utf-8")
        eventos = [json.loads(linea)["evento"] for linea in traza.splitlines()]
        assert "creada" in eventos and "hecha" in eventos
        assert "secreto" not in traza


class TestSeguridad:
    def test_el_ayudante_no_gana_permisos(self, ledger) -> None:
        guion = Guion({
            "dir.jefe": [{"accion": "delegar", "a": "inv", "tarea": "x"}, T("ok")],
            "inv.a": [
                {"accion": "crear", "rol": "r", "tarea": "t", "herramientas": ["pc.escribir"]},
                {"accion": "crear", "rol": "r", "tarea": "t", "herramientas": ["codigo.buscar"]},
                T("listo"),
            ],
            "inv.a>ayudante1": [
                {"accion": "delegar", "a": "cont.r", "tarea": "x"},
                {"accion": "crear", "rol": "r", "tarea": "t"},
                T("sin permisos extra"),
            ],
        })
        r = correr(agencia(), guion, ledger)
        assert r.ok
        assert guion.vio("inv.a", "no tienes: pc.escribir")
        assert guion.vio("inv.a>ayudante1", "no puedes delegar a 'cont.r'")
        assert guion.vio("inv.a>ayudante1", "no puedes crear ayudantes")

    def test_solo_se_delega_por_aristas_declaradas(self, ledger) -> None:
        guion = Guion({"dir.jefe": [{"accion": "delegar", "a": "prod", "tarea": "x"}, T("ok")],
                       "prod.b": [{"accion": "delegar", "a": "inv", "tarea": "x"}, T("no pude")]})
        r = correr(agencia(), guion, ledger)
        assert guion.vio("prod.b", "no puedes delegar a 'inv'; puedes delegar a: cont.r")
        assert len(r.tareas) == 2

    def test_solo_se_espera_y_escribe_a_tareas_propias(self, ledger) -> None:
        guion = Guion({
            "dir.jefe": [{"accion": "delegar", "a": "inv", "tarea": "x", "esperar": False},
                         {"accion": "delegar", "a": "prod", "tarea": "y"}, {"accion": "esperar"}, T("ok")],
            "inv.a": [T("a")],
            "prod.b": [{"accion": "esperar", "tareas": ["t1"]}, {"accion": "enviar", "a": "t9", "texto": "hola"},
                       T("b")],
        }, demoras={"inv.a": 0.2})
        r = correr(agencia(), guion, ledger)
        assert r.ok
        assert guion.vio("prod.b", "solo puedes esperar tareas que tu iniciaste")
        assert guion.vio("prod.b", "solo puedes escribir a tareas relacionadas contigo")

    def test_un_efecto_pide_aprobacion(self, ledger, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        escribir = {"accion": "usar", "herramienta": "pc.escribir",
                    "args": {"ruta": "salidas/informe.md", "contenido": "hola"}}
        vistas: list[str] = []

        def rechazar(paso_id, vista):
            vistas.append(vista)
            return False

        guion = Guion({"cont.r": [escribir, T("no me dejaron")]})
        r = correr(agencia(), guion, ledger, agente="cont", aprobar=rechazar)
        assert r.ok and not (tmp_path / "salidas" / "informe.md").exists()
        assert "cont.r (t1) quiere:" in vistas[0] and "escribir en este PC: salidas/informe.md" in vistas[0]
        assert guion.vio("cont.r", "la accion fue rechazada")

        guion = Guion({"cont.r": [escribir, T("escrito")]})
        r = correr(agencia(), guion, ledger, agente="cont", aprobar=lambda *_: True)
        assert (tmp_path / "salidas" / "informe.md").read_text(encoding="utf-8") == "hola"

    def test_la_parada_corta_el_arbol(self, ledger) -> None:
        def parar_y_delegar():
            detener("prueba")
            return {"accion": "delegar", "a": "prod", "tarea": "x"}

        guion = Guion({"dir.jefe": [parar_y_delegar, T("no deberia llegar")]})
        r = correr(agencia(), guion, ledger)
        assert not r.ok and "detenido" in r.detalle
        assert len(r.tareas) == 1


class TestTopes:
    def test_agentes_totales(self, ledger) -> None:
        guion = Guion({"dir.jefe": [{"accion": "delegar", "a": "inv", "tarea": "x"},
                                    {"accion": "delegar", "a": "prod", "tarea": "y"}, T("ok")]})
        r = correr(agencia({"agentes_totales": 2}), guion, ledger)
        assert guion.vio("dir.jefe", "se alcanzo el tope de 2 agentes")
        assert len(r.tareas) == 2

    def test_profundidad(self, ledger) -> None:
        guion = Guion({"dir.jefe": [{"accion": "delegar", "a": "inv", "tarea": "x"}, T("ok")],
                       "inv.a": [{"accion": "crear", "rol": "r", "tarea": "t"}, T("solo")]})
        correr(agencia({"profundidad": 1}), guion, ledger)
        assert guion.vio("inv.a", "profundidad maxima de delegacion (1)")

    def test_llamadas_de_toda_la_agencia(self, ledger) -> None:
        usar_mal = {"accion": "usar", "herramienta": "web.extraer", "args": {}}
        guion = Guion({"dir.jefe": [usar_mal] * 10})
        r = correr(agencia({"llamadas": 3}), guion, ledger)
        assert not r.ok and "3 llamadas" in r.detalle
        assert ledger.conn.execute("SELECT COUNT(*) FROM calls WHERE run_id = ?", (r.run_id,)).fetchone()[0] == 3

    def test_turnos(self, ledger) -> None:
        guion = Guion({"dir.jefe": [{"accion": "esperar"}] * 5})
        r = correr(agencia({"turnos_por_agente": 2}), guion, ledger)
        assert not r.ok and "agoto sus 2 turnos" in r.detalle

    def test_protocolo(self, ledger) -> None:
        guion = Guion({"dir.jefe": ["hola, soy un modelo charlatan", '{"accion": "volar"}', "[]"]})
        r = correr(agencia(), guion, ledger)
        assert not r.ok and "no siguio el protocolo 3 veces" in r.detalle
        assert guion.vio("dir.jefe", "Responde SOLO un objeto JSON")

    def test_tiempo(self, ledger) -> None:
        guion = Guion({"dir.jefe": [{"accion": "delegar", "a": "inv", "tarea": "x"}]},
                      demoras={"inv.a": 1.0})
        r = correr(agencia({"segundos": 0.3}), guion, ledger)
        assert not r.ok and "tiempo" in r.detalle
        assert {t.estado for t in r.tareas} == {"cancelada"}

    def test_simultaneos(self, ledger) -> None:
        guion = Guion({
            "dir.jefe": [{"accion": "delegar", "a": "inv", "tarea": "x", "esperar": False},
                         {"accion": "delegar", "a": "prod", "tarea": "y", "esperar": False},
                         {"accion": "esperar"}, T("ok")],
        }, demoras={"inv.a": 0.1, "prod.b": 0.1})
        r = correr(agencia({"simultaneos": 1}), guion, ledger)
        assert r.ok and r.max_simultaneos == 1

    def test_terminar_con_tareas_en_curso(self, ledger) -> None:
        guion = Guion({"dir.jefe": [{"accion": "delegar", "a": "inv", "tarea": "x", "esperar": False},
                                    T("apurado"), T("apurado de verdad")]},
                      demoras={"inv.a": 0.5})
        r = correr(agencia(), guion, ledger)
        assert r.ok and r.resultado == "apurado de verdad"
        assert guion.vio("dir.jefe", "Tienes tareas en curso (t2)")
        assert por_agente(r, "inv.a").estado == "cancelada"


class TestHerramientas:
    def test_codigo_y_argumentos_invalidos(self, ledger, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("LYMI_CODIGO", str(tmp_path / "indices"))
        (tmp_path / "repo").mkdir()
        (tmp_path / "repo" / "m.py").write_text("class Cliente:\n    pass\n", encoding="utf-8")
        guion = Guion({"inv.a": [
            {"accion": "usar", "herramienta": "codigo.buscar", "args": {"consulta": "Cliente", "raiz": "repo"}},
            {"accion": "usar", "herramienta": "codigo.buscar", "args": {"nope": 1}},
            {"accion": "usar", "herramienta": "pc.borrar", "args": {"ruta": "x"}},
            T("listo"),
        ]})
        r = correr(agencia(), guion, ledger, agente="inv")
        assert r.ok
        assert guion.vio("inv.a", "m.py:1  clase Cliente")
        assert guion.vio("inv.a", "argumentos invalidos para codigo.buscar")
        assert guion.vio("inv.a", "no tienes la herramienta 'pc.borrar'")

    def test_argumentos_vacios_cuentan_como_no_enviados(self, ledger, tmp_path, monkeypatch) -> None:
        """Hallado en una corrida real con qwen2.5:3b: manda `"raiz": ""` en vez de omitirla."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("LYMI_CODIGO", str(tmp_path / "indices"))
        (tmp_path / "m.py").write_text("def revisar():\n    pass\n", encoding="utf-8")
        guion = Guion({"inv.a": [
            {"accion": "usar", "herramienta": "codigo.buscar", "args": {"consulta": "revisar", "raiz": ""}},
            {"accion": "usar", "herramienta": "codigo.buscar", "args": {"consulta": "", "raiz": None}},
            T("listo"),
        ]})
        correr(agencia(), guion, ledger, agente="inv")
        assert guion.vio("inv.a", "m.py:1  funcion revisar")
        assert guion.vio("inv.a", "op buscar requiere consulta")

    def test_un_agente_corre_un_workflow(self, ledger, tmp_path) -> None:
        (tmp_path / "saludo.yml").write_text(
            "name: saludo\ninputs:\n  nombre: {type: string}\n"
            "steps:\n  - id: armar\n    type: transform\n    set: {texto: 'hola {{ inputs.nombre }}'}\n",
            encoding="utf-8",
        )
        (tmp_path / "ag.yml").write_text(
            "name: ag\ndepartamentos:\n  ops:\n    agentes:\n      o:\n        descripcion: opera\n"
            "        rol: Operas.\n        herramientas: ['workflow:saludo.yml']\n",
            encoding="utf-8",
        )
        ag = cargar_agencia(tmp_path / "ag.yml")
        guion = Guion({"ops.o": [
            {"accion": "usar", "herramienta": "workflow:saludo.yml", "args": {"inputs": {"nombre": "Vicente"}}},
            T("saludado"),
        ]})
        r = correr(ag, guion, ledger, agente="ops")
        assert r.ok
        assert guion.vio("ops.o", "workflow saludo ok") and guion.vio("ops.o", "hola Vicente")


class TestEnrutar:
    def test_arroba_departamento_unico_y_modelo(self, ledger) -> None:
        ag = agencia()
        with ledger.run("r", "r", Billing.LOCAL) as run:
            rec = Recorder(run)
            assert asyncio.run(enrutar(ag, "@prod arma el plan", None, rec))[:2] == ("prod.b", "arma el plan")
            modelo = Guion({})
            modelo.complete = lambda messages, **kw: Completion(  # type: ignore[method-assign]
                text="inv", usage=Usage(), model="m", provider="p", billing=Billing.LOCAL, tier="local", latency_ms=1)
            assert asyncio.run(enrutar(ag, "cuanto cuesta X", modelo, rec))[0] == "inv.a"
            modelo.complete = lambda messages, **kw: Completion(  # type: ignore[method-assign]
                text="marte", usage=Usage(), model="m", provider="p", billing=Billing.LOCAL, tier="local", latency_ms=1)
            destino, _, motivo = asyncio.run(enrutar(ag, "algo", modelo, rec))
            assert destino == "dir.jefe" and "'marte', que no existe" in motivo
            assert asyncio.run(enrutar(ag, "algo", None, rec))[2].startswith("sin modelo local")


class TestDefinicion:
    @pytest.mark.parametrize("cambio,mensaje", [
        ({"herramientas": ["shell.todo"]}, "herramienta desconocida"),
        ({"delega_a": ["marte"]}, "no es un agente ni un departamento"),
        ({"delega_a": ["dir.jefe"]}, "no puede delegarse a si mismo"),
    ])
    def test_errores(self, cambio, mensaje) -> None:
        datos = agencia().model_dump(exclude={"workflows"})
        datos["departamentos"]["dir"]["agentes"]["jefe"].update(cambio)
        with pytest.raises(ValueError, match=mensaje):
            Agencia.model_validate(datos)

    def test_rol_fuera_de_la_carpeta(self, tmp_path) -> None:
        (tmp_path / "sub").mkdir()
        (tmp_path / "secreto.md").write_text("x", encoding="utf-8")
        (tmp_path / "sub" / "ag.yml").write_text(
            "name: ag\ndepartamentos:\n  d:\n    agentes:\n      a:\n        descripcion: x\n"
            "        rol: 'archivo:../secreto.md'\n", encoding="utf-8")
        with pytest.raises(AgenciaError, match="fuera de la carpeta"):
            cargar_agencia(tmp_path / "sub" / "ag.yml")

    def test_el_ejemplo_es_valido(self) -> None:
        ag = cargar_agencia(RAIZ_PROYECTO / "agencias" / "startup.example.yml")
        assert ag.resolver("investigacion") == "investigacion.analista"
        assert "Nunca afirmes un dato" in ag.agentes()["direccion.coordinador"].rol

    def test_cli_plan(self) -> None:
        r = CliRunner().invoke(app, ["agencia", "plan", str(RAIZ_PROYECTO / "agencias" / "startup.example.yml")])
        assert r.exit_code == 0, r.output
        assert "pide aprobacion" in r.output and "topes duros" in r.output


class TestPasoAgencia:
    def test_en_un_workflow(self, ledger, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(RAIZ_PROYECTO)
        flujo = Workflow.model_validate({"name": "con_agencia", "inputs": {"tema": {"type": "string"}}, "steps": [
            {"id": "equipo", "type": "agencia", "archivo": "agencias/startup.example.yml",
             "agente": "producto", "tarea": "revisa {{ inputs.tema }}"},
        ]})
        (fila,) = planificar(flujo)
        # La agencia tiene agentes con web: el plan no sabe a quien se delegara y avisa.
        assert fila.costo == "externo" and not fila.efectos
        guion = Guion({"producto.ingeniero": [T("revisado")]})
        r = asyncio.run(ejecutar_flujo(flujo, {"tema": "el ledger"}, ledger=ledger, local=guion))
        assert r.ok, r.detalle
        assert r.salidas["equipo"]["resultado"] == "revisado"
        assert guion.vio("producto.ingeniero", "revisa el ledger")

    def test_no_se_reintenta(self) -> None:
        with pytest.raises(ValueError, match="no se reintenta"):
            Workflow.model_validate({"name": "x", "steps": [
                {"id": "a", "type": "agencia", "archivo": "a.yml", "tarea": "t", "retries": 1}]})


class TestProtocolo:
    @pytest.mark.parametrize("texto,esperado", [
        ('{"accion": "codigo.buscar", "consulta": "x"}', ("usar", "codigo.buscar", {"consulta": "x"})),
        ('{"accion": "codigo.buscar", "args": {"consulta": "x"}}', ("usar", "codigo.buscar", {"consulta": "x"})),
        ('{"herramienta": "web.extraer", "args": {"url": "u"}}', ("usar", "web.extraer", {"url": "u"})),
    ])
    def test_formas_inequivocas_de_usar(self, texto, esperado) -> None:
        from lymi.agencia.protocolo import interpretar

        accion = interpretar(texto)
        assert (accion.accion, accion.herramienta, accion.args) == esperado

    def test_terminar_con_otra_clave(self) -> None:
        from lymi.agencia.protocolo import interpretar

        assert interpretar('{"accion": "terminar", "respuesta": "listo"}').resultado == "listo"

    @pytest.mark.parametrize("texto", [
        '{"accion": "volar"}',
        '{"accion": "terminar"}',
        '{"accion": "codigo.buscar", "args": {"consulta": "x"}, "extra": 1}',
    ])
    def test_lo_ambiguo_sigue_siendo_error(self, texto) -> None:
        from lymi.agencia.protocolo import ProtocoloError, interpretar

        with pytest.raises(ProtocoloError):
            interpretar(texto)


class RemotoAgotado:
    provider = "claude-code"
    model = "claude"
    billing = Billing.SUBSCRIPTION
    tier = "frontier"

    def complete(self, messages, **kw):
        from lymi.providers.claude_code import ClaudeCodeLimiteError

        raise ClaudeCodeLimiteError("la suscripcion llego a su limite de uso")


class TestModelos:
    def _agencia(self, **agente) -> Agencia:
        return Agencia.model_validate({"name": "m", "departamentos": {"d": {"agentes": {
            "a": {"descripcion": "x", "rol": "r", **agente}}}}})

    @pytest.mark.parametrize("agente,mensaje", [
        ({"tier": "remote", "modelo": "qwen3:4b"}, "elige un modelo local"),
        ({"tier": "local", "respaldo": "local"}, "solo tiene sentido en un agente remote"),
    ])
    def test_validacion(self, agente, mensaje) -> None:
        with pytest.raises(ValueError, match=mensaje):
            self._agencia(**agente)

    def test_respaldo_local_visible(self, ledger) -> None:
        local = Guion({"d.a": [T("lo hizo el local")]})
        ag = self._agencia(tier="remote", respaldo="local")
        r = asyncio.run(correr_agencia(ag, "x", ledger=ledger, local=local, remote=RemotoAgotado(), agente="d"))
        assert r.ok and r.resultado == "lo hizo el local"
        (t,) = r.tareas
        assert t.tier == "local" and "agoto su cuota" in t.avisos[0]
        assert "[aviso: el remoto agoto su cuota" in arbol(r.tareas)[0]

    def test_sin_respaldo_falla_con_el_motivo(self, ledger) -> None:
        ag = self._agencia(tier="remote")
        r = asyncio.run(correr_agencia(ag, "x", ledger=ledger, local=Guion({}), remote=RemotoAgotado(), agente="d"))
        assert not r.ok and "limite de uso" in r.detalle

    def test_modelo_por_agente(self, ledger, monkeypatch) -> None:
        creados: list[str] = []

        class OllamaFalso(Guion):
            def __init__(self, model: str) -> None:
                super().__init__({"d.a": [T(f"respondio {model}")]})
                creados.append(model)

        monkeypatch.setattr("lymi.providers.local.OllamaClient", OllamaFalso)
        ag = self._agencia(tier="local", modelo="qwen3:4b")
        r = asyncio.run(correr_agencia(ag, "x", ledger=ledger, local=Guion({}), agente="d"))
        assert r.resultado == "respondio qwen3:4b" and creados == ["qwen3:4b"]


BUSCAR_REVISAR = {"accion": "usar", "herramienta": "codigo.buscar", "args": {"consulta": "revisar"}}


class TestCitas:
    def test_formatos(self) -> None:
        from lymi.agencia.citas import citas, respaldada, vistas

        v = vistas(
            "# src/lymi/web/red.py (python, 400 lineas)\ndef f(): ...  # L91\n"
            "# src/x.py:10-12  g\ncodigo\nver https://a.com/b.\n"
        )
        assert {"src/lymi/web/red.py:91", "src/x.py:10", "src/x.py:12", "https://a.com/b"} <= v
        assert citas("en red.py:91 y ./src/x.py:11, ver https://a.com/b.") == [
            "red.py:91", "src/x.py:11", "https://a.com/b"]
        assert respaldada("red.py:91", v) and respaldada("src/x.py:11", v)
        assert not respaldada("buscar.py:39", v) and not respaldada("https://otra.com", v)
        assert citas("ver .github/ci.yml:3") == [".github/ci.yml:3"]

    @pytest.fixture
    def repo(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("LYMI_CODIGO", str(tmp_path / "indices"))
        (tmp_path / "m.py").write_text("def revisar():\n    pass\n", encoding="utf-8")
        return tmp_path

    def test_una_cita_inventada_se_devuelve_y_despues_se_marca(self, ledger, repo) -> None:
        inventada = T("esta en m.py:1 y en otro.py:39")
        guion = Guion({"inv.a": [BUSCAR_REVISAR, inventada, inventada]})
        r = correr(agencia(), guion, ledger, agente="inv")
        assert r.ok
        # El aviso nombra la cita, pero no la vuelve "vista": el segundo intento sigue marcado.
        assert guion.vio("inv.a", "no aparecen en nada de lo que viste: otro.py:39")
        assert por_agente(r, "inv.a").sin_respaldo == ["otro.py:39"]
        assert "citas sin respaldo: otro.py:39" in "\n".join(arbol(r.tareas))

    def test_corregir_limpia_la_marca(self, ledger, repo) -> None:
        guion = Guion({"inv.a": [BUSCAR_REVISAR, T("esta en otro.py:39"), T("esta en m.py:1")]})
        r = correr(agencia(), guion, ledger, agente="inv")
        assert r.resultado == "esta en m.py:1" and por_agente(r, "inv.a").sin_respaldo == []

    def test_se_puede_citar_la_tarea_y_lo_que_entrega_una_hija(self, ledger) -> None:
        guion = Guion({
            "dir.jefe": [{"accion": "delegar", "a": "prod", "tarea": "revisa src/a.py:5"},
                         T("src/a.py:5 revisado; ver https://ejemplo.com/doc")],
            "prod.b": [T("src/a.py:5 esta bien, fuente https://ejemplo.com/doc")],
        })
        r = correr(agencia(), guion, ledger, texto="revisa src/a.py:5 segun https://ejemplo.com/doc")
        assert r.ok and all(not t.sin_respaldo for t in r.tareas)
        assert not guion.vio("dir.jefe", "no aparecen en nada")
