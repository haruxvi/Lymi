"""Pruebas de las etiquetas de sensibilidad y su bloqueo en la pasarela."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from lymi.cli_flow import _entradas_etiquetadas
from lymi.flows.engine import correr
from lymi.flows.schema import Workflow
from lymi.ledger import Billing, Ledger
from lymi.privacidad.etiquetas import (
    EtiquetaError,
    Etiquetas,
    Nivel,
    Regla,
    cargar_etiquetas,
    fragmentos_protegidos,
)
from lymi.providers.base import Completion, Usage

CONTRATO = (
    "CONTRATO DE CONFIDENCIALIDAD ENTRE ACME Y CLIENTE A\n"
    "La tarifa acordada es de 48.000 dolares anuales por el servicio completo.\n"
    "ok\n"
)


class Espia:
    provider = "espia"
    model = "claude-opus-5"
    tier = "frontier"

    def __init__(self, billing: Billing) -> None:
        self.billing = billing
        self.recibido: list[str] = []

    def complete(self, messages, *, system=None, max_tokens=4096, cache_system=False) -> Completion:
        self.recibido.append(messages[-1].content)
        return Completion(text="resumen breve", usage=Usage(input_tokens=10, output_tokens=5), model=self.model,
                          provider=self.provider, billing=self.billing, tier=self.tier, latency_ms=1)


class TestNiveles:
    @pytest.mark.parametrize("ruta", [".env", "config/.env.local", "llaves/servidor.pem", "id_rsa", "home/.ssh/config", "claves.kdbx"])
    def test_el_piso_fijo(self, ruta) -> None:
        # Ni una regla explicita lo baja.
        etiquetas = Etiquetas([Regla("*", Nivel.PUBLICO)])
        assert etiquetas.nivel_de(Path(ruta)) is Nivel.NUNCA_SALE

    def test_la_primera_regla_gana(self) -> None:
        etiquetas = Etiquetas([Regla("contratos/*", Nivel.NUNCA_SALE), Regla("*.txt", Nivel.PUBLICO)])
        assert etiquetas.nivel_de(Path("contratos/a.txt")) is Nivel.NUNCA_SALE
        assert etiquetas.nivel_de(Path("notas/a.txt")) is Nivel.PUBLICO

    def test_por_defecto_interno(self) -> None:
        assert Etiquetas().nivel_de(Path("notas.md")) is Nivel.INTERNO

    def test_cargar_desde_yaml(self, tmp_path) -> None:
        archivo = tmp_path / "sensibilidad.yml"
        archivo.write_text(yaml.safe_dump({"por_defecto": "confidencial",
                                           "reglas": [{"ruta": "publico/*", "nivel": "publico"}]}), encoding="utf-8")
        etiquetas = cargar_etiquetas(archivo)
        assert etiquetas.por_defecto is Nivel.CONFIDENCIAL
        assert etiquetas.nivel_de(Path("publico/x.md")) is Nivel.PUBLICO

    def test_sin_archivo_solo_rige_el_piso(self, tmp_path) -> None:
        assert cargar_etiquetas(tmp_path / "no-existe.yml").reglas == []

    @pytest.mark.parametrize("contenido", ["reglas: [{ruta: x}]", "reglas: [{ruta: x, nivel: secretisimo}]", "reglas: nada"])
    def test_yaml_invalido(self, tmp_path, contenido) -> None:
        archivo = tmp_path / "sensibilidad.yml"
        archivo.write_text(contenido, encoding="utf-8")
        with pytest.raises(EtiquetaError):
            cargar_etiquetas(archivo)

    def test_fragmentos_ignoran_lineas_cortas(self) -> None:
        fragmentos = fragmentos_protegidos(CONTRATO)
        assert "ok" not in fragmentos
        assert "La tarifa acordada es de 48.000 dolares anuales por el servicio completo." in fragmentos


class TestEntradas:
    def test_un_archivo_nunca_sale_queda_protegido(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        (tmp_path / "contratos").mkdir()
        (tmp_path / "contratos" / "a.txt").write_text(CONTRATO, encoding="utf-8")
        etiquetas = Etiquetas([Regla("contratos/*", Nivel.NUNCA_SALE)])

        valores, protegidos, avisos = _entradas_etiquetadas(["doc=@contratos/a.txt", "tono=formal"], etiquetas)
        assert valores["doc"] == CONTRATO
        assert protegidos
        assert len(avisos) == 1 and "nunca-sale" in avisos[0]

    def test_valores_escritos_a_mano_no_se_protegen(self) -> None:
        _, protegidos, avisos = _entradas_etiquetadas(["tono=formal"], Etiquetas())
        assert protegidos == () and avisos == []


def _flujo(tier: str) -> Workflow:
    return Workflow.model_validate({
        "name": "resumir",
        "inputs": {"doc": {"type": "string"}},
        "steps": [{"id": "resumir", "type": "llm", "tier": tier, "prompt": "Resume: {{ inputs.doc }}"}],
    })


class TestBloqueo:
    def test_no_llega_al_modelo_remoto(self, tmp_path) -> None:
        remoto = Espia(Billing.API)
        ledger = Ledger(tmp_path / "l.sqlite3")
        try:
            resultado = correr(_flujo("remote"), {"doc": CONTRATO}, ledger=ledger, remote=remoto,
                               protegidos=fragmentos_protegidos(CONTRATO))
        finally:
            ledger.close()
        assert not resultado.ok
        assert "archivo nunca sale" in resultado.pasos[0].detalle
        assert remoto.recibido == []

    def test_el_modelo_local_si_lo_lee(self, tmp_path) -> None:
        local = Espia(Billing.LOCAL)
        ledger = Ledger(tmp_path / "l.sqlite3")
        try:
            resultado = correr(_flujo("local"), {"doc": CONTRATO}, ledger=ledger, local=local,
                               protegidos=fragmentos_protegidos(CONTRATO))
        finally:
            ledger.close()
        assert resultado.ok, resultado.detalle
        assert "48.000 dolares" in local.recibido[0]

    def test_una_linea_suelta_tambien_se_bloquea(self, tmp_path) -> None:
        # Copiar solo la linea sensible dentro de otro texto no la deja salir.
        remoto = Espia(Billing.API)
        linea = "La tarifa acordada es de 48.000 dolares anuales por el servicio completo."
        ledger = Ledger(tmp_path / "l.sqlite3")
        try:
            resultado = correr(_flujo("remote"), {"doc": f"Contexto: {linea} Gracias."}, ledger=ledger,
                               remote=remoto, protegidos=fragmentos_protegidos(CONTRATO))
        finally:
            ledger.close()
        assert not resultado.ok
        assert remoto.recibido == []

    def test_http_no_lo_envia(self, tmp_path) -> None:
        flujo = Workflow.model_validate({
            "name": "aviso",
            "inputs": {"doc": {"type": "string"}},
            "integrations": {"api": {"type": "http", "allow_hosts": ["api.ejemplo.com"]}},
            "steps": [{"id": "enviar", "type": "http", "integration": "api", "method": "POST",
                       "url": "https://api.ejemplo.com/x", "body": {"texto": "{{ inputs.doc }}"}}],
        })
        ledger = Ledger(tmp_path / "l.sqlite3")
        try:
            resultado = correr(flujo, {"doc": CONTRATO}, ledger=ledger, aprobar=lambda *_: True,
                               protegidos=fragmentos_protegidos(CONTRATO))
        finally:
            ledger.close()
        assert not resultado.ok
        assert resultado.pasos[0].status == "fallo"
        assert "archivo nunca sale" in resultado.pasos[0].detalle
