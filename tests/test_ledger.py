"""Pruebas del ledger.

La propiedad que importa: es imposible que una llamada quede fuera del registro,
y es imposible que el payload quede persistido.
"""

from __future__ import annotations

from hashlib import sha256

import pytest

from lymi.ledger import Billing, CallRecord, Ledger


@pytest.fixture
def ledger(tmp_path):
    led = Ledger(tmp_path / "test.sqlite3")
    yield led
    led.close()


def _call(**kw) -> CallRecord:
    base = {"provider": "anthropic", "model": "claude-opus-5", "billing": Billing.API}
    return CallRecord(**(base | kw))


class TestCicloDeCorrida:
    def test_corrida_exitosa_queda_cerrada(self, ledger: Ledger) -> None:
        with ledger.run("snake", "baseline", Billing.API) as run:
            run.record(_call(input_tokens=1000, output_tokens=500))
            run.score = 1.0
        t = ledger.totals(run.run_id)
        assert t is not None
        assert t["status"] == "passed"
        assert t["score"] == 1.0
        assert t["n_calls"] == 1

    def test_excepcion_marca_error_y_se_relanza(self, ledger: Ledger) -> None:
        with pytest.raises(ValueError), ledger.run("snake", "baseline", Billing.API) as run:
            run.record(_call())
            raise ValueError("fallo simulado")
        t = ledger.totals(run.run_id)
        assert t is not None
        assert t["status"] == "error"
        # La llamada previa al fallo NO se pierde: sin eso el costo quedaria subestimado.
        assert t["n_calls"] == 1

    def test_fail_marca_la_corrida(self, ledger: Ledger) -> None:
        with ledger.run("snake", "baseline", Billing.API) as run:
            run.record(_call())
            run.fail("el juego no arranca")
        assert ledger.totals(run.run_id)["status"] == "failed"

    def test_secuencia_de_llamadas_es_ordinal(self, ledger: Ledger) -> None:
        with ledger.run("repo", "baseline", Billing.API) as run:
            for _ in range(5):
                run.record(_call())
        rows = ledger.conn.execute(
            "SELECT seq FROM calls WHERE run_id = ? ORDER BY seq", (run.run_id,)
        ).fetchall()
        assert [r["seq"] for r in rows] == [1, 2, 3, 4, 5]


class TestPrivacidadDelPayload:
    def test_el_payload_nunca_se_persiste(self, ledger: Ledger) -> None:
        secreto = "CLAVE_PRIVADA_DEL_USUARIO_12345"
        with ledger.run("research", "baseline", Billing.API) as run:
            run.record(_call(payload=secreto, egress=True))

        # El texto no puede aparecer en ninguna columna de ninguna tabla.
        volcado = "".join(ledger.conn.iterdump())
        assert secreto not in volcado

    def test_guarda_hash_y_tamano_para_auditoria(self, ledger: Ledger) -> None:
        payload = "hola mundo"
        with ledger.run("research", "baseline", Billing.API) as run:
            run.record(_call(payload=payload, egress=True))
        row = ledger.conn.execute(
            "SELECT payload_sha256, payload_bytes, egress FROM calls WHERE run_id = ?",
            (run.run_id,),
        ).fetchone()
        assert row["payload_sha256"] == sha256(payload.encode()).hexdigest()
        assert row["payload_bytes"] == len(payload.encode())
        assert row["egress"] == 1

    def test_sin_payload_no_hay_hash(self, ledger: Ledger) -> None:
        with ledger.run("snake", "baseline", Billing.API) as run:
            run.record(_call())
        row = ledger.conn.execute(
            "SELECT payload_sha256 FROM calls WHERE run_id = ?", (run.run_id,)
        ).fetchone()
        assert row["payload_sha256"] is None


class TestTotales:
    def test_separa_tokens_locales_de_remotos(self, ledger: Ledger) -> None:
        with ledger.run("research", "p3-local", Billing.API) as run:
            run.record(_call(input_tokens=1000, output_tokens=200))
            run.record(
                _call(
                    provider="ollama",
                    model="qwen3:4b",
                    billing=Billing.LOCAL,
                    tier="local",
                    input_tokens=80_000,
                    output_tokens=4_000,
                )
            )
        t = ledger.totals(run.run_id)
        assert t["remote_tokens"] == 1200
        assert t["local_tokens"] == 84_000

    def test_cuenta_llamadas_sin_tarifa(self, ledger: Ledger) -> None:
        with ledger.run("snake", "baseline", Billing.API) as run:
            run.record(_call(model="modelo-fantasma", input_tokens=1000))
            run.record(_call(input_tokens=1000))
        # Si esto no es 0, el costo reportado esta incompleto y hay que declararlo.
        assert ledger.totals(run.run_id)["unpriced_calls"] == 1

    def test_suscripcion_no_contamina_el_costo_en_dolares(self, ledger: Ledger) -> None:
        with ledger.run("snake", "harness", Billing.SUBSCRIPTION) as run:
            run.record(
                _call(
                    provider="claude-code",
                    billing=Billing.SUBSCRIPTION,
                    input_tokens=50_000,
                    output_tokens=3_000,
                )
            )
        t = ledger.totals(run.run_id)
        assert t["cost_usd"] is None          # no comparable con el modo api
        assert t["remote_tokens"] == 53_000   # pero los tokens si se miden

    def test_cache_abarata_la_corrida(self, ledger: Ledger) -> None:
        with ledger.run("repo", "sin-cache", Billing.API) as a:
            a.record(_call(input_tokens=100_000))
        with ledger.run("repo", "con-cache", Billing.API) as b:
            b.record(_call(input_tokens=0, cache_read_tokens=100_000))
        assert ledger.totals(b.run_id)["cost_usd"] < ledger.totals(a.run_id)["cost_usd"]

    def test_la_cache_cuenta_como_consumo_remoto(self, ledger: Ledger) -> None:
        # Cifras de la primera corrida real: el recibo mostraba 3.1k tokens
        # remotos cuando el proveedor proceso 44.9k. El resto era el prefijo del
        # harness, escrito en cache.
        with ledger.run("snake", "baseline", Billing.SUBSCRIPTION) as run:
            run.record(
                _call(
                    provider="claude-code",
                    billing=Billing.SUBSCRIPTION,
                    input_tokens=2,
                    output_tokens=3_139,
                    cache_write_tokens=41_807,
                )
            )
        t = ledger.totals(run.run_id)
        assert t["remote_tokens"] == 44_948
        assert t["remote_cache_tokens"] == 41_807

    def test_la_cache_local_no_es_remota(self, ledger: Ledger) -> None:
        with ledger.run("snake", "local", Billing.LOCAL) as run:
            run.record(_call(provider="ollama", billing=Billing.LOCAL, tier="local", cache_read_tokens=500))
        assert ledger.totals(run.run_id)["remote_cache_tokens"] == 0

    def test_costo_parcial_no_se_presenta_como_total(self, ledger: Ledger) -> None:
        # Una llamada con tarifa y otra sin ella: SUM daria el costo de la
        # primera como si fuera el de la corrida entera.
        with ledger.run("snake", "mixta", Billing.API) as run:
            run.record(_call(input_tokens=1_000))
            run.record(_call(provider="claude-code", billing=Billing.SUBSCRIPTION, input_tokens=1_000))
        assert ledger.totals(run.run_id)["cost_usd"] is None

    def test_la_vista_vieja_se_reemplaza_al_abrir(self, tmp_path) -> None:
        # Una base creada con la formula anterior tiene que pasar a la nueva.
        ruta = tmp_path / "vieja.sqlite3"
        led = Ledger(ruta)
        led.conn.execute("DROP VIEW run_totals")
        led.conn.execute("CREATE VIEW run_totals AS SELECT id AS run_id FROM runs")
        led.close()

        led = Ledger(ruta)
        try:
            columnas = [r[1] for r in led.conn.execute("PRAGMA table_info(run_totals)")]
        finally:
            led.close()
        assert "remote_cache_tokens" in columnas
