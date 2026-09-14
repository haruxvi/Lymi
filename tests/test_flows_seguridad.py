"""Seguridad de plantillas y condiciones.

Un workflow procesa texto ajeno por definicion: correos, paginas, salidas de
modelos. Estas pruebas fijan que ese texto nunca puede ejecutar codigo ni leer lo
que no debe.
"""

from __future__ import annotations

import pytest

from lymi.flows import condition, template
from lymi.flows.condition import ConditionError
from lymi.flows.template import TemplateError

CTX = {
    "inputs": {"correo": "hola", "secreto": "NO-DEBE-SALIR"},
    "steps": {
        "extraer": {
            "output": {"empresa": "Acme", "presupuesto": 5000, "tags": ["b2b", "urgente"]},
            "status": "ok",
        },
        "clasificar": {"output": {"score": 0.9}, "status": "ok"},
        "vacio": {"output": None, "status": "omitido"},
    },
}


class TestPlantillas:
    def test_interpola_texto(self) -> None:
        assert template.render("Empresa: {{ steps.extraer.output.empresa }}", CTX) == "Empresa: Acme"

    def test_plantilla_unica_conserva_el_tipo(self) -> None:
        assert template.render("{{ steps.extraer.output.presupuesto }}", CTX) == 5000
        assert template.render("{{ steps.extraer.output }}", CTX) == CTX["steps"]["extraer"]["output"]

    def test_mezclada_serializa_como_json(self) -> None:
        assert template.render("x={{ steps.extraer.output.tags }}", CTX) == 'x=["b2b", "urgente"]'

    def test_indices_de_lista(self) -> None:
        assert template.render("{{ steps.extraer.output.tags.1 }}", CTX) == "urgente"

    def test_recorre_diccionarios_y_listas(self) -> None:
        assert template.render({"a": ["{{ inputs.correo }}"]}, CTX) == {"a": ["hola"]}

    def test_ruta_inexistente_falla_fuerte(self) -> None:
        with pytest.raises(TemplateError, match="no existe"):
            template.render("{{ steps.extraer.output.cargo }}", CTX)

    @pytest.mark.parametrize(
        "malicioso",
        [
            "{{ __import__('os').system('calc') }}",
            "{{ inputs.correo.upper() }}",
            "{{ 1 + 1 }}",
            "{{ inputs.correo | safe }}",
            "{{ steps._privado }}",
        ],
    )
    def test_solo_admite_rutas(self, malicioso: str) -> None:
        with pytest.raises(TemplateError):
            template.render(malicioso, CTX)

    def test_una_sola_pasada(self) -> None:
        # La salida de un modelo que contiene una plantilla NO se vuelve a expandir.
        ctx = {"inputs": {"secreto": "NO-DEBE-SALIR"}, "steps": {"llm": {"output": "{{ inputs.secreto }}"}}}
        resultado = template.render("Respuesta: {{ steps.llm.output }}", ctx)
        assert resultado == "Respuesta: {{ inputs.secreto }}"
        assert "NO-DEBE-SALIR" not in resultado

    def test_no_entra_en_objetos_de_python(self) -> None:
        with pytest.raises(TemplateError):
            template.render("{{ inputs.correo.length }}", CTX)

    def test_referencias(self) -> None:
        refs = template.referencias({"p": "{{ inputs.correo }} y {{ steps.extraer.output }}"})
        assert refs == {"inputs.correo", "steps.extraer.output"}


class TestCondiciones:
    def test_comparacion(self) -> None:
        assert condition.evaluar("steps.clasificar.output.score > 0.7", CTX) is True
        assert condition.evaluar("steps.clasificar.output.score > 0.95", CTX) is False

    def test_logica(self) -> None:
        expr = "steps.clasificar.output.score > 0.7 and not steps.extraer.output.presupuesto < 1000"
        assert condition.evaluar(expr, CTX) is True

    def test_pertenencia(self) -> None:
        assert condition.evaluar("'urgente' in steps.extraer.output.tags", CTX) is True

    def test_subindices_literales(self) -> None:
        assert condition.evaluar("steps['extraer'].output['empresa'] == 'Acme'", CTX) is True

    def test_clave_ausente_es_falso_no_excepcion(self) -> None:
        assert condition.evaluar("steps.clasificar.output.inexistente > 0.7", CTX) is False

    def test_paso_omitido_es_falso(self) -> None:
        assert condition.evaluar("steps.vacio.output.score > 0.7", CTX) is False

    def test_tipos_incomparables_son_falso(self) -> None:
        assert condition.evaluar("steps.extraer.output.empresa > 3", CTX) is False

    @pytest.mark.parametrize(
        "malicioso",
        [
            "__import__('os').system('calc')",
            "steps.__class__",
            "().__class__.__bases__",
            "(lambda: 1)()",
            "[x for x in steps]",
            "2 ** 10 ** 10",
            "open('secreto.txt')",
            "globals()",
            "inputs.correo.upper()",
            "'abc'.upper",
            "os.environ",
            "steps[inputs.correo]",
        ],
    )
    def test_rechaza_lo_que_no_esta_en_la_lista_blanca(self, malicioso: str) -> None:
        with pytest.raises(ConditionError):
            condition.evaluar(malicioso, CTX)

    def test_limite_de_largo(self) -> None:
        with pytest.raises(ConditionError, match="supera"):
            condition.evaluar("1 == 1 and " * 40 + "True", CTX)

    def test_vacia(self) -> None:
        with pytest.raises(ConditionError):
            condition.evaluar("   ", CTX)

    def test_referencias(self) -> None:
        refs = condition.referencias("steps.clasificar.output.score > 0.7")
        assert "steps.clasificar.output.score" in refs

    def test_validar_sin_contexto(self) -> None:
        condition.validar("steps.x.output.score > 0.7 and inputs.y == 'z'")

    def test_validar_rechaza_llamadas(self) -> None:
        with pytest.raises(ConditionError):
            condition.validar("len(steps) > 2")
