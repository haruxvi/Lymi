"""Ejecucion de cada tipo de paso.

Toda llamada -- a un modelo o a una integracion -- pasa por el Recorder. En otros
motores de workflow no sabes cuanto costo cada nodo ni que datos saco de tu
maquina; aqui queda escrito.

Tres reglas de seguridad viven en este modulo:

1. **Los secretos solo se expanden sobre texto del autor.** `${VAR}` se resuelve
   en los tramos literales de una URL, nunca en valores interpolados. Si un
   correo entrante trae el texto `${AWS_SECRET}`, llega al destino tal cual.
2. **Lo interpolado en una URL va escapado.** Un valor no puede cambiar la ruta
   ni la consulta, y el host se comprueba contra la lista blanca DESPUES de
   construir la URL final.
3. **Los errores de red no se imprimen enteros.** La excepcion de httpx incluye
   la URL, y la URL puede llevar el secreto: se reporta solo el tipo de error.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import re
import time
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import httpx

from lymi.bench.runner import Recorder
from lymi.control import Detenido, PresupuestoAgotado
from lymi.ejecutor import CapacidadDenegada, Ejecutor, EjecutorError
from lymi.flows import template
from lymi.flows.schema import (
    AgenciaStep,
    CodigoStep,
    HttpIntegration,
    HttpStep,
    LlmStep,
    McpIntegration,
    PcStep,
    ToolStep,
    TransformStep,
    WebStep,
    Workflow,
)
from lymi.privacidad import EgressBloqueado, sanear_valor
from lymi.privacidad.etiquetas import Nivel
from lymi.providers.base import LLMClient, Message
from lymi.web import Buscador, Web, WebError, investigar

LIMITE_RESPUESTA = 200_000
"""Caracteres maximos que se guardan de una respuesta HTTP o de herramienta."""

REINICIOS_MAXIMOS = 3
"""Reinicios de un servidor MCP permitidos dentro de la ventana antes de degradarlo."""
VENTANA_REINICIOS = 60.0
"""Segundos en los que se cuentan los reinicios."""
ESPERA_REINICIO = 0.5
"""Espera antes del primer reinicio; se duplica en cada uno."""
TIEMPO_PING = 5.0
"""Segundos para decidir si una sesion MCP sigue viva tras un error."""

log = logging.getLogger("lymi.mcp")

_ENV = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

AbrirTransporte = Callable[[], AbstractAsyncContextManager[Any]]
"""Fabrica de un contexto que produce el par (lectura, escritura) de MCP."""


class PasoError(RuntimeError):
    """Fallo al ejecutar un paso."""

    def __init__(self, mensaje: str, *, reintentable: bool = True) -> None:
        super().__init__(mensaje)
        self.reintentable = reintentable


# ---------------------------------------------------------------- utilidades


def expandir_env(valor: Any, entorno: Mapping[str, str]) -> Any:
    """Sustituye `${VAR}` desde el entorno. Solo para configuracion del autor."""
    if isinstance(valor, str):

        def _sustituir(m: re.Match[str]) -> str:
            nombre = m.group(1)
            if nombre not in entorno:
                raise PasoError(f"falta la variable de entorno {nombre}", reintentable=False)
            return entorno[nombre]

        return _ENV.sub(_sustituir, valor)
    if isinstance(valor, Mapping):
        return {k: expandir_env(v, entorno) for k, v in valor.items()}
    if isinstance(valor, list):
        return [expandir_env(v, entorno) for v in valor]
    return valor


def extraer_json(texto: str) -> Any:
    """Saca JSON de la respuesta de un modelo, aunque venga con texto alrededor."""
    limpio = texto.strip()[:LIMITE_RESPUESTA]
    if limpio.startswith("```"):
        limpio = re.sub(r"^```[A-Za-z]*\s*|\s*```$", "", limpio).strip()
    try:
        return json.loads(limpio)
    except json.JSONDecodeError:
        pass
    decodificador = json.JSONDecoder()
    for i, caracter in enumerate(limpio):
        if caracter in "{[":
            try:
                valor, _ = decodificador.raw_decode(limpio, i)
            except json.JSONDecodeError:
                continue
            return valor
    raise PasoError("el modelo no devolvio JSON valido")


def _texto(valor: Any) -> str:
    return valor if isinstance(valor, str) else json.dumps(valor, ensure_ascii=False)


def _causa_raiz(exc: BaseException) -> BaseException:
    """Desenvuelve los grupos de excepciones de anyio hasta el error real.

    Sin esto, un fallo de autorizacion dentro del transporte HTTP de MCP llega
    como "unhandled errors in a TaskGroup", que no le dice nada a nadie.
    """
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return exc


def construir_url(
    url: str, contexto: Mapping[str, Any], entorno: Mapping[str, str], *, con_secretos: bool
) -> str:
    """Arma la URL final.

    Tramos literales: `${VAR}` se expande (si `con_secretos`). Tramos `{{ }}`: el
    valor se escapa y jamas se expande. Con `con_secretos=False` sirve para una
    vista previa que no revela nada.
    """
    partes: list[str] = []
    posicion = 0
    for m in template.PATRON.finditer(url):
        literal = url[posicion : m.start()]
        partes.append(expandir_env(literal, entorno) if con_secretos else literal)
        valor = template.resolver_ruta(contexto, m.group(1))
        partes.append(quote(_texto(valor), safe=""))
        posicion = m.end()
    cola = url[posicion:]
    partes.append(expandir_env(cola, entorno) if con_secretos else cola)
    return "".join(partes)


def _es_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def verificar_destino(url: str, integracion: HttpIntegration) -> str:
    """Comprueba host y esquema de la URL FINAL. Devuelve el host."""
    partes = urlparse(url)
    host = (partes.hostname or "").lower()
    if not host:
        raise PasoError("la URL no tiene host", reintentable=False)

    permitido = any(
        host == h.lower() or (h.startswith(".") and host.endswith(h.lower()))
        for h in integracion.allow_hosts
    )
    if not permitido:
        raise PasoError(f"{host} no esta en allow_hosts de la integracion", reintentable=False)

    if partes.scheme != "https" and not (partes.scheme == "http" and _es_loopback(host)):
        raise PasoError(f"{host}: solo se admite https (http solo hacia loopback)", reintentable=False)
    return host


# ---------------------------------------------------------------- MCP


class _ServidorMcp:
    """Un servidor MCP vivo, dueno exclusivo de su sesion.

    La sesion vive en su propia tarea y recibe pedidos por una cola. Asi los
    timeouts de cada paso solo cortan la ESPERA de una respuesta, nunca los
    contextos internos del SDK, que exigen abrirse y cerrarse en orden.
    """

    def __init__(self, nombre: str, abrir: AbrirTransporte) -> None:
        self.nombre = nombre
        self._abrir = abrir
        self._error: BaseException | None = None
        self._muriendo = False
        """Se decidio que la sesion murio; la limpieza del transporte puede seguir en curso."""
        bucle = asyncio.get_running_loop()
        self._listo: asyncio.Future[None] = bucle.create_future()
        self._cola: asyncio.Queue[tuple[str, dict[str, Any], asyncio.Future[Any]] | None] = asyncio.Queue()
        self._tarea = asyncio.create_task(self._atender(), name=f"mcp:{nombre}")

    async def _atender(self) -> None:
        from mcp import ClientSession

        try:
            async with self._abrir() as (lectura, escritura), ClientSession(lectura, escritura) as sesion:
                await sesion.initialize()
                self._listo.set_result(None)
                while (pedido := await self._cola.get()) is not None:
                    herramienta, argumentos, futuro = pedido
                    if futuro.done():
                        continue
                    try:
                        resultado = await sesion.call_tool(herramienta, argumentos)
                    except Exception as exc:  # noqa: BLE001 - se entrega a quien espera
                        # Un error puede venir del protocolo (la sesion sigue sana) o
                        # de la conexion (el proceso murio). Solo un ping lo distingue.
                        # Se decide ANTES de entregar el error: si no, quien espera
                        # retorna y la llamada siguiente reutiliza un servidor que se
                        # esta cerrando.
                        viva = await self._sigue_viva(sesion)
                        if not viva:
                            self._error = exc
                            self._muriendo = True
                        if not futuro.done():
                            futuro.set_exception(exc)
                        if not viva:
                            return
                    else:
                        if not futuro.done():
                            futuro.set_result(resultado)
        except Exception as exc:  # noqa: BLE001 - el arranque o la sesion murieron
            self._error = self._error or exc
            self._muriendo = True
            if not self._listo.done():
                self._listo.set_exception(exc)

    @staticmethod
    async def _sigue_viva(sesion: Any) -> bool:
        try:
            await asyncio.wait_for(sesion.send_ping(), TIEMPO_PING)
        except Exception:  # noqa: BLE001 - cualquier fallo del ping es "no responde"
            return False
        return True

    @property
    def muerto(self) -> bool:
        """La sesion termino: el proceso murio, no arranco o se cerro."""
        return self._muriendo or self._tarea.done()

    def causa(self) -> str:
        if self._error is not None:
            return f"{type(self._error).__name__}: {self._error}"[:300]
        return "el servidor termino"

    async def llamar(self, herramienta: str, argumentos: dict[str, Any]) -> Any:
        await asyncio.wait({self._listo, self._tarea}, return_when=asyncio.FIRST_COMPLETED)
        if not self._listo.done():
            raise PasoError(f"el servidor MCP {self.nombre!r} termino antes de arrancar", reintentable=False)
        self._listo.result()  # levanta si el arranque fallo

        futuro: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        await self._cola.put((herramienta, argumentos, futuro))
        await asyncio.wait({futuro, self._tarea}, return_when=asyncio.FIRST_COMPLETED)
        if not futuro.done():
            raise PasoError(f"el servidor MCP {self.nombre!r} se cerro a mitad de llamada", reintentable=False)
        return futuro.result()

    async def cerrar(self) -> None:
        await self._cola.put(None)
        try:
            await asyncio.wait_for(asyncio.shield(self._tarea), timeout=10)
        except Exception:  # noqa: BLE001 - cerrar nunca debe fallar
            self._tarea.cancel()
        if self._listo.done() and not self._listo.cancelled():
            self._listo.exception()  # evita el aviso de excepcion nunca recuperada


@dataclass(slots=True)
class SaludMcp:
    """Estado de supervision de una integracion MCP."""

    arranques: int = 0
    reinicios: list[float] = field(default_factory=list)
    """Momentos (reloj monotono) de los reinicios dentro de la ventana."""
    degradado: bool = False
    ultimo_error: str | None = None


class McpPool:
    """Servidores MCP abiertos durante una corrida, uno por integracion y bajo demanda.

    Supervisa cada servidor: si muere entre llamadas, lo reinicia con espera
    exponencial. Si muere demasiadas veces dentro de la ventana, la integracion
    queda degradada y falla al instante en vez de martillar un proceso roto.

    Nunca reintenta la llamada que estaba en curso cuando el servidor murio: la
    herramienta pudo haber tenido efectos. Solo la SIGUIENTE llamada provoca el
    reinicio.
    """

    def __init__(
        self,
        integraciones: Mapping[str, McpIntegration],
        entorno: Mapping[str, str],
        *,
        reinicios_maximos: int = REINICIOS_MAXIMOS,
        ventana: float = VENTANA_REINICIOS,
        espera_base: float = ESPERA_REINICIO,
        dormir: Callable[[float], Any] = asyncio.sleep,
        reloj: Callable[[], float] = time.monotonic,
    ) -> None:
        self._integraciones = dict(integraciones)
        self._entorno = entorno
        self._servidores: dict[str, _ServidorMcp] = {}
        self._salud: dict[str, SaludMcp] = {}
        self._reinicios_maximos = reinicios_maximos
        self._ventana = ventana
        self._espera_base = espera_base
        self._dormir = dormir
        self._reloj = reloj
        self._candado = asyncio.Lock()

    def salud(self) -> dict[str, SaludMcp]:
        """Copia del estado de supervision de cada integracion usada."""
        return {
            nombre: SaludMcp(s.arranques, list(s.reinicios), s.degradado, s.ultimo_error)
            for nombre, s in self._salud.items()
        }

    def _abrir_stdio(self, integ: McpIntegration) -> AbrirTransporte:
        from mcp import StdioServerParameters
        from mcp.client.stdio import stdio_client

        # El SDK combina estas variables con un entorno minimo por defecto: el
        # servidor recibe solo lo declarado, no todo tu entorno.
        parametros = StdioServerParameters(
            command=integ.command or "",
            args=list(integ.args),
            env=expandir_env(dict(integ.env), self._entorno) or None,
        )

        def abrir() -> AbstractAsyncContextManager[Any]:
            return stdio_client(parametros)

        return abrir

    def _abrir_http(self, integ: McpIntegration) -> AbrirTransporte:
        encabezados = expandir_env(dict(integ.headers), self._entorno)
        url = integ.url or ""

        @asynccontextmanager
        async def abrir() -> AsyncIterator[Any]:
            from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

            autorizacion = None
            if integ.auth == "oauth":
                from lymi.flows import oauth

                # No interactivo: una corrida nunca abre un navegador. Sin sesion
                # previa, falla con la instruccion para iniciarla.
                autorizacion = oauth.proveedor_no_interactivo(url, list(integ.scopes))

            # El SDK de MCP usa httpx2, no httpx: el cliente lo construye el SDK.
            async with (
                create_mcp_http_client(headers=encabezados or None, auth=autorizacion) as cliente,
                streamable_http_client(url, http_client=cliente) as flujos,
            ):
                yield flujos

        return abrir

    async def _servidor(self, nombre: str) -> _ServidorMcp:
        async with self._candado:
            salud = self._salud.setdefault(nombre, SaludMcp())
            if salud.degradado:
                raise PasoError(
                    f"la integracion MCP {nombre!r} esta degradada: murio {len(salud.reinicios)} veces "
                    f"en {self._ventana:g} s (ultimo error: {salud.ultimo_error})",
                    reintentable=False,
                )

            actual = self._servidores.get(nombre)
            if actual is not None and not actual.muerto:
                return actual

            if actual is not None:
                salud.ultimo_error = actual.causa()
                ahora = self._reloj()
                salud.reinicios = [t for t in salud.reinicios if ahora - t < self._ventana]
                if len(salud.reinicios) >= self._reinicios_maximos:
                    salud.degradado = True
                    log.warning("MCP %s degradado: %s", nombre, salud.ultimo_error)
                    raise PasoError(
                        f"la integracion MCP {nombre!r} quedo degradada tras {len(salud.reinicios)} "
                        f"reinicios en {self._ventana:g} s (ultimo error: {salud.ultimo_error})",
                        reintentable=False,
                    )
                salud.reinicios.append(ahora)
                espera = self._espera_base * 2 ** (len(salud.reinicios) - 1)
                log.info("MCP %s murio (%s); reinicio en %.2f s", nombre, salud.ultimo_error, espera)
                await actual.cerrar()
                await self._dormir(espera)

            integ = self._integraciones[nombre]
            abrir = self._abrir_stdio(integ) if integ.transport == "stdio" else self._abrir_http(integ)
            salud.arranques += 1
            self._servidores[nombre] = _ServidorMcp(nombre, abrir)
            return self._servidores[nombre]

    async def llamar(self, nombre: str, herramienta: str, argumentos: dict[str, Any]) -> Any:
        try:
            servidor = await self._servidor(nombre)
            resultado = await servidor.llamar(herramienta, argumentos)
        except PasoError:
            raise
        except Exception as exc:
            raiz = _causa_raiz(exc)
            # Un error de autorizacion ya trae la instruccion: se muestra tal cual.
            detalle = str(raiz) if type(raiz).__name__ == "OAuthError" else f"{type(raiz).__name__}: {raiz}"
            raise PasoError(f"MCP {nombre}.{herramienta}: {detalle}", reintentable=False) from exc

        contenido = getattr(resultado, "content", None)
        if contenido is None:
            raise PasoError(
                f"{nombre}.{herramienta} pidio interaccion; los workflows no la admiten",
                reintentable=False,
            )
        texto = "\n".join(c.text for c in contenido if getattr(c, "type", None) == "text")[:LIMITE_RESPUESTA]

        # El SDK usa snake_case: `is_error`, `structured_content`. Leer `isError`
        # dejaria pasar cada fallo de herramienta como exito.
        if getattr(resultado, "is_error", False):
            raise PasoError(f"{nombre}.{herramienta} devolvio error: {texto[:400]}", reintentable=False)
        estructurado = getattr(resultado, "structured_content", None)
        if estructurado is not None:
            return estructurado
        try:
            return json.loads(texto)
        except json.JSONDecodeError:
            return texto

    async def aclose(self) -> None:
        for servidor in self._servidores.values():
            await servidor.cerrar()


# ---------------------------------------------------------------- recursos y nodos


@dataclass(slots=True)
class Recursos:
    """Lo que un paso necesita para ejecutarse."""

    rec: Recorder
    local: LLMClient | None
    remote: LLMClient | None
    mcp: McpPool
    http: httpx.AsyncClient
    entorno: Mapping[str, str]
    ejecutor: Ejecutor | None = None
    web: Web | None = None
    buscador: Buscador | None = None
    aprobar: Callable[..., Any] | None = None
    """Lo usan los pasos que piden aprobacion desde dentro (los agentes de una agencia)."""
    politica: Any = None
    tiempo_aprobacion: float | None = None
    ledger: Any = None


async def ejecutar_llm(paso: LlmStep, contexto: Mapping[str, Any], r: Recursos) -> Any:
    cliente = r.local if paso.tier == "local" else r.remote
    if cliente is None:
        raise PasoError(f"no hay proveedor {paso.tier}: corre `lymi setup`", reintentable=False)

    prompt = _texto(template.render(paso.prompt, contexto))
    system = _texto(template.render(paso.system, contexto)) if paso.system is not None else None
    mensajes = [Message("user", prompt)]

    # La pasarela decide antes de llamar. Nada de lo que corta aqui se reintenta:
    # reintentar un dato bloqueado, una parada o un tope agotado daria lo mismo.
    try:
        enviados, sistema, redactor = r.rec.preparar(cliente, mensajes, system)
    except (EgressBloqueado, Detenido, PresupuestoAgotado) as exc:
        raise PasoError(str(exc), reintentable=False) from None

    completion = await asyncio.to_thread(
        cliente.complete, enviados, system=sistema, max_tokens=paso.max_tokens
    )
    if redactor is not None:
        completion.text = redactor.rehidratar(completion.text)
    # Se registra aqui, en el hilo del bucle: SQLite no admite escrituras cruzadas.
    r.rec.registrar(
        completion, enviados, purpose=f"flow:{paso.id}", system=sistema,
        redacciones=redactor.total if redactor is not None else 0,
    )
    return extraer_json(completion.text) if paso.output == "json" else completion.text


async def ejecutar_transform(paso: TransformStep, contexto: Mapping[str, Any], _r: Recursos) -> Any:
    return template.render(paso.set, contexto)


async def ejecutar_tool(paso: ToolStep, contexto: Mapping[str, Any], r: Recursos) -> Any:
    argumentos = template.render(paso.args, contexto)
    try:
        r.rec.verificar_protegido(_texto(argumentos))
    except EgressBloqueado as exc:
        raise PasoError(str(exc), reintentable=False) from None
    destino = f"{paso.integration}.{paso.tool}"
    inicio = time.perf_counter()
    try:
        salida = await r.mcp.llamar(paso.integration, paso.tool, argumentos)
    except PasoError as exc:
        r.rec.integracion(
            tipo="mcp", destino=destino, proposito=f"flow:{paso.id}", payload=_texto(argumentos),
            latencia_ms=int((time.perf_counter() - inicio) * 1000), ok=False, error=str(exc)[:300],
        )
        raise
    r.rec.integracion(
        tipo="mcp", destino=destino, proposito=f"flow:{paso.id}", payload=_texto(argumentos),
        latencia_ms=int((time.perf_counter() - inicio) * 1000),
    )
    # La salida de una herramienta ajena es entrada para el proximo paso: se sanea.
    return sanear_valor(salida)[0]


async def ejecutar_http(paso: HttpStep, contexto: Mapping[str, Any], r: Recursos, flujo: Workflow) -> Any:
    integ = flujo.integrations[paso.integration]
    if not isinstance(integ, HttpIntegration):  # el esquema lo garantiza; esto lo documenta
        raise PasoError(f"{paso.integration!r} no es una integracion http", reintentable=False)

    url = construir_url(paso.url, contexto, r.entorno, con_secretos=True)
    host = verificar_destino(url, integ)
    cuerpo = template.render(paso.body, contexto) if paso.body is not None else None
    encabezados = expandir_env(dict(integ.headers), r.entorno)
    payload = None if cuerpo is None else _texto(cuerpo)
    proposito = f"flow:{paso.id}:{paso.method}"
    try:
        r.rec.verificar_protegido(f"{url}\n{payload or ''}")
    except EgressBloqueado as exc:
        raise PasoError(str(exc), reintentable=False) from None

    inicio = time.perf_counter()
    try:
        respuesta = await r.http.request(
            paso.method,
            url,
            headers=encabezados,
            json=cuerpo if cuerpo is not None and not isinstance(cuerpo, str) else None,
            content=cuerpo if isinstance(cuerpo, str) else None,
            timeout=paso.timeout_s,
        )
    except httpx.HTTPError as exc:
        # Solo el tipo: el mensaje de httpx trae la URL, y la URL puede traer el secreto.
        r.rec.integracion(
            tipo="http", destino=host, proposito=proposito, payload=payload,
            latencia_ms=int((time.perf_counter() - inicio) * 1000), ok=False, error=type(exc).__name__,
        )
        raise PasoError(f"{paso.method} {host}: {type(exc).__name__}") from None

    estado = respuesta.status_code
    ok = estado < 300
    r.rec.integracion(
        tipo="http", destino=host, proposito=proposito, payload=payload,
        latencia_ms=int((time.perf_counter() - inicio) * 1000),
        ok=ok, error=None if ok else f"HTTP {estado}",
    )
    if 300 <= estado < 400:
        raise PasoError(f"{host} redirige ({estado}); no se siguen redirecciones", reintentable=False)
    if not ok:
        raise PasoError(f"{paso.method} {host}: HTTP {estado}", reintentable=estado >= 500 or estado == 429)

    # La respuesta de un servicio externo es entrada ajena para los pasos que siguen.
    try:
        return sanear_valor(respuesta.json())[0]
    except ValueError:
        return sanear_valor(respuesta.text[:LIMITE_RESPUESTA])[0]


def _campos_pc(paso: PcStep, contexto: Mapping[str, Any]) -> tuple[dict[str, str], list[str]]:
    valores = {
        campo: _texto(template.render(getattr(paso, campo), contexto))
        for campo in ("ruta", "destino", "contenido")
        if getattr(paso, campo) is not None
    }
    return valores, [_texto(template.render(a, contexto)) for a in paso.args]


def _operar_pc(ejecutor: Ejecutor, paso: PcStep, valores: dict[str, str], args: list[str]) -> Any:
    if paso.op == "leer":
        return ejecutor.leer(valores["ruta"])
    if paso.op == "listar":
        return ejecutor.listar(valores["ruta"])
    if paso.op == "escribir":
        return ejecutor.escribir(valores["ruta"], valores["contenido"])
    if paso.op == "mover":
        return ejecutor.mover(valores["ruta"], valores["destino"])
    if paso.op == "borrar":
        return ejecutor.borrar(valores["ruta"])
    return ejecutor.ejecutar(paso.comando or "", args, timeout=paso.timeout_s)


async def ejecutar_pc(paso: PcStep, contexto: Mapping[str, Any], r: Recursos) -> Any:
    if r.ejecutor is None:
        raise PasoError("este motor no tiene ejecutor del host", reintentable=False)
    valores, args = _campos_pc(paso, contexto)
    destino = f"{paso.op}:{paso.comando if paso.op == 'ejecutar' else valores.get('ruta')}"
    inicio = time.perf_counter()
    try:
        salida = await asyncio.to_thread(_operar_pc, r.ejecutor, paso, valores, args)
    except (CapacidadDenegada, EjecutorError, OSError) as exc:
        r.rec.accion_local(
            tipo="pc", destino=destino, proposito=f"flow:{paso.id}",
            latencia_ms=int((time.perf_counter() - inicio) * 1000), ok=False, error=str(exc)[:300],
        )
        # Una capacidad denegada no cambia al reintentar, y un efecto no se repite.
        raise PasoError(str(exc), reintentable=False) from None
    r.rec.accion_local(
        tipo="pc", destino=destino, proposito=f"flow:{paso.id}",
        latencia_ms=int((time.perf_counter() - inicio) * 1000),
    )
    if paso.op == "leer":
        # Lo leido del PC puede ser `nunca-sale`: desde ahora la pasarela lo vigila.
        if salida.nivel is Nivel.NUNCA_SALE:
            r.rec.proteger(salida.texto)
        return sanear_valor(salida.texto)[0]
    return sanear_valor(salida)[0]


def _lista_urls(valor: Any) -> list[str]:
    if isinstance(valor, str):
        try:
            valor = json.loads(valor)
        except json.JSONDecodeError:
            return valor.split()
    if isinstance(valor, list):
        return [v if isinstance(v, str) else str(v.get("url", "")) if isinstance(v, dict) else str(v) for v in valor]
    return []


async def ejecutar_web(paso: WebStep, contexto: Mapping[str, Any], r: Recursos) -> Any:
    if r.web is None:
        raise PasoError("este motor no tiene acceso web", reintentable=False)
    proposito = f"flow:{paso.id}"

    def campo(valor: str | None) -> str:
        return _texto(template.render(valor, contexto)) if valor is not None else ""

    async def completar(sistema: str, mensaje: str) -> str:
        cliente = r.local if paso.tier == "local" else r.remote
        if cliente is None:
            raise PasoError(f"no hay proveedor {paso.tier}: corre `lymi setup`", reintentable=False)
        try:
            enviados, sistema_final, redactor = r.rec.preparar(cliente, [Message("user", mensaje)], sistema)
        except (EgressBloqueado, Detenido, PresupuestoAgotado) as exc:
            raise PasoError(str(exc), reintentable=False) from None
        completion = await asyncio.to_thread(cliente.complete, enviados, system=sistema_final, max_tokens=2048)
        if redactor is not None:
            completion.text = redactor.rehidratar(completion.text)
        r.rec.registrar(
            completion, enviados, purpose=proposito, system=sistema_final,
            redacciones=redactor.total if redactor is not None else 0,
        )
        return completion.text

    try:
        if paso.op in {"extraer", "mapear"}:
            url = campo(paso.url)
            r.rec.verificar_protegido(url)
            if paso.op == "extraer":
                salida: Any = (await r.web.extraer(url)).como_dict()
            else:
                mapa = await r.web.mapear(url, max_paginas=paso.max_paginas, profundidad=paso.profundidad)
                salida = mapa.como_dict()
        elif paso.op == "buscar":
            consulta = campo(paso.consulta)
            r.rec.verificar_protegido(consulta)
            if r.buscador is None:
                raise PasoError("no hay buscador: define LYMI_BUSCADOR_URL (ej. SearXNG local)", reintentable=False)
            salida = [x.como_dict() for x in await r.buscador.buscar(consulta, paso.max_resultados)]
        else:
            pregunta = campo(paso.pregunta)
            r.rec.verificar_protegido(pregunta)
            urls = _lista_urls(template.render(paso.urls, contexto)) if paso.urls else []
            informe = await investigar(
                pregunta, web=r.web, buscador=r.buscador, urls=urls, completar=completar,
                max_fuentes=paso.max_resultados,
            )
            salida = informe.como_dict()
    except EgressBloqueado as exc:
        raise PasoError(str(exc), reintentable=False) from None
    except WebError as exc:
        raise PasoError(str(exc), reintentable=exc.reintentable) from None
    finally:
        eventos = r.web.vaciar_eventos() + (r.buscador.vaciar_eventos() if r.buscador is not None else [])
        for ev in eventos:
            r.rec.integracion(
                tipo=ev.tipo, destino=ev.host, proposito=proposito, payload=ev.payload,
                latencia_ms=ev.latencia_ms, ok=ev.ok, error=ev.error,
            )
    return sanear_valor(salida)[0]


def _consultar_codigo(paso: CodigoStep, raiz: str, valores: dict[str, str]) -> dict[str, Any]:
    """Corre en un hilo: abre, pone al dia, consulta y cierra el indice en ese mismo hilo."""
    from lymi.codigo import abrir
    from lymi.codigo import formato as fmt
    from lymi.ejecutor import cargar_perfil

    base = Path.cwd()
    carpeta = cargar_perfil(base / "ejecutor.yml", base).resolver_lectura(raiz, base)
    with abrir(carpeta) as indice:
        if paso.op == "buscar":
            datos: Any = indice.buscar(valores["consulta"])
            texto = fmt.buscar(datos)
        elif paso.op == "esqueleto":
            datos = indice.esqueleto(valores["ruta"])
            texto = fmt.esqueleto(datos)
        elif paso.op == "fragmento":
            datos = indice.fragmento(valores["nombre"])
            texto = fmt.fragmentos(datos)
        elif paso.op == "llamadores":
            datos = indice.llamadores(valores["nombre"])
            texto = fmt.llamadores(valores["nombre"], datos)
        elif paso.op == "impacto":
            datos = indice.impacto(valores["nombre"], paso.profundidad)
            texto = fmt.impacto(datos)
        else:
            datos = indice.mapa(valores.get("ruta", ""))
            texto = fmt.mapa(datos)
    return {"texto": texto, "datos": datos}


async def ejecutar_codigo(paso: CodigoStep, contexto: Mapping[str, Any], r: Recursos) -> Any:
    from lymi.codigo import IndiceError

    raiz = _texto(template.render(paso.raiz, contexto))
    valores = {
        campo: _texto(template.render(getattr(paso, campo), contexto))
        for campo in ("consulta", "ruta", "nombre")
        if getattr(paso, campo) is not None
    }
    destino = f"codigo:{paso.op}:{next(iter(valores.values()), '')}"[:200]
    inicio = time.perf_counter()
    try:
        salida = await asyncio.to_thread(_consultar_codigo, paso, raiz, valores)
    except (IndiceError, CapacidadDenegada, OSError) as exc:
        r.rec.accion_local(
            tipo="codigo", destino=destino, proposito=f"flow:{paso.id}",
            latencia_ms=int((time.perf_counter() - inicio) * 1000), ok=False, error=str(exc)[:300],
        )
        raise PasoError(str(exc), reintentable=False) from None
    r.rec.accion_local(
        tipo="codigo", destino=destino, proposito=f"flow:{paso.id}",
        latencia_ms=int((time.perf_counter() - inicio) * 1000),
    )
    return salida


async def ejecutar_agencia(paso: AgenciaStep, contexto: Mapping[str, Any], r: Recursos) -> Any:
    from lymi.agencia import AgenciaError, Orquestador, cargar_agencia, enrutar
    from lymi.agencia.motor import raiz_trazas

    try:
        agencia = cargar_agencia(Path(paso.archivo))
    except AgenciaError as exc:
        raise PasoError(str(exc), reintentable=False) from None
    texto = _texto(template.render(paso.tarea, contexto))
    if paso.agente is not None:
        destino, motivo = _texto(template.render(paso.agente, contexto)), "declarado en el paso"
    else:
        destino, texto, motivo = await enrutar(agencia, texto, r.local, r.rec)
    orquestador = Orquestador(
        agencia, r, aprobar=r.aprobar, politica=r.politica, tiempo_aprobacion=r.tiempo_aprobacion,
        ledger=r.ledger, traza=raiz_trazas() / f"{agencia.name}-{paso.id}-{int(time.time())}.jsonl",
    )
    try:
        raiz = await orquestador.correr(texto, destino)
    except ValueError as exc:
        raise PasoError(str(exc), reintentable=False) from None
    if raiz.estado != "hecha":
        raise PasoError(f"la agencia no termino ({raiz.agente}): {raiz.error}", reintentable=False)
    return {
        "resultado": raiz.resultado,
        "agente": raiz.agente,
        "ruta": motivo,
        "tareas": [t.resumen() for t in orquestador.tareas.values()],
    }


async def ejecutar(paso: Any, contexto: Mapping[str, Any], r: Recursos, flujo: Workflow) -> Any:
    """Despacha el paso a su nodo."""
    if isinstance(paso, AgenciaStep):
        return await ejecutar_agencia(paso, contexto, r)
    if isinstance(paso, CodigoStep):
        return await ejecutar_codigo(paso, contexto, r)
    if isinstance(paso, WebStep):
        return await ejecutar_web(paso, contexto, r)
    if isinstance(paso, PcStep):
        return await ejecutar_pc(paso, contexto, r)
    if isinstance(paso, LlmStep):
        return await ejecutar_llm(paso, contexto, r)
    if isinstance(paso, TransformStep):
        return await ejecutar_transform(paso, contexto, r)
    if isinstance(paso, ToolStep):
        return await ejecutar_tool(paso, contexto, r)
    if isinstance(paso, HttpStep):
        return await ejecutar_http(paso, contexto, r, flujo)
    raise PasoError(f"tipo de paso no soportado: {type(paso).__name__}", reintentable=False)


def destino_de(paso: Any, contexto: Mapping[str, Any]) -> tuple[str, str | None]:
    """Destino y metodo de un paso con efectos, para aplicar politicas de aprobacion.

    Se calcula sin secretos. Si el host no se puede determinar devuelve `?`, que no
    coincide con ninguna regla: el paso cae en "preguntar", el lado seguro.
    """
    if isinstance(paso, HttpStep):
        url = construir_url(paso.url, contexto, {}, con_secretos=False)
        host = (urlparse(url).hostname or "?").lower()
        return host, paso.method
    if isinstance(paso, ToolStep):
        return f"mcp:{paso.integration}.{paso.tool}", None
    if isinstance(paso, PcStep):
        valores, _ = _campos_pc(paso, contexto)
        objetivo = paso.comando if paso.op == "ejecutar" else valores.get("ruta", "?")
        return f"pc:{objetivo}", paso.op.upper()
    return "?", None


def vista_previa(paso: Any, contexto: Mapping[str, Any]) -> str:
    """Lo que el paso va a hacer, para pedir aprobacion. Nunca revela secretos."""
    if isinstance(paso, HttpStep):
        url = construir_url(paso.url, contexto, {}, con_secretos=False)
        linea = f"{paso.method} {url}"
        if paso.body is None:
            return linea
        return f"{linea}\n{_texto(template.render(paso.body, contexto))[:600]}"
    if isinstance(paso, ToolStep):
        argumentos = _texto(template.render(paso.args, contexto))[:600]
        return f"mcp {paso.integration}.{paso.tool}({argumentos})"
    if isinstance(paso, PcStep):
        valores, args = _campos_pc(paso, contexto)
        if paso.op == "ejecutar":
            return f"ejecutar en este PC: {paso.comando} {' '.join(args)}".rstrip()
        linea = f"{paso.op} en este PC: {valores.get('ruta', '')}"
        if "destino" in valores:
            linea += f" -> {valores['destino']}"
        if "contenido" in valores:
            contenido = valores["contenido"]
            return f"{linea} ({len(contenido.encode('utf-8'))} bytes)\n{contenido[:600]}"
        return linea
    return str(getattr(paso, "id", paso))
