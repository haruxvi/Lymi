"""Mapa del codigo: extraccion, indice fresco, consultas, paso de workflow y servidor MCP real."""

from __future__ import annotations

import asyncio
import os
import shutil
import sqlite3
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from typer.testing import CliRunner

from lymi.cli import app
from lymi.codigo import Indice, IndiceError, abrir, extraer
from lymi.codigo import formato as fmt
from lymi.flows.engine import ejecutar_flujo
from lymi.flows.plan import planificar
from lymi.flows.schema import Workflow
from lymi.ledger import Ledger
from lymi.privacidad.etiquetas import Etiquetas, Nivel, Regla

MODULO_A = '''\
"""Modulo a."""

LIMITE = 10


class Cliente:
    """Habla con el servidor."""

    def obtener(self, clave: str) -> str:
        """Devuelve el valor."""
        return self._leer(clave)

    def _leer(self, clave):
        return clave.upper()


def ayudante(x: int = 1) -> int:
    return x + 1
'''

MODULO_B = '''\
class Agenda:
    def obtener(self, id_):
        return id_
'''

USA_A = '''\
from paquete.a import Cliente


def usar() -> str:
    return Cliente().obtener("k")
'''

USA_B = '''\
from paquete.b import Agenda


def otro():
    return Agenda().obtener(1)
'''

PRUEBA = '''\
from paquete.c import usar


def test_usar():
    assert usar() == "K"
'''


def escribir(raiz: Path, archivos: dict[str, str]) -> None:
    for ruta, contenido in archivos.items():
        destino = raiz / ruta
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(contenido, encoding="utf-8")


@pytest.fixture
def repo(tmp_path, monkeypatch):
    raiz = tmp_path / "repo"
    escribir(raiz, {
        "paquete/__init__.py": "",
        "paquete/a.py": MODULO_A,
        "paquete/b.py": MODULO_B,
        "paquete/c.py": USA_A,
        "paquete/d.py": USA_B,
        "tests/test_c.py": PRUEBA,
        "web/app.ts": "export function iniciar(): void {}\nexport class Vista {}\nexport interface Props {}\n"
                      "import { x } from './util';\n",
        "notas.txt": "no es codigo",
        "node_modules/lib/index.js": "function ignorada() {}",
    })
    monkeypatch.setenv("LYMI_CODIGO", str(tmp_path / "indices"))
    monkeypatch.chdir(tmp_path)
    return raiz


def indice(raiz: Path, **opciones) -> Indice:
    i = Indice(raiz, etiquetas=opciones.pop("etiquetas", Etiquetas()), **opciones)
    i.ultima = i.actualizar()
    return i


class TestExtraer:
    def test_python_exacto(self) -> None:
        ex = extraer(MODULO_A, "a.py", "python")
        assert ex.exacto and ex.error is None
        nombres = {(s.nombre, s.tipo) for s in ex.simbolos}
        assert {("Cliente", "clase"), ("Cliente.obtener", "metodo"), ("ayudante", "funcion")} <= nombres
        obtener = next(s for s in ex.simbolos if s.nombre == "Cliente.obtener")
        assert obtener.firma == "def obtener(self, clave: str) -> str"
        assert obtener.doc == "Devuelve el valor."
        assert (obtener.linea, obtener.linea_fin) == (9, 11)
        assert any(c.desde == "Cliente.obtener" and c.hacia == "_leer" for c in ex.llamadas)
        assert "LIMITE = ...  # L3" in ex.esqueleto
        assert "return" not in ex.esqueleto

    def test_importaciones_incluyen_submodulos(self) -> None:
        ex = extraer("from paquete import a\nfrom . import b\nimport os.path\n", "x.py", "python")
        assert {"paquete", "paquete.a", ".b", "os.path"} <= set(ex.importaciones)

    def test_python_invalido_no_revienta(self) -> None:
        ex = extraer("def roto(:\n", "x.py", "python")
        assert ex.error and not ex.simbolos

    def test_otros_lenguajes_son_aproximados(self) -> None:
        ex = extraer("export async function cargar(a) {}\nconst sumar = (a, b) => a + b\nclass Caja {}\n",
                     "x.js", "javascript")
        assert not ex.exacto
        assert [s.nombre for s in ex.simbolos] == ["cargar", "sumar", "Caja"]
        go = extraer("package x\n\nfunc (s *Srv) Servir(w int) {}\ntype Srv struct{}\n", "x.go", "go")
        assert [s.nombre for s in go.simbolos] == ["Servir", "Srv"]
        rs = extraer("pub async fn correr() {}\npub struct Motor;\nuse std::io;\n", "x.rs", "rust")
        assert [s.nombre for s in rs.simbolos] == ["correr", "Motor"] and rs.importaciones == ["std::io"]


class TestIndice:
    def test_indexa_y_reusa(self, repo) -> None:
        i = indice(repo)
        try:
            assert i.ultima.nuevos == 7  # 6 .py + 1 .ts; ni .txt ni node_modules
            assert i.actualizar().reusados == 7
        finally:
            i.cerrar()

    def test_cambios_borrados_y_mismo_contenido(self, repo) -> None:
        i = indice(repo)
        try:
            (repo / "paquete" / "b.py").write_text(MODULO_B + "\ndef nueva(): ...\n", encoding="utf-8")
            (repo / "paquete" / "d.py").unlink()
            a = repo / "paquete" / "a.py"
            os.utime(a, ns=(a.stat().st_atime_ns, a.stat().st_mtime_ns + 5_000_000_000))
            r = i.actualizar()
            assert (r.cambiados, r.borrados, r.reusados) == (1, 1, 5)
            assert i.buscar("nueva")[0]["ruta"] == "paquete/b.py"
        finally:
            i.cerrar()

    def test_lo_que_no_sale_no_se_indexa(self, repo) -> None:
        etiquetas = Etiquetas([Regla("b.py", Nivel.NUNCA_SALE)])
        i = indice(repo, etiquetas=etiquetas)
        try:
            assert "paquete/b.py" in i.ultima.omitidos
            assert i.buscar("Agenda") == []
        finally:
            i.cerrar()

    def test_version_nueva_reconstruye(self, repo, tmp_path) -> None:
        i = indice(repo)
        db = i.db
        i.cerrar()
        with sqlite3.connect(db) as conn:
            conn.execute("UPDATE meta SET valor = '0' WHERE clave = 'version'")
        i = indice(repo)
        try:
            assert i.ultima.nuevos == 7
        finally:
            i.cerrar()

    @pytest.mark.skipif(shutil.which("git") is None, reason="sin git")
    def test_respeta_gitignore(self, repo) -> None:
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        (repo / ".gitignore").write_text("paquete/b.py\n", encoding="utf-8")
        i = indice(repo)
        try:
            assert i.buscar("Agenda") == []
            assert i.buscar("Cliente")
        finally:
            i.cerrar()


class TestConsultas:
    def test_buscar_ordena_por_coincidencia_exacta(self, repo) -> None:
        i = indice(repo)
        try:
            resultados = i.buscar("obtener")
            assert [r["nombre"] for r in resultados] == ["Agenda.obtener", "Cliente.obtener"]
            assert i.buscar("vista")[0]["exacto"] is False
            assert i.buscar("100%_") == []
        finally:
            i.cerrar()

    @pytest.mark.parametrize("ruta", ["../repo/paquete/a.py", "/etc/passwd", "C:/Windows/win.ini", "notas.txt"])
    def test_esqueleto_solo_de_lo_indexado(self, repo, ruta) -> None:
        i = indice(repo)
        try:
            with pytest.raises(IndiceError, match="no esta en el indice"):
                i.esqueleto(ruta)
            assert "class Cliente" in i.esqueleto("./paquete/a.py")["esqueleto"]
        finally:
            i.cerrar()

    def test_fragmento_es_solo_el_simbolo(self, repo) -> None:
        i = indice(repo)
        try:
            (frag,) = i.fragmento("Cliente._leer")
            assert frag["codigo"].strip().startswith("def _leer") and "ayudante" not in frag["codigo"]
            texto = fmt.fragmentos([frag])
            assert len(texto.encode()) < frag["bytes_archivo"]
            (ts,) = i.fragmento("iniciar")
            assert ts["exacto"] is False and ts["linea_fin"] == 1
        finally:
            i.cerrar()

    def test_llamadores_confirmados_por_importacion(self, repo) -> None:
        i = indice(repo)
        try:
            por_ruta = {r["ruta"]: r["confirmado"] for r in i.llamadores("Cliente.obtener")}
            assert por_ruta == {"paquete/c.py": True, "paquete/d.py": False}
            texto = fmt.llamadores("Cliente.obtener", i.llamadores("Cliente.obtener"))
            assert "1 posibles homonimos" in texto
        finally:
            i.cerrar()

    def test_impacto_llega_a_las_pruebas_y_descarta_homonimos(self, repo) -> None:
        i = indice(repo)
        try:
            datos = i.impacto("Cliente.obtener")
            assert datos["niveles"][0] == [{"simbolo": "usar", "ruta": "paquete/c.py"}]
            assert datos["pruebas"] == ["tests/test_c.py"]
            assert datos["posibles"] == 1
            assert "paquete/d.py" not in datos["archivos"]
        finally:
            i.cerrar()

    def test_mapa_con_dependencias_internas(self, repo) -> None:
        i = indice(repo)
        try:
            datos = i.mapa("paquete")
            usa = {a["ruta"]: a["usa"] for a in datos["archivos"]}
            assert usa["paquete/c.py"] == ["paquete/a.py"]
            assert datos["total"] == 5
        finally:
            i.cerrar()


class TestCli:
    def test_esqueleto_muestra_el_ahorro_medido(self, repo) -> None:
        r = CliRunner().invoke(app, ["codigo", "esqueleto", "paquete/a.py", "--raiz", str(repo)])
        assert r.exit_code == 0, r.output
        assert "def obtener(self, clave: str) -> str" in r.output
        assert "menos)" in r.output

    def test_ruta_invalida(self, repo) -> None:
        r = CliRunner().invoke(app, ["codigo", "esqueleto", "../fuera.py", "--raiz", str(repo)])
        assert r.exit_code == 1


class TestPasoCodigo:
    def test_esquema_y_plan(self) -> None:
        with pytest.raises(ValueError, match="requiere nombre"):
            Workflow.model_validate({"name": "x", "steps": [{"id": "a", "type": "codigo", "op": "impacto"}]})
        flujo = Workflow.model_validate({"name": "x", "steps": [
            {"id": "a", "type": "codigo", "op": "esqueleto", "ruta": "src/x.py"}]})
        (fila,) = planificar(flujo)
        assert fila.costo == "gratis" and not fila.efectos

    def _flujo(self, raiz: str) -> Workflow:
        return Workflow.model_validate({"name": "x", "steps": [
            {"id": "mapa", "type": "codigo", "op": "impacto", "raiz": raiz, "nombre": "Cliente.obtener"}]})

    def test_en_un_workflow(self, repo, tmp_path) -> None:
        ledger = Ledger(tmp_path / "l.sqlite3")
        try:
            r = asyncio.run(ejecutar_flujo(self._flujo("repo"), {}, ledger=ledger))
            assert r.ok, r.detalle
            assert "tests/test_c.py" in r.salidas["mapa"]["texto"]
            fila = ledger.conn.execute("SELECT provider, egress FROM calls WHERE run_id = ?", (r.run_id,)).fetchone()
            assert (fila["provider"], fila["egress"]) == ("codigo", 0)
        finally:
            ledger.close()

    def test_raiz_fuera_del_perfil(self, repo, tmp_path) -> None:
        ledger = Ledger(tmp_path / "l.sqlite3")
        try:
            r = asyncio.run(ejecutar_flujo(self._flujo(str(tmp_path.parent)), {}, ledger=ledger))
            assert not r.ok and "fuera de las carpetas legibles" in r.pasos[0].detalle
        finally:
            ledger.close()


def test_servidor_mcp_real_por_stdio(repo, tmp_path) -> None:
    """El servidor se levanta como proceso y se le habla con el cliente MCP de lymi."""
    arranque = textwrap.dedent("""
        import sys
        from lymi.cli import app
        sys.argv = ["lymi", "codigo", "servir", "--raiz", sys.argv[1]]
        app()
    """)
    herramientas = ["buscar_simbolo", "esqueleto", "fragmento", "llamadores", "impacto", "mapa"]
    flujo = Workflow.model_validate({
        "name": "mcp_codigo",
        "integrations": {"codigo": {
            "type": "mcp", "command": sys.executable, "args": ["-c", arranque, str(repo)],
            "env": {"LYMI_CODIGO": str(tmp_path / "indices_mcp")}, "tools": herramientas,
        }},
        "steps": [
            {"id": "esq", "type": "tool", "integration": "codigo", "tool": "esqueleto",
             "args": {"ruta": "paquete/a.py"}, "side_effect": False},
            {"id": "imp", "type": "tool", "integration": "codigo", "tool": "impacto",
             "args": {"nombre": "Cliente.obtener"}, "side_effect": False},
            {"id": "fuera", "type": "tool", "integration": "codigo", "tool": "esqueleto",
             "args": {"ruta": "../../etc/passwd"}, "side_effect": False},
        ],
    })
    ledger = Ledger(tmp_path / "l.sqlite3")
    try:
        r = asyncio.run(ejecutar_flujo(flujo, {}, ledger=ledger))
    finally:
        ledger.close()
    assert r.ok, r.detalle
    assert "def obtener(self, clave: str) -> str" in r.salidas["esq"]
    assert "tests/test_c.py" in r.salidas["imp"]
    assert r.salidas["fuera"].startswith("error:") and "no esta en el indice" in r.salidas["fuera"]


def test_abrir_carga_sensibilidad_del_directorio_actual(repo, tmp_path) -> None:
    (tmp_path / "sensibilidad.yml").write_text("reglas:\n  - ruta: a.py\n    nivel: nunca-sale\n", encoding="utf-8")
    with abrir(repo) as i:
        assert i.buscar("Cliente") == []
