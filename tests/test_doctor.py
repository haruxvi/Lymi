"""Pruebas del diagnostico de proveedores.

La propiedad que importa: nunca reportar un proveedor como listo sin haberlo
comprobado, y que toda carencia traiga el comando que la soluciona.
"""

from __future__ import annotations

import httpx

from lymi.doctor import (
    Chequeo,
    Diagnostico,
    Estado,
    _chequear_clave,
    _chequear_modelo_local,
    _chequear_ollama_instalado,
    _chequear_ollama_servidor,
    ruta_ollama,
)


class TestOllama:
    def test_sin_binario_propone_la_instalacion(self, monkeypatch) -> None:
        monkeypatch.setattr("lymi.doctor.shutil.which", lambda _: None)
        monkeypatch.setattr("lymi.doctor._rutas_conocidas", tuple)
        c = _chequear_ollama_instalado()
        assert c.estado is Estado.FALTA
        assert c.arreglo == "winget install Ollama.Ollama"

    def test_con_binario_queda_ok(self, monkeypatch) -> None:
        monkeypatch.setattr("lymi.doctor.shutil.which", lambda _: "C:/ollama.exe")
        assert _chequear_ollama_instalado().estado is Estado.OK

    def test_instalado_fuera_del_path_no_pide_reinstalar(self, monkeypatch, tmp_path) -> None:
        # Una terminal abierta antes de instalar Ollama no lo ve en PATH. Mandar
        # a reinstalar algo que ya esta ahi es el error que esto evita.
        binario = tmp_path / "ollama.exe"
        binario.write_text("", encoding="utf-8")
        monkeypatch.setattr("lymi.doctor.shutil.which", lambda _: None)
        monkeypatch.setattr("lymi.doctor._rutas_conocidas", lambda: (binario,))

        c = _chequear_ollama_instalado()
        assert c.estado is Estado.OK
        assert c.arreglo is None
        assert "reinicia la terminal" in c.detalle

    def test_servidor_vivo_basta_aunque_no_haya_binario(self, monkeypatch) -> None:
        monkeypatch.setattr("lymi.doctor.shutil.which", lambda _: None)
        monkeypatch.setattr("lymi.doctor._rutas_conocidas", tuple)
        assert _chequear_ollama_instalado(servidor_vivo=True).estado is Estado.OK

    def test_ruta_conocida_inaccesible_no_revienta(self, monkeypatch) -> None:
        class _Ruta:
            def is_file(self) -> bool:
                raise OSError("permiso denegado")

        monkeypatch.setattr("lymi.doctor.shutil.which", lambda _: None)
        monkeypatch.setattr("lymi.doctor._rutas_conocidas", lambda: (_Ruta(),))
        assert ruta_ollama() is None

    def test_servidor_caido_propone_arrancarlo(self, monkeypatch) -> None:
        def _falla(*a, **k):
            raise httpx.ConnectError("rechazado")

        monkeypatch.setattr(httpx, "get", _falla)
        c, modelos = _chequear_ollama_servidor("http://localhost:11434")
        assert c.estado is Estado.FALTA
        assert c.arreglo == "ollama serve"
        assert modelos == []

    def test_endpoint_remoto_es_error_no_carencia(self, monkeypatch) -> None:
        # Un tier "local" apuntando a otra maquina es una fuga disfrazada de
        # privacidad: tiene que fallar ruidosamente, no proponer un arreglo.
        import socket

        def _remoto(host, port, *a, **k):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("203.0.113.7", 11434))]

        monkeypatch.setattr(socket, "getaddrinfo", _remoto)
        monkeypatch.delenv("LYMI_ALLOW_REMOTE_LOCAL", raising=False)
        c, _ = _chequear_ollama_servidor("http://ollama.ejemplo.com:11434")
        assert c.estado is Estado.ERROR
        assert c.arreglo is None


class TestModeloLocal:
    def test_modelo_presente(self) -> None:
        c = _chequear_modelo_local("qwen3:4b", ["qwen3:4b", "llama3:8b"])
        assert c.estado is Estado.OK

    def test_coincide_por_prefijo_de_etiqueta(self) -> None:
        # Ollama etiqueta como "qwen3:4b-instruct-q4_K_M"; sigue siendo qwen3.
        c = _chequear_modelo_local("qwen3:4b", ["qwen3:4b-instruct-q4_K_M"])
        assert c.estado is Estado.OK

    def test_modelo_ausente_propone_el_pull(self) -> None:
        c = _chequear_modelo_local("qwen3:4b", ["llama3:8b"])
        assert c.estado is Estado.FALTA
        assert c.arreglo == "ollama pull qwen3:4b"

    def test_sin_servidor_tambien_propone_el_pull(self) -> None:
        assert _chequear_modelo_local("qwen3:4b", []).arreglo == "ollama pull qwen3:4b"


class TestClaves:
    def test_clave_definida(self, monkeypatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-loquesea")
        assert _chequear_clave("anthropic api", "ANTHROPIC_API_KEY").estado is Estado.OK

    def test_clave_ausente(self, monkeypatch) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        assert _chequear_clave("anthropic api", "ANTHROPIC_API_KEY").estado is Estado.FALTA


class TestResumen:
    def _diag(self, **estados) -> Diagnostico:
        base = {
            "ollama binario": Estado.OK,
            "ollama servidor": Estado.OK,
            "ollama modelo": Estado.OK,
            "claude code": Estado.FALTA,
            "anthropic api": Estado.FALTA,
            "openai api": Estado.FALTA,
        }
        base.update(estados)
        return Diagnostico([Chequeo(n, e, "") for n, e in base.items()])

    def test_tier_local_listo(self) -> None:
        assert self._diag().tier_local is True

    def test_sin_modelo_no_hay_tier_local(self) -> None:
        assert self._diag(**{"ollama modelo": Estado.FALTA}).tier_local is False

    def test_sin_remoto_no_se_puede_medir(self) -> None:
        # Sin proveedor remoto no hay nada que medir: solo queda el modo demo.
        assert self._diag().puede_medir is False

    def test_con_suscripcion_ya_se_puede_medir(self) -> None:
        assert self._diag(**{"claude code": Estado.OK}).puede_medir is True

    def test_con_clave_de_api_tambien(self) -> None:
        assert self._diag(**{"anthropic api": Estado.OK}).puede_medir is True


class TestResidenciaGpu:
    """`/api/ps` de Ollama: cuanto de cada modelo cargado vive en la GPU."""

    def _ps(self, monkeypatch, modelos):
        class Resp:
            def raise_for_status(self):
                return None

            def json(self):
                return {"models": modelos}

        monkeypatch.setattr(httpx, "get", lambda *a, **k: Resp())

    def test_modelo_partido_entre_cpu_y_gpu_avisa(self, monkeypatch) -> None:
        from lymi.doctor import Estado, _chequear_residencia

        self._ps(monkeypatch, [{"name": "qwen3:4b", "size": 3_500, "size_vram": 2_345,
                                "details": {"quantization_level": "Q4_K_M"}}])
        c = _chequear_residencia("http://127.0.0.1:11434")
        assert c.estado is Estado.FALTA and "qwen3:4b Q4_K_M 67% en GPU" in c.detalle
        assert "sera lento" in c.arreglo

    def test_modelo_entero_en_gpu(self, monkeypatch) -> None:
        from lymi.doctor import Estado, _chequear_residencia

        self._ps(monkeypatch, [{"name": "qwen2.5:3b", "size": 2_000, "size_vram": 2_000,
                                "details": {"quantization_level": "Q4_K_M"}}])
        c = _chequear_residencia("http://127.0.0.1:11434")
        assert c.estado is Estado.OK and "100% en GPU" in c.detalle

    def test_no_decide_si_hay_tier_local(self) -> None:
        from lymi.doctor import Chequeo, Diagnostico, Estado

        d = Diagnostico([Chequeo("ollama servidor", Estado.OK, ""), Chequeo("gpu local", Estado.FALTA, "")])
        assert d.tier_local
