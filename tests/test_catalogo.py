"""Integraciones MCP: esquema ampliado e importador de catalogos.

Los manifiestos de estas pruebas son sinteticos, con la misma forma que el
catalogo de Hermes. La propiedad central: importar nunca ejecuta nada.
"""

from __future__ import annotations

import copy
import os
import subprocess

import pytest
import yaml
from pydantic import ValidationError

from lymi.flows.catalogo import CatalogoError, importar_datos, importar_manifiesto
from lymi.flows.schema import McpIntegration, Workflow

HTTP_OAUTH = {
    "manifest_version": 1,
    "name": "notas",
    "description": "Paginas de un espacio de notas.",
    "source": "https://ejemplo.com/docs/mcp",
    "transport": {"type": "http", "url": "https://mcp.ejemplo.com/mcp"},
    "auth": {"type": "oauth"},
    "tools": {"default_enabled": ["buscar", "leer_pagina"]},
}

STDIO_GIT = {
    "manifest_version": 1,
    "name": "flujos-n8n",
    "description": "Puente a una instancia de n8n.",
    "transport": {
        "type": "stdio",
        "command": "${INSTALL_DIR}/.venv/bin/python",
        "args": ["${INSTALL_DIR}/server.py"],
    },
    "install": {
        "type": "git",
        "url": "https://github.com/ejemplo/puente.git",
        "ref": "7a9ae00795593aa1fdb4e61ecd640e8bfd0c3841",
        "bootstrap": ["python3 -m venv .venv", ".venv/bin/pip install -r requirements.txt"],
    },
    "auth": {
        "type": "api_key",
        "env": [
            {"name": "N8N_BASE_URL", "prompt": "URL de n8n", "default": "http://127.0.0.1:5678", "secret": False},
            {"name": "N8N_API_KEY", "prompt": "Clave de API", "secret": True},
        ],
    },
    "tools": {"default_enabled": ["health", "list_workflows"]},
}


class TestImportador:
    def test_http_con_oauth(self) -> None:
        imp = importar_datos(HTTP_OAUTH)
        i = imp.integracion
        assert (i.transport, i.url, i.auth) == ("http", "https://mcp.ejemplo.com/mcp", "oauth")
        assert i.tools == ["buscar", "leer_pagina"]
        assert imp.instalacion_manual is None

    def test_variables_se_mapean_como_referencias_no_como_valores(self) -> None:
        imp = importar_datos(STDIO_GIT)
        assert imp.integracion.env == {
            "N8N_BASE_URL": "${N8N_BASE_URL}",
            "N8N_API_KEY": "${N8N_API_KEY}",
        }
        assert {v.nombre: v.secreta for v in imp.variables} == {
            "N8N_BASE_URL": False,
            "N8N_API_KEY": True,
        }

    def test_variable_sin_declarar_se_asume_secreta(self) -> None:
        datos = copy.deepcopy(STDIO_GIT)
        del datos["auth"]["env"][0]["secret"]
        assert importar_datos(datos).variables[0].secreta is True

    def test_nunca_ejecuta_el_bootstrap(self, monkeypatch) -> None:
        llamadas: list[tuple] = []
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: llamadas.append(a))
        monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: llamadas.append(a))
        monkeypatch.setattr(os, "system", lambda *a, **k: llamadas.append(a))

        imp = importar_datos(STDIO_GIT)

        assert llamadas == []
        # Se muestra para que una persona lo lea; no se corre.
        assert imp.instalacion_manual is not None
        assert "pip install" in imp.instalacion_manual
        assert "7a9ae00795593aa1fdb4e61ecd640e8bfd0c3841" in imp.instalacion_manual

    def test_install_dir_genera_aviso(self) -> None:
        assert any("INSTALL_DIR" in a for a in importar_datos(STDIO_GIT).avisos)

    def test_nombre_normalizado(self) -> None:
        imp = importar_datos(STDIO_GIT)
        assert imp.nombre == "flujos_n8n"
        assert any("ajustado" in a for a in imp.avisos)

    def test_git_sin_sha_completo_avisa(self) -> None:
        datos = copy.deepcopy(STDIO_GIT)
        datos["install"]["ref"] = "main"
        assert any("SHA completo" in a for a in importar_datos(datos).avisos)

    def test_sin_herramientas_por_defecto_avisa(self) -> None:
        datos = copy.deepcopy(HTTP_OAUTH)
        del datos["tools"]
        imp = importar_datos(datos)
        assert imp.integracion.tools is None
        assert any("todas habilitadas" in a for a in imp.avisos)

    def test_version_no_soportada(self) -> None:
        with pytest.raises(CatalogoError, match="manifest_version"):
            importar_datos({**HTTP_OAUTH, "manifest_version": 2})

    def test_http_plano_hacia_remoto_se_rechaza(self) -> None:
        datos = copy.deepcopy(HTTP_OAUTH)
        datos["transport"]["url"] = "http://mcp.ejemplo.com/mcp"
        with pytest.raises(CatalogoError, match="https"):
            importar_datos(datos)

    def test_transporte_desconocido(self) -> None:
        datos = copy.deepcopy(HTTP_OAUTH)
        datos["transport"]["type"] = "sse"
        with pytest.raises(CatalogoError, match="no soportado"):
            importar_datos(datos)

    def test_el_yaml_de_salida_vuelve_a_validar(self) -> None:
        imp = importar_datos(STDIO_GIT)
        datos = yaml.safe_load(imp.como_yaml())
        recargada = McpIntegration.model_validate(datos["flujos_n8n"])
        assert recargada.tools == ["health", "list_workflows"]

    def test_importar_desde_archivo(self, tmp_path) -> None:
        archivo = tmp_path / "manifest.yaml"
        archivo.write_text(yaml.safe_dump(HTTP_OAUTH), encoding="utf-8")
        assert importar_manifiesto(archivo).nombre == "notas"

    def test_archivo_inexistente(self, tmp_path) -> None:
        with pytest.raises(CatalogoError, match="no se pudo leer"):
            importar_manifiesto(tmp_path / "no-existe.yaml")


def _flujo(integraciones: dict, pasos: list[dict]) -> Workflow:
    return Workflow.model_validate({"name": "t", "integrations": integraciones, "steps": pasos})


class TestEsquemaMcp:
    def test_stdio_requiere_command(self) -> None:
        with pytest.raises(ValidationError, match="requiere command"):
            McpIntegration.model_validate({"type": "mcp"})

    def test_http_requiere_url(self) -> None:
        with pytest.raises(ValidationError, match="requiere url"):
            McpIntegration.model_validate({"type": "mcp", "transport": "http"})

    def test_http_no_admite_campos_de_stdio(self) -> None:
        with pytest.raises(ValidationError, match="solo aplican a transport stdio"):
            McpIntegration.model_validate(
                {"type": "mcp", "transport": "http", "url": "https://x.com/mcp", "command": "node"}
            )

    def test_stdio_no_admite_oauth(self) -> None:
        with pytest.raises(ValidationError, match="solo aplican a transport http"):
            McpIntegration.model_validate({"type": "mcp", "command": "node", "auth": "oauth"})

    def test_http_hacia_loopback_se_permite(self) -> None:
        McpIntegration.model_validate({"type": "mcp", "transport": "http", "url": "http://127.0.0.1:8080/mcp"})

    def test_herramienta_fuera_de_la_lista_blanca(self) -> None:
        with pytest.raises(ValidationError, match="no esta habilitada"):
            _flujo(
                {"crm": {"type": "mcp", "command": "node", "tools": ["buscar"]}},
                [{"id": "a", "type": "tool", "integration": "crm", "tool": "borrar_todo"}],
            )

    def test_herramienta_habilitada(self) -> None:
        _flujo(
            {"crm": {"type": "mcp", "command": "node", "tools": ["buscar"]}},
            [{"id": "a", "type": "tool", "integration": "crm", "tool": "buscar", "side_effect": False}],
        )
