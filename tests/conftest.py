"""Utilidades compartidas por las pruebas."""

from __future__ import annotations

import keyring
import pytest
from keyring.backend import KeyringBackend
from keyring.errors import PasswordDeleteError


class KeyringEnMemoria(KeyringBackend):
    """Almacen de credenciales falso: ninguna prueba toca el del sistema."""

    priority = 1  # type: ignore[assignment]

    def __init__(self) -> None:
        super().__init__()
        self.datos: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.datos.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.datos[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        if (service, username) not in self.datos:
            raise PasswordDeleteError("no existe")
        del self.datos[(service, username)]


@pytest.fixture(autouse=True)
def parada_aislada(tmp_path_factory, monkeypatch):
    """Ninguna prueba lee la parada real: un `lymi stop` del usuario no rompe la suite."""
    monkeypatch.setenv("LYMI_PARADA", str(tmp_path_factory.mktemp("parada") / "PARAR"))
    monkeypatch.setenv("LYMI_DIARIO", str(tmp_path_factory.mktemp("diario")))


@pytest.fixture
def keyring_memoria():
    anterior = keyring.get_keyring()
    backend = KeyringEnMemoria()
    keyring.set_keyring(backend)
    yield backend
    keyring.set_keyring(anterior)
