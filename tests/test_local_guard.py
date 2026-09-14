"""Pruebas de seguridad del tier local.

Un tier llamado "local" que apunte a un host remoto es una fuga de datos
disfrazada de privacidad. Esta guarda es la que impide que lymi cometa
exactamente la mentira que denuncia.
"""

from __future__ import annotations

import socket

import pytest

from lymi.providers.local import NonLocalEndpointError, assert_loopback


def _fake_getaddrinfo(ip: str):
    def _inner(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 11434))]

    return _inner


class TestAssertLoopback:
    def test_acepta_localhost(self, monkeypatch) -> None:
        monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("127.0.0.1"))
        assert_loopback("http://localhost:11434")

    def test_acepta_ipv6_loopback(self, monkeypatch) -> None:
        monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("::1"))
        assert_loopback("http://[::1]:11434")

    def test_rechaza_host_remoto(self, monkeypatch) -> None:
        monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("203.0.113.7"))
        with pytest.raises(NonLocalEndpointError, match="no es loopback"):
            assert_loopback("http://ollama.ejemplo.com:11434")

    def test_rechaza_ip_privada_de_otra_maquina(self, monkeypatch) -> None:
        # Una IP de LAN no es esta maquina: los datos igual salen del equipo.
        monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("192.168.1.50"))
        with pytest.raises(NonLocalEndpointError):
            assert_loopback("http://192.168.1.50:11434")

    def test_detecta_localhost_reapuntado_en_hosts(self, monkeypatch) -> None:
        # 'localhost' se puede reapuntar en el archivo hosts. Comparar por texto
        # no lo detectaria; resolver el nombre si.
        monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("203.0.113.9"))
        with pytest.raises(NonLocalEndpointError):
            assert_loopback("http://localhost:11434")

    def test_opt_in_explicito_permite_remoto(self, monkeypatch) -> None:
        monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("203.0.113.7"))
        assert_loopback("http://remoto:11434", allow_remote=True)

    def test_url_sin_host_falla(self) -> None:
        with pytest.raises(NonLocalEndpointError, match="sin host"):
            assert_loopback("no-es-una-url")

    def test_host_irresoluble_falla_cerrado(self, monkeypatch) -> None:
        def _boom(*args, **kwargs):
            raise socket.gaierror("sin resolucion")

        monkeypatch.setattr(socket, "getaddrinfo", _boom)
        # Falla cerrado: ante la duda, no se envia nada.
        with pytest.raises(NonLocalEndpointError):
            assert_loopback("http://desconocido:11434")
