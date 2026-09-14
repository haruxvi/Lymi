"""Expresiones cron y calculo de la siguiente ejecucion.

Fechas de referencia (verificables en cualquier calendario): el 12 de septiembre
de 2026 es sabado; el 18, viernes; el 25 de octubre de 2026 es el ultimo domingo
de octubre, cuando Europa vuelve al horario de invierno.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from lymi.triggers.cron import CronError, parsear, zona_horaria


def utc(*partes: int) -> datetime:
    return datetime(*partes, tzinfo=UTC)


class TestSiguiente:
    def test_cada_quince_minutos(self) -> None:
        assert parsear("*/15 * * * *").siguiente(utc(2026, 9, 12, 10, 7)) == utc(2026, 9, 12, 10, 15)

    def test_estrictamente_posterior(self) -> None:
        assert parsear("0 10 * * *").siguiente(utc(2026, 9, 12, 10, 0)) == utc(2026, 9, 13, 10, 0)

    def test_dias_laborables_saltan_el_fin_de_semana(self) -> None:
        # Viernes 18 a las 10:00 -> lunes 21 a las 09:00.
        assert parsear("0 9 * * mon-fri").siguiente(utc(2026, 9, 18, 10, 0)) == utc(2026, 9, 21, 9, 0)

    def test_alias(self) -> None:
        assert parsear("@daily").siguiente(utc(2026, 9, 12, 10, 0)) == utc(2026, 9, 13, 0, 0)

    def test_cambio_de_mes(self) -> None:
        assert parsear("0 0 1 * *").siguiente(utc(2026, 1, 31, 12, 0)) == utc(2026, 2, 1, 0, 0)

    def test_29_de_febrero_espera_al_bisiesto(self) -> None:
        assert parsear("0 0 29 2 *").siguiente(utc(2026, 3, 1)) == utc(2028, 2, 29, 0, 0)

    def test_fecha_imposible(self) -> None:
        with pytest.raises(CronError, match="no ocurre"):
            parsear("0 0 31 2 *").siguiente(utc(2026, 1, 1))

    def test_dia_del_mes_o_dia_de_la_semana(self) -> None:
        # Ambos restringidos: basta cualquiera. El 13 (domingo) llega antes que el viernes 18,
        # y mucho antes que un viernes 13 (noviembre).
        assert parsear("0 0 13 * fri").siguiente(utc(2026, 9, 12)) == utc(2026, 9, 13, 0, 0)

    def test_solo_dia_de_la_semana(self) -> None:
        assert parsear("0 0 * * fri").siguiente(utc(2026, 9, 12)) == utc(2026, 9, 18, 0, 0)

    def test_siete_es_domingo(self) -> None:
        assert parsear("0 0 * * 7").siguiente(utc(2026, 9, 12)) == utc(2026, 9, 13, 0, 0)

    def test_desde_sin_zona_horaria(self) -> None:
        with pytest.raises(CronError, match="zona horaria"):
            parsear("* * * * *").siguiente(datetime(2026, 9, 12))  # noqa: DTZ001 - sin zona es lo que se prueba


class TestZonas:
    def test_hora_de_pared_en_tokio(self) -> None:
        # 00:00 UTC son las 09:00 en Tokio; la siguiente a las 09:00 es el dia siguiente.
        tokio = zona_horaria("Asia/Tokyo")
        assert parsear("0 9 * * *").siguiente(utc(2026, 9, 12, 0, 0), tokio) == utc(2026, 9, 13, 0, 0)

    def test_hora_repetida_por_cambio_de_horario_corre_una_vez(self) -> None:
        # El 25 de octubre de 2026 las 02:30 de Madrid ocurren dos veces.
        madrid = zona_horaria("Europe/Madrid")
        cron = parsear("30 2 * * *")
        primera = cron.siguiente(utc(2026, 10, 25, 0, 0), madrid)
        segunda = cron.siguiente(primera, madrid)
        assert primera == utc(2026, 10, 25, 0, 30)  # 02:30 en horario de verano
        assert segunda == utc(2026, 10, 26, 1, 30)  # dia siguiente, no una hora despues

    def test_utc_por_defecto(self) -> None:
        assert zona_horaria(None) is UTC
        assert zona_horaria("utc") is UTC

    def test_zona_desconocida(self) -> None:
        with pytest.raises(CronError, match="desconocida"):
            zona_horaria("Nada/Ninguna")


class TestParseo:
    def test_rango_con_paso(self) -> None:
        assert parsear("0-30/10 * * * *").minutos == frozenset({0, 10, 20, 30})

    def test_inicio_con_paso(self) -> None:
        assert parsear("5/15 * * * *").minutos == frozenset({5, 20, 35, 50})

    def test_listas(self) -> None:
        assert parsear("0 8,12,18 * * *").horas == frozenset({8, 12, 18})

    def test_nombres(self) -> None:
        cron = parsear("0 0 1 jan sun")
        assert cron.meses == frozenset({1})
        assert cron.dias_semana == frozenset({0})

    @pytest.mark.parametrize(
        ("expresion", "fragmento"),
        [
            ("* * * *", "5 campos"),
            ("61 * * * *", "fuera de rango"),
            ("* 24 * * *", "fuera de rango"),
            ("5-1 * * * *", "invertido"),
            ("*/0 * * * *", "paso invalido"),
            ("abc * * * *", "no es un numero"),
            ("1,,2 * * * *", "vacio"),
        ],
    )
    def test_errores_explican_que_campo_fallo(self, expresion: str, fragmento: str) -> None:
        with pytest.raises(CronError, match=fragmento):
            parsear(expresion)
