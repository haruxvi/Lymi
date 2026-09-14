"""Pruebas del recibo.

El invariante que importa mas que ningun otro en este proyecto: **nunca se
anuncia un ahorro si alguna corrida fallo su puerta**. Si estas pruebas pasan a
rojo, lymi se convirtio en lo que dice combatir.
"""

from __future__ import annotations

import pytest

from lymi.bench.report import Receipt, render_card_html, render_terminal
from lymi.bench.runner import RunOutcome
from lymi.bench.tasks import GateResult


def _outcome(
    run_id: str, *, passed: bool, remote: int, local: int = 0, cost: float | None = 0.05
) -> RunOutcome:
    return RunOutcome(
        run_id=run_id,
        task_id="snake",
        variant="x",
        gate=GateResult(passed, 1.0 if passed else 0.0, "ok" if passed else "el juego no arranca"),
        totals={
            "remote_tokens": remote,
            "local_tokens": local,
            "cost_usd": cost,
            "unpriced_calls": 0,
        },
    )


def _recibo(base_ok: bool = True, test_ok: bool = True, **kw) -> Receipt:
    return Receipt(
        task_id="snake",
        task_title="Snake en Python",
        base=_outcome("base01", passed=base_ok, remote=kw.get("base_remote", 70_000), cost=0.35),
        test=_outcome("test01", passed=test_ok, remote=kw.get("test_remote", 9_000),
                      local=kw.get("local", 140_000), cost=0.04),
        demo=kw.get("demo", False),
    )


class TestReglaDeHonestidad:
    def test_anuncia_ahorro_solo_si_ambas_pasaron(self) -> None:
        r = _recibo(base_ok=True, test_ok=True)
        assert r.ahorro == pytest.approx(1 - 9_000 / 70_000)

    def test_si_lymi_falla_no_hay_ahorro(self) -> None:
        r = _recibo(test_ok=False)
        assert r.ahorro is None
        assert "lymi fallo" in r.motivo_sin_ahorro

    def test_si_la_linea_base_falla_no_hay_ahorro(self) -> None:
        r = _recibo(base_ok=False)
        assert r.ahorro is None
        assert "linea base" in r.motivo_sin_ahorro

    def test_el_texto_nunca_muestra_porcentaje_si_fallo(self) -> None:
        salida = render_terminal(_recibo(test_ok=False), unicode_ok=False)
        assert "SIN AHORRO ANUNCIABLE" in salida
        assert "%" not in salida

    def test_la_tarjeta_nunca_muestra_porcentaje_si_fallo(self) -> None:
        html = render_card_html(_recibo(test_ok=False))
        assert "sin ahorro" in html
        assert "&minus;" not in html

    def test_linea_base_sin_tokens_no_produce_division_por_cero(self) -> None:
        assert _recibo(base_remote=0).ahorro is None


class TestSelloDeDemo:
    def test_el_modo_demo_se_estampa_en_la_terminal(self) -> None:
        assert "MODO DEMO" in render_terminal(_recibo(demo=True), unicode_ok=False)

    def test_el_modo_demo_se_estampa_en_la_tarjeta(self) -> None:
        assert "MODO DEMO" in render_card_html(_recibo(demo=True))

    def test_sin_demo_no_hay_sello(self) -> None:
        assert "MODO DEMO" not in render_terminal(_recibo(demo=False), unicode_ok=False)


class TestVerificabilidad:
    def test_el_recibo_lleva_los_identificadores_de_corrida(self) -> None:
        salida = render_terminal(_recibo(), unicode_ok=False)
        assert "base01" in salida and "test01" in salida

    def test_el_recibo_lleva_el_comando_para_reproducirlo(self) -> None:
        assert "lymi bench snake" in render_terminal(_recibo(), unicode_ok=False)

    def test_la_tarjeta_tambien(self) -> None:
        html = render_card_html(_recibo())
        assert "base01" in html and "lymi bench snake" in html


class TestFormato:
    def test_todas_las_filas_miden_lo_mismo(self) -> None:
        # Un recibo desalineado es un recibo que nadie va a mostrar.
        lineas = render_terminal(_recibo(demo=True), unicode_ok=False).splitlines()
        anchos = {len(x) for x in lineas}
        assert len(anchos) == 1, f"filas de anchos distintos: {sorted(anchos)}"

    def test_el_respaldo_ascii_no_usa_caracteres_de_caja(self) -> None:
        salida = render_terminal(_recibo(), unicode_ok=False)
        assert not any(c in salida for c in "╭╮╰╯─│█")

    def test_reporta_los_tokens_locales(self) -> None:
        assert "140.0k tok en local" in render_terminal(_recibo(), unicode_ok=False)


def _recibo_con(base: dict, test: dict, *, base_ok: bool = True, test_ok: bool = True) -> Receipt:
    """Recibo con totales arbitrarios encima de los de `_outcome`."""
    b = _outcome("base01", passed=base_ok, remote=70_000, cost=None)
    t = _outcome("test01", passed=test_ok, remote=9_000, local=140_000, cost=None)
    b.totals.update(base)
    t.totals.update(test)
    return Receipt(task_id="snake", task_title="Snake en Python", base=b, test=t)


class TestContabilidadHonesta:
    def test_cache_calentada_por_la_linea_base_no_se_anuncia(self) -> None:
        # La linea base corre primero y deja el prefijo en cache: lymi lo lee
        # barato. Ese ahorro es del orden de ejecucion, no de lymi.
        r = _recibo_con({"cache_read_tokens": 0}, {"cache_read_tokens": 11_868})
        assert r.ahorro is None
        assert "cache" in r.motivo_sin_ahorro
        assert "%" not in render_terminal(r, unicode_ok=False)

    def test_cache_simetrica_si_permite_anunciar(self) -> None:
        r = _recibo_con({"cache_read_tokens": 5_000}, {"cache_read_tokens": 5_000})
        assert r.ahorro is not None

    def test_suscripcion_no_se_confunde_con_tarifa_desconocida(self) -> None:
        r = _recibo_con({"billing_mode": "subscription"}, {"billing_mode": "subscription"})
        salida = render_terminal(r, unicode_ok=False)
        assert "suscr." in salida
        assert "n/d" not in salida
        assert "no en dolares" in salida

    def test_sin_suscripcion_el_costo_ausente_es_dato_faltante(self) -> None:
        r = _recibo_con({"billing_mode": "api"}, {"billing_mode": "api"})
        assert "n/d" in render_terminal(r, unicode_ok=False)

    def test_declara_las_llamadas_que_salieron(self) -> None:
        r = _recibo_con({}, {"egress_calls": 1})
        salida = render_terminal(r, unicode_ok=False)
        assert "1 llamadas de lymi si salieron" in salida
        assert "0 salieron" not in salida

    def test_declara_cuanto_del_remoto_es_cache(self) -> None:
        r = _recibo_con({"remote_cache_tokens": 41_807}, {"remote_cache_tokens": 24_274})
        assert "66.1k de cache" in render_terminal(r, unicode_ok=False)

    def test_las_lineas_nuevas_no_desalinean(self) -> None:
        r = _recibo_con(
            {"billing_mode": "subscription", "remote_cache_tokens": 41_807},
            {"billing_mode": "subscription", "egress_calls": 1, "cache_read_tokens": 11_868},
        )
        anchos = {len(x) for x in render_terminal(r, unicode_ok=False).splitlines()}
        assert len(anchos) == 1
