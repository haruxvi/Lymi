"""Pruebas de saneamiento y redaccion.

La propiedad central: lo que el proveedor recibe no contiene el secreto ni el dato
personal, y lo que el usuario ve de vuelta si.
"""

from __future__ import annotations

import pytest

from lymi.privacidad import EgressBloqueado, Redactor, sanear, sanear_valor


class TestSaneamiento:
    def test_texto_normal_no_cambia(self) -> None:
        r = sanear("Hola, ¿cómo estás? Línea dos\n\ttabulada")
        assert r.texto == "Hola, ¿cómo estás? Línea dos\n\ttabulada"
        assert r.total == 0

    def test_quita_ancho_cero_y_bidi(self) -> None:
        r = sanear("ig\u200bnora\u202e esto\u2066")
        assert r.texto == "ignora esto"
        assert r.quitados == {"ancho_cero": 1, "bidi": 2}

    def test_quita_texto_escondido_en_tag_characters(self) -> None:
        # "ignore" codificado en U+E0000..E007F: invisible para una persona.
        escondido = "".join(chr(0xE0000 + ord(c)) for c in "ignore")
        r = sanear(f"documento inocente{escondido}")
        assert r.texto == "documento inocente"
        assert r.quitados == {"etiquetas_invisibles": 6}

    def test_quita_controles_ascii(self) -> None:
        r = sanear("a\x00b\x1bc")
        assert r.texto == "abc"
        assert r.quitados == {"control": 2}

    def test_sanea_estructuras(self) -> None:
        valor, total = sanear_valor({"t\u200bitulo": ["a\u202eb", 3, None], "n": 1})
        assert valor == {"titulo": ["ab", 3, None], "n": 1}
        assert total == 2


class TestRedaccion:
    @pytest.mark.parametrize(
        ("texto", "categoria"),
        [
            ("usa sk-ant-api03-AbCdEfGhIjKlMnOpQrStUvWxYz0123", "CLAVE_API"),
            ("AKIAIOSFODNN7EXAMPLE en la config", "CLAVE_API"),
            ("token ghp_" + "a" * 36, "TOKEN"),
            ("escribe a juana.perez@empresa.cl mañana", "EMAIL"),
            ("tarjeta 4111 1111 1111 1111", "TARJETA"),
            ("RUT 12.345.678-5", "RUT"),
            ("password = hunter2hunter2", "CREDENCIAL"),
            ("postgres://admin:SuperSecreta99@db.local/app", "CREDENCIAL"),
        ],
    )
    def test_detecta_y_redacta(self, texto, categoria) -> None:
        r = Redactor()
        salida = r.redactar(texto)
        assert r.conteo.get(categoria) == 1, (salida, r.conteo)
        assert f"⟦{categoria}_1_" in salida

    def test_el_valor_no_sale(self) -> None:
        r = Redactor()
        salida = r.redactar("mi clave es sk-ant-api03-SECRETOSECRETOSECRETO123 y mi correo ana@x.io")
        assert "SECRETOSECRETO" not in salida
        assert "ana@x.io" not in salida

    def test_rehidrata_la_respuesta(self) -> None:
        r = Redactor()
        enviado = r.redactar("Responde a ana@x.io")
        marcador = enviado.split()[-1]
        assert r.rehidratar(f"Listo, escribi a {marcador}.") == "Listo, escribi a ana@x.io."

    def test_mismo_valor_mismo_marcador(self) -> None:
        r = Redactor()
        salida = r.redactar("ana@x.io y otra vez ana@x.io, y beto@x.io")
        marcadores = [p.strip(",.") for p in salida.split() if p.startswith("⟦")]
        assert marcadores[0] == marcadores[1] != marcadores[2]
        assert r.conteo["EMAIL"] == 3

    def test_solo_el_valor_de_una_asignacion(self) -> None:
        r = Redactor()
        salida = r.redactar("password: hunter2hunter2")
        assert salida.startswith("password: ⟦CREDENCIAL_1_")

    def test_un_marcador_ajeno_no_se_rehidrata(self) -> None:
        # Un documento que ya trae un marcador inventado no debe hacer que lymi
        # escriba en la respuesta un valor real de otra redaccion.
        r = Redactor()
        r.redactar("ana@x.io")
        falso = f"⟦EMAIL_1_{'0000' if r.sufijo != '0000' else '1111'}⟧"
        assert r.rehidratar(falso) == falso

    def test_numeros_que_no_pasan_luhn_ni_digito_verificador(self) -> None:
        r = Redactor()
        texto = "pedido 4111 1111 1111 1112 y codigo 12.345.678-9"
        assert r.redactar(texto) == texto
        assert r.total == 0

    def test_no_redacta_dos_veces(self) -> None:
        r = Redactor()
        salida = r.redactar("token: sk-ant-api03-AbCdEfGhIjKlMnOpQrStUvWxYz0123")
        assert r.conteo == {"CLAVE_API": 1}
        assert salida.count("⟦") == 1

    def test_una_clave_privada_bloquea(self) -> None:
        clave = "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXk=\n-----END OPENSSH PRIVATE KEY-----"
        with pytest.raises(EgressBloqueado, match="clave privada"):
            Redactor().redactar(f"mira mi config:\n{clave}")

    def test_texto_sin_nada_sensible(self) -> None:
        r = Redactor()
        texto = "Refactoriza AuthService para emitir tokens rotativos."
        assert r.redactar(texto) == texto
        assert r.rehidratar(texto) == texto
