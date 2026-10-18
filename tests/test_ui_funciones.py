"""La interfaz completa: hoy, correo, chat, agencia, memoria, programaciones, codigo,
diario del PC y el editor de workflows. Todo contra datos sinteticos y un modelo con guion."""

from __future__ import annotations

import json
import shutil
import threading
import time
from pathlib import Path

import pytest
import yaml
from starlette.testclient import TestClient

from lymi.agencia.protocolo import interpretar
from lymi.ledger import Billing, Ledger
from lymi.providers.base import Completion, Message, Usage
from lymi.providers.local import contexto_necesario
from lymi.ui.app import ConfigUI, crear_app_ui
from lymi.web.markdown import html_a_markdown

TOKEN = "t" * 40


class Guion:
    """Modelo falso: responde segun el agente (primera linea del sistema) y su turno."""

    provider = "guion"
    model = "guion-1"
    billing = Billing.LOCAL
    tier = "local"

    def __init__(self, respuestas: dict[str, list]) -> None:
        self.respuestas = {k: list(v) for k, v in respuestas.items()}
        self.recibidos: list[tuple[str, str]] = []
        self._candado = threading.Lock()

    def complete(self, messages, *, system=None, max_tokens=4096, cache_system=False) -> Completion:
        agente = (system or "").splitlines()[0].removeprefix("Eres ").rstrip(".")
        with self._candado:
            cola = self.respuestas.get(agente)
            respuesta = cola.pop(0) if cola else {"accion": "terminar", "resultado": f"{agente}: sin guion"}
            self.recibidos.append((agente, messages[-1].content))
        texto = respuesta if isinstance(respuesta, str) else json.dumps(respuesta)
        return Completion(text=texto, usage=Usage(input_tokens=10, output_tokens=5), model=self.model,
                          provider=self.provider, billing=self.billing, tier=self.tier, latency_ms=1)

    def vio(self, agente: str, fragmento: str) -> bool:
        return any(a == agente and fragmento in texto for a, texto in self.recibidos)


def T(resultado: str) -> dict:
    return {"accion": "terminar", "resultado": resultado}
RAIZ = Path(__file__).resolve().parent.parent

MBOX_FIJO = """From - Mon Sep 15 10:00:00 2026
X-Mozilla-Status: 0000
Date: Mon, 15 Sep 2026 10:00:00 +0000
From: Ana Perez <ana@cliente.cl>
To: vicente@ejemplo.cl
Subject: Propuesta para el martes
Message-ID: <uno@cliente.cl>
Content-Type: text/plain; charset=utf-8

Hola, te mando la propuesta. Necesito tu respuesta antes del martes.

From - Tue Sep 16 08:00:00 2026
X-Mozilla-Status: 0001
Date: Tue, 16 Sep 2026 08:00:00 +0000
From: Tienda <ofertas@tienda.cl>
To: vicente@ejemplo.cl
Subject: 50% de descuento
List-Unsubscribe: <https://tienda.cl/baja>
Content-Type: text/plain; charset=utf-8

Ofertas de la semana.
"""



def _mbox() -> str:
    """El buzon de prueba con fechas de hace 2 y 1 dias: un resumen "de los ultimos N dias"
    no puede depender del dia en que corre la suite."""
    from datetime import UTC, datetime, timedelta
    from email.utils import format_datetime

    texto = MBOX_FIJO
    for fija, hace in (("Mon, 15 Sep 2026 10:00:00 +0000", 2), ("Tue, 16 Sep 2026 08:00:00 +0000", 1)):
        texto = texto.replace(fija, format_datetime(datetime.now(UTC) - timedelta(days=hace)))
    return texto


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LYMI_TEMA", str(tmp_path / "theme.toml"))
    (tmp_path / "workflows").mkdir()
    shutil.copytree(RAIZ / "agencias", tmp_path / "agencias")
    return tmp_path


def cliente_con(entorno: Path, guion: Guion | None = None) -> TestClient:
    config = ConfigUI(
        ledger=entorno / "runs" / "lymi.sqlite3", workflows=entorno / "workflows",
        memoria=entorno / "runs" / "aprobaciones.sqlite3", hosts=frozenset({"testserver"}), token=TOKEN,
        proveedores=lambda: (guion, "guion" if guion else None, None, None),
        agencias=entorno / "agencias", agenda=entorno / "runs" / "agenda.sqlite3",
        ganchos=entorno / "runs" / "ganchos.sqlite3", sesiones=entorno / "runs" / "sesiones",
    )
    c = TestClient(crear_app_ui(config))
    c.headers.update({"X-Lymi-Token": TOKEN})
    return c


def esperar(c: TestClient, trabajo_id: str, timeout: float = 20.0) -> dict:
    limite = time.monotonic() + timeout
    while time.monotonic() < limite:
        t = c.get(f"/api/trabajos/{trabajo_id}").json()
        if t["estado"] not in {"en_curso", "esperando"}:
            return t
        time.sleep(0.05)
    raise AssertionError(f"el trabajo {trabajo_id} no termino: {t}")


# ---------------------------------------------------------------- hoy y correo


def test_hoy_sin_fuentes_configuradas_dice_que_falta(entorno) -> None:
    with cliente_con(entorno) as c:
        d = c.get("/api/hoy").json()
    assert not d["correo"]["ok"] and "LYMI_CORREO" in d["correo"]["error"]
    assert not d["agenda"]["ok"] and "no hay archivos .ics" in d["agenda"]["error"]
    assert d["programaciones"] == {"ok": True, "datos": []}
    assert d["esperando"] == [] and d["sesiones"] == []


@pytest.fixture
def perfil(entorno, monkeypatch) -> Path:
    raiz = entorno / "perfil"
    (raiz / "ImapMail" / "imap.ejemplo.com").mkdir(parents=True)
    (raiz / "ImapMail" / "imap.ejemplo.com" / "INBOX").write_text(_mbox(), encoding="utf-8")
    (raiz / "prefs.js").write_text('user_pref("mail.identity.id1.useremail", "vicente@ejemplo.cl");\n', encoding="utf-8")
    monkeypatch.setenv("LYMI_CORREO", str(raiz))
    return raiz


class TestCorreo:
    def test_carpetas_filtros_y_lectura(self, entorno, perfil) -> None:
        with cliente_con(entorno) as c:
            carpetas = c.get("/api/correo/carpetas").json()
            assert carpetas["direcciones"] == ["vicente@ejemplo.cl"]
            todos = c.get("/api/correo/mensajes?carpeta=INBOX&filtro=todos").json()
            para_mi = c.get("/api/correo/mensajes?carpeta=INBOX&filtro=para_mi").json()
            assert len(todos["mensajes"]) == 2 and [m["asunto"] for m in para_mi["mensajes"]] == ["Propuesta para el martes"]
            assert todos["ultimo"] is not None  # para avisar si Thunderbird no sincroniza
            n = para_mi["mensajes"][0]["n"]
            m = c.get(f"/api/correo/mensaje?carpeta=INBOX&n={n}").json()
            assert "antes del martes" in m["cuerpo"] and m["para_mi"]

    def test_guardar_borrador_pasa_por_el_ejecutor(self, entorno, perfil) -> None:
        with cliente_con(entorno) as c:
            n = c.get("/api/correo/mensajes?carpeta=INBOX&filtro=para_mi").json()["mensajes"][0]["n"]
            r = c.post("/api/correo/borrador/guardar", json={"carpeta": "INBOX", "n": n, "cuerpo": "Te respondo el lunes."})
        assert r.status_code == 200, r.text
        eml = Path(r.json()["ruta"]).read_text(encoding="utf-8")
        assert "In-Reply-To: <uno@cliente.cl>" in eml and "Te respondo el lunes." in eml
        assert r.json()["asunto"] == "Re: Propuesta para el martes"

    def test_borrador_con_el_modelo(self, entorno, perfil) -> None:
        class Redactor(Guion):
            def complete(self, messages, **kw):
                completion = super().complete(messages, **kw)
                completion.text = "Gracias Ana, lo reviso y te confirmo el martes."
                return completion

        with cliente_con(entorno, Redactor({})) as c:
            n = c.get("/api/correo/mensajes?carpeta=INBOX&filtro=para_mi").json()["mensajes"][0]["n"]
            t = c.post("/api/correo/borrador", json={"carpeta": "INBOX", "n": n, "instruccion": "di que si"}).json()
            r = esperar(c, t["id"])["resultado"]
        assert r["ok"] and "te confirmo el martes" in r["cuerpo"] and r["para"].endswith("ana@cliente.cl>")


# ---------------------------------------------------------------- chat


class TestChat:
    def test_una_conversacion_con_contexto(self, entorno) -> None:
        guion = Guion({"lymi.asistente": [T("Hola, soy lymi."), T("Dijiste hola.")]})
        with cliente_con(entorno, guion) as c:
            r = c.post("/api/sesiones", json={"texto": "hola", "tier": "local"})
            assert r.status_code == 202, r.text
            sesion = r.json()["sesion"]
            esperar(c, r.json()["trabajo"]["id"])
            time.sleep(0.1)  # el resultado se guarda al terminar el hilo
            s = c.get(f"/api/sesiones/{sesion['id']}").json()
            assert [m["rol"] for m in s["mensajes"]] == ["persona", "lymi"]
            assert s["mensajes"][1]["texto"] == "Hola, soy lymi." and s["mensajes"][1]["estado"] == "ok"
            assert s["mensajes"][1]["run_id"] and s["mensajes"][1]["tareas"][0]["agente"] == "lymi.asistente"

            r2 = c.post(f"/api/sesiones/{sesion['id']}/mensajes", json={"texto": "¿qué dije?"})
            esperar(c, r2.json()["trabajo"]["id"])
            time.sleep(0.1)
            assert c.get("/api/sesiones").json()[0]["mensajes"] == 4
        # El segundo turno lleva la conversacion anterior.
        assert guion.vio("lymi.asistente", "Conversacion hasta ahora") and guion.vio("lymi.asistente", "Hola, soy lymi.")

    def test_debate_reparte_y_sintetiza(self, entorno) -> None:
        guion = Guion({
            "debate.moderador": [
                {"accion": "delegar", "a": "a_favor", "tarea": "defiende", "esperar": False},
                {"accion": "delegar", "a": "en_contra", "tarea": "ataca", "esperar": False},
                {"accion": "esperar"},
                T("Veredicto: depende."),
            ],
            "debate.a_favor": [T("Si, porque X.")],
            "debate.en_contra": [T("No, porque Y.")],
        })
        with cliente_con(entorno, guion) as c:
            r = c.post("/api/sesiones", json={"texto": "¿Vale la pena?", "modo": "debate"}).json()
            t = esperar(c, r["trabajo"]["id"])
        assert t["resultado"]["resultado"] == "Veredicto: depende."
        assert {x["agente"] for x in t["resultado"]["tareas"]} == {"debate.moderador", "debate.a_favor", "debate.en_contra"}
        assert any("a_favor" in e for e in t["eventos"])  # el progreso llega a la pagina en vivo

    def test_borrar_y_validar(self, entorno) -> None:
        with cliente_con(entorno, Guion({})) as c:
            assert c.post("/api/sesiones", json={"texto": "  "}).status_code == 400
            assert c.post("/api/sesiones", json={"texto": "x", "tier": "nube"}).status_code == 400
            assert c.get("/api/sesiones/000000000000").status_code == 404
            sid = c.post("/api/sesiones", json={"texto": "hola"}).json()["sesion"]["id"]
            time.sleep(0.2)
            assert c.delete(f"/api/sesiones/{sid}").status_code == 200
            assert c.get(f"/api/sesiones/{sid}").status_code == 404


def test_modelos_dice_cuando_ollama_no_responde(entorno) -> None:
    with cliente_con(entorno) as c:
        d = c.get("/api/modelos").json()
    assert d["locales"] == [] and "Ollama no responde" in d["error_local"]


# ---------------------------------------------------------------- agencia


def test_agencia_organigrama_y_corrida(entorno) -> None:
    guion = Guion({"direccion.coordinador": [T("Plan listo.")]})
    with cliente_con(entorno, guion) as c:
        lista = c.get("/api/agencias").json()["agencias"]
        assert [a["archivo"] for a in lista] == ["startup.example.yml"]
        org = c.get("/api/agencias/startup.example.yml").json()
        coordinador = next(a for d in org["departamentos"] for a in d["agentes"] if a["nombre"] == "coordinador")
        assert coordinador["lider"] and coordinador["delega_a"] and org["limites"]["profundidad"] >= 1
        t = c.post("/api/agencias/startup.example.yml/correr", json={"tarea": "arma un plan", "agente": "direccion"}).json()
        r = esperar(c, t["id"])["resultado"]
        assert r["ok"] and r["resultado"] == "Plan listo."
        assert c.post("/api/agencias/startup.example.yml/correr", json={"tarea": "x", "agente": "nadie"}).status_code == 400
        assert c.get("/api/agencias/..%2Fpyproject.toml").status_code == 404


# ---------------------------------------------------------------- memoria y programaciones


def test_memoria_lo_que_anota_la_persona_es_hecho(entorno) -> None:
    with cliente_con(entorno) as c:
        r = c.post("/api/memoria", json={"texto": "El cliente prefiere reuniones los martes.", "fuente": "llamada"})
        assert r.status_code == 201 and r.json()["estado"] == "hecho"
        d = c.get("/api/memoria?estado=hechos").json()
        assert d["cuentas"]["hechos"] == 1 and d["notas"][0]["agente"] == "persona"
        assert c.get("/api/memoria/buscar?q=martes").json()[0]["texto"].startswith("El cliente")
        assert c.post("/api/memoria", json={"texto": "clave sk-ant-api03-" + "a" * 40}).status_code == 400


def test_programar_pausar_reanudar_y_quitar(entorno) -> None:
    (entorno / "workflows" / "hola.yml").write_text(yaml.safe_dump({
        "name": "hola", "steps": [{"id": "x", "type": "transform", "set": {"a": "1"}}]}), encoding="utf-8")
    with cliente_con(entorno) as c:
        r = c.post("/api/programaciones", json={"workflow": "hola.yml", "cron": "0 8 * * *", "zona": "America/Santiago"})
        assert r.status_code == 201, r.text
        pid = r.json()["id"]
        assert c.post(f"/api/programaciones/{pid}/pausar", json={}).json()["activo"] is False
        assert c.post(f"/api/programaciones/{pid}/reanudar", json={}).json()["activo"] is True
        assert c.get("/api/programaciones").json()["programaciones"][0]["cron"] == "0 8 * * *"
        assert c.delete(f"/api/programaciones/{pid}").status_code == 200
        assert c.post("/api/programaciones", json={"workflow": "hola.yml", "cron": "cada rato"}).status_code == 400
        assert c.post("/api/programaciones", json={"workflow": "otro.yml", "cron": "@daily"}).status_code == 404


# ---------------------------------------------------------------- codigo y PC


def test_codigo_indexa_busca_y_respeta_zonas_vetadas(entorno) -> None:
    repo = entorno / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("def sumar(a, b):\n    return a + b\n\n\ndef total(x):\n    return sumar(x, 1)\n", encoding="utf-8")
    with cliente_con(entorno) as c:
        idx = c.post("/api/codigo", json={"op": "indexar", "raiz": str(repo)}).json()
        assert idx["datos"]["total"] == 1 and "indice al dia" in idx["texto"]
        assert c.post("/api/codigo", json={"op": "buscar", "raiz": str(repo), "consulta": "sum"}).json()["datos"][0]["nombre"] == "sumar"
        assert "return a + b" in c.post("/api/codigo", json={"op": "fragmento", "raiz": str(repo), "nombre": "sumar"}).json()["texto"]
        assert "total" in c.post("/api/codigo", json={"op": "llamadores", "raiz": str(repo), "nombre": "sumar"}).json()["texto"]
        assert c.post("/api/codigo", json={"op": "indexar", "raiz": str(Path.home() / ".ssh")}).status_code == 403
        assert c.post("/api/codigo", json={"op": "magia", "raiz": str(repo)}).status_code == 400


def test_diario_del_pc_y_deshacer(entorno) -> None:
    from lymi.ejecutor import Diario, raiz_diario

    archivo = entorno / "salidas" / "nota.md"
    archivo.parent.mkdir()
    diario = Diario(raiz_diario() / "corrida1")
    diario.antes_de_escribir(archivo)
    archivo.write_text("hola", encoding="utf-8")
    with cliente_con(entorno) as c:
        d = c.get("/api/diario").json()
        assert d["corridas"][0]["corrida"] == "corrida1" and d["corridas"][0]["entradas"][0]["op"] == "creado"
        assert c.get("/api/equipo/perfil").json()["escribibles"]
        r = c.post("/api/diario/corrida1/deshacer", json={})
        assert r.status_code == 200 and not archivo.exists()
        assert c.post("/api/diario/corrida1/deshacer", json={}).status_code == 400  # ya se deshizo
        assert c.post("/api/diario/..%2F..%2Fx/deshacer", json={}).status_code == 404


def test_web_valida_antes_de_salir(entorno) -> None:
    with cliente_con(entorno) as c:
        assert c.post("/api/web", json={"op": "hackear"}).status_code == 400
        assert c.post("/api/web", json={"op": "extraer"}).status_code == 400


# ---------------------------------------------------------------- editor de workflows


FLUJO_EDITOR = {"name": "prueba", "steps": [
    {"id": "datos", "type": "transform", "set": {"a": "1"}},
    {"id": "guardar", "type": "pc", "op": "escribir", "ruta": "salidas/x.md", "contenido": "{{ steps.datos.output.a }}"},
]}


class TestEditor:

    def test_esquema_para_paleta_e_inspector(self, entorno) -> None:
        with cliente_con(entorno) as c:
            d = c.get("/api/editor/esquema").json()
        tipos = {t["tipo"]: t for t in d["tipos"]}
        assert {"llm", "correo", "web", "pc", "agencia", "transform"} <= set(tipos)
        assert "prompt" in tipos["llm"]["campos"] and "tier" in tipos["llm"]["requeridos"]
        assert d["grupos"][0] == "Modelos"

    def test_validar_crear_guardar_con_copia_y_correr(self, entorno) -> None:
        with cliente_con(entorno) as c:
            v = c.post("/api/editor/validar", json={"flujo": FLUJO_EDITOR}).json()
            assert v["ok"] and v["resumen"]["con_efectos"] == 1 and "guardar" in v["yaml"]
            malo = {"name": "x", "steps": [{"id": "a", "type": "llm"}]}
            v2 = c.post("/api/editor/validar", json={"flujo": malo}).json()
            assert not v2["ok"] and "steps.0" in v2["error"]

            assert c.post("/api/workflows", json={"archivo": "prueba.yml", "flujo": FLUJO_EDITOR}).status_code == 201
            assert c.post("/api/workflows", json={"archivo": "prueba.yml", "flujo": FLUJO_EDITOR}).status_code == 409
            assert c.post("/api/workflows", json={"archivo": "../fuera.yml", "flujo": FLUJO_EDITOR}).status_code == 400
            cambiado = {**FLUJO_EDITOR, "description": "con descripcion"}
            assert c.put("/api/workflows/prueba.yml", json={"flujo": cambiado}).status_code == 200
            assert list((entorno / "runs" / "workflows-anteriores").glob("prueba.*.yml"))
            assert c.put("/api/workflows/prueba.yml", json={"flujo": malo}).status_code == 400
            leido = c.get("/api/workflows/prueba.yml").json()
            assert leido["flujo"]["description"] == "con descripcion" and "retries" not in leido["flujo"]["steps"][0]

            t = c.post("/api/workflows/prueba.yml/correr", json={"entradas": {}}).json()
            limite = time.monotonic() + 10
            while (v := c.get(f"/api/trabajos/{t['id']}").json())["estado"] != "esperando" and time.monotonic() < limite:
                time.sleep(0.05)
            # El lienzo ve cada nodo: el primero listo, el segundo esperando permiso.
            assert v["pasos"]["datos"]["estado"] == "ok" and v["pasos"]["guardar"]["estado"] == "esperando"
            c.post(f"/api/trabajos/{t['id']}/aprobacion", json={"decision": "rechazar"})
            final = esperar(c, t["id"])
            assert final["pasos"]["guardar"]["estado"] == "rechazado" and not (entorno / "salidas" / "x.md").exists()

    def test_costo_por_nodo_es_la_mediana_real(self, entorno) -> None:
        from lymi.bench.runner import Recorder

        (entorno / "workflows" / "m.yml").write_text(yaml.safe_dump({"name": "medido", "steps": [
            {"id": "pensar", "type": "llm", "tier": "local", "prompt": "hola"}]}), encoding="utf-8")
        ledger = Ledger(entorno / "runs" / "lymi.sqlite3")
        try:
            for tokens in (100, 300, 200):
                with ledger.run("medido", "flow", Billing.LOCAL) as run:
                    Recorder(run).registrar(
                        Completion(text="x", usage=Usage(input_tokens=tokens, output_tokens=0), model="m", provider="p",
                                   billing=Billing.LOCAL, tier="local", latency_ms=1),
                        [Message("user", "hola")], purpose="flow:pensar")
        finally:
            ledger.close()
        with cliente_con(entorno) as c:
            d = c.get("/api/workflows/m.yml/costos").json()
        assert d["corridas"] == 3 and d["pasos"]["pensar"]["tokens"] == 200 and d["pasos"]["pensar"]["corridas"] == 3


# ---------------------------------------------------------------- piezas que destapo probar la app de verdad


class TestHallazgos:
    def test_un_modelo_chico_que_termina_sin_resultado(self) -> None:
        assert interpretar('La carpeta tiene 2 archivos.\n```json\n{"accion": "terminar"}\n```').resultado == "La carpeta tiene 2 archivos."
        assert interpretar('{"accion": "terminar", "mensaje_final": "listo"}').resultado == "listo"

    def test_el_contexto_de_ollama_alcanza_para_el_prompt(self) -> None:
        corto = contexto_necesario("sistema", [Message("user", "hola")], 1024)
        largo = contexto_necesario("x" * 30_000, [], 1024)
        assert corto == 8192 and largo == 16384  # Ollama por defecto usa 4096 y recorta en silencio

    def test_correo_html_de_maquetacion_se_lee_como_texto(self) -> None:
        html = ('<table><tr><td><img src="https://x/logo.png" alt="Logo"></td></tr><tr><td><table>'
                '<tr><td>Estimado: Ana</td></tr><tr><td>Tu clave cambio.</td></tr></table></td></tr></table>')
        texto = html_a_markdown(html, "", correo=True).markdown
        assert texto == "Estimado: Ana\n\nTu clave cambio." and "|" not in texto and "logo" not in texto

    def test_tablas_anidadas_en_la_web_no_se_duplican(self) -> None:
        html = '<table><tr><td><table><tr><td>uno</td></tr></table></td></tr><tr><td>dos</td></tr></table>'
        assert html_a_markdown(html, "").markdown.count("uno") == 1

    def test_texto_plano_que_es_css_no_gana_al_html(self) -> None:
        import email
        import email.policy

        from lymi.correo.buzon import _convertir

        crudo = (
            "Subject: Hola\nContent-Type: multipart/alternative; boundary=B\n\n--B\nContent-Type: text/plain\n\n"
            "@import url('https://fonts.googleapis.com/x');\n.boton { color: red; padding: 40px 40px 40px 40px; }\n"
            "--B\nContent-Type: text/html\n\n<p>Bienvenido a la tienda.</p>\n--B--\n"
        )
        mensaje = email.message_from_string(crudo, policy=email.policy.default)
        assert _convertir(mensaje, "INBOX", 1, False, False).cuerpo == "Bienvenido a la tienda."

    def test_sin_calendario_el_informe_sigue(self, entorno) -> None:
        import asyncio

        from lymi.flows.engine import ejecutar_flujo
        from lymi.flows.schema import Workflow

        flujo = Workflow.model_validate({"name": "agenda", "steps": [{"id": "hoy", "type": "calendario"}]})
        ledger = Ledger(entorno / "l.sqlite3")
        try:
            r = asyncio.run(ejecutar_flujo(flujo, {}, ledger=ledger))
        finally:
            ledger.close()
        assert r.ok and r.salidas["hoy"]["texto"] == "sin calendario configurado"
        assert "no hay archivos .ics" in r.salidas["hoy"]["avisos"][0]


def test_el_json_del_resumen_de_correo(entorno, perfil) -> None:
    """El resumen llega a la pagina como datos: prioridad y accion por mensaje."""

    class Anotador(Guion):
        def complete(self, messages, **kw):
            completion = super().complete(messages, **kw)
            completion.text = json.dumps([{"n": 1, "prioridad": "alta", "accion": "responder antes del martes"}])
            return completion

    with cliente_con(entorno, Anotador({})) as c:
        t = c.post("/api/correo/resumen", json={"dias": 30}).json()
        r = esperar(c, t["id"])["resultado"]
    assert r["ok"], r
    datos = r["datos"]["resumen"]["datos"]
    assert datos["boletines"] == 1 and datos["mensajes"][0]["prioridad"] == "alta"
    assert datos["mensajes"][0]["accion"] == "responder antes del martes"
