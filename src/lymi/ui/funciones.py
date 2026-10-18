"""Rutas de la API para todo lo que lymi sabe hacer: hoy, correo, calendario, chat,
agencia, memoria, programaciones, codigo, web y el diario del PC.

Dos clases de operaciones, y la diferencia importa:

- **Lecturas locales** (tu bandeja, tu agenda, el indice de codigo, la memoria):
  responden al momento. No gastan tokens ni sacan nada de la maquina, asi que no
  ensucian el ledger con una corrida por cada clic.
- **Todo lo que llama a un modelo, sale a la red o tiene efectos** (resumir,
  redactar, investigar, la agencia, el chat): es un trabajo en segundo plano que
  pasa por el mismo motor que la terminal, con ledger, aprobaciones y parada.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from lymi.ui.comun import ErrorApi, archivo_en, cuerpo, entero, texto, tier
from lymi.ui.trabajos import Trabajos


@dataclass(slots=True)
class Lugares:
    """Donde vive cada cosa. En la app de escritorio, todo bajo la carpeta de datos."""

    ledger: Path
    workflows: Path
    agencias: Path
    agenda: Path
    ganchos: Path
    sesiones: Path
    agenda_activa: bool = False
    """Si este proceso revisa la agenda (escritorio o `lymi serve`) o solo la muestra."""


def _fecha(valor: datetime | None) -> str | None:
    return valor.isoformat() if valor else None


def _mensaje(m: Any, *, cuerpo_completo: bool = False) -> dict[str, Any]:
    datos = {
        "id": m.id, "carpeta": m.carpeta, "n": m.n, "fecha": _fecha(m.fecha), "de": m.remitente,
        "de_completo": m.de, "para": m.para, "asunto": m.asunto, "leido": m.leido, "boletin": m.boletin,
        "para_mi": m.para_mi, "adjuntos": list(m.adjuntos),
    }
    if cuerpo_completo:
        datos.update(cuerpo=m.cuerpo, avisos=list(m.avisos), truncado=m.truncado, responder_a=m.responder_a)
    else:
        extracto = " ".join(m.cuerpo.split())
        datos["extracto"] = extracto[:180]
    return datos


def _evento(e: Any) -> dict[str, Any]:
    return {
        "titulo": e.titulo, "inicio": e.inicio.isoformat(), "fin": e.fin.isoformat(), "lugar": e.lugar,
        "todo_el_dia": e.todo_el_dia, "calendario": e.calendario,
    }


def _nota(n: Any) -> dict[str, Any]:
    return {
        "id": n.id, "estado": n.estado, "texto": n.texto, "fuente": n.fuente, "agente": n.agente,
        "corrida": n.corrida, "creada": n.creada, "ruta": n.ruta.as_posix(),
    }


def _programacion(p: Any) -> dict[str, Any]:
    return {
        "id": p.id, "workflow": p.workflow.name, "ruta": str(p.workflow), "cron": p.cron, "zona": p.zona,
        "activo": p.activo, "ultima": _fecha(p.ultima), "proxima": _fecha(p.proxima),
        "aprobados": sorted(p.aprobados), "entradas": p.entradas,
    }


def _intentar(funcion: Callable[[], Any], errores: tuple[type[Exception], ...]) -> dict[str, Any]:
    """Una seccion de Hoy que falla no tumba las demas: devuelve el motivo en su lugar."""
    try:
        return {"ok": True, "datos": funcion()}
    except errores as exc:
        return {"ok": False, "error": str(exc)}


def rutas(lugares: Lugares, trabajos: Trabajos) -> list[Route]:
    from lymi.calendario import Calendario, CalendarioError
    from lymi.correo import Buzon, CorreoError
    from lymi.memoria import Memoria, MemoriaError
    from lymi.triggers.agenda import Agenda, AgendaError
    from lymi.ui.sesiones import (
        SesionError,
        Sesiones,
        asistente,
        contexto_turno,
        debate,
        validar_mensaje,
    )

    sesiones = Sesiones(lugares.sesiones)

    # ------------------------------------------------------------ hoy

    def correo_de_hoy() -> dict[str, Any]:
        with Buzon() as buzon:
            recientes = buzon.listar("INBOX", n=60, dias=3)
            ultimo = next(iter(buzon.listar("INBOX", n=1)), None)
        sin_leer = [m for m in recientes if not m.leido]
        importantes = [m for m in sin_leer if not m.boletin and m.para_mi]
        return {
            "sin_leer": len(sin_leer),
            "boletines": sum(1 for m in sin_leer if m.boletin),
            "importantes": [_mensaje(m) for m in importantes[:8]],
            "ultimo": _fecha(ultimo.fecha) if ultimo is not None else None,
        }

    def agenda_de_hoy() -> dict[str, Any]:
        inicio = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
        eventos, avisos = Calendario().eventos(inicio, inicio + timedelta(days=2))
        manana = inicio + timedelta(days=1)
        return {
            "hoy": [_evento(e) for e in eventos if e.inicio < manana],
            "manana": [_evento(e) for e in eventos if e.inicio >= manana],
            "avisos": avisos,
        }

    def proximas() -> list[dict[str, Any]]:
        agenda = Agenda(lugares.agenda)
        try:
            activas = [p for p in agenda.listar() if p.activo]
        finally:
            agenda.close()
        return [_programacion(p) for p in sorted(activas, key=lambda p: p.proxima)[:5]]

    def api_hoy(_request: Request) -> JSONResponse:
        memoria = _intentar(lambda: len(Memoria().listar("afirmaciones")), (MemoriaError, OSError))
        return JSONResponse({
            "ahora": datetime.now().astimezone().isoformat(),
            "correo": _intentar(correo_de_hoy, (CorreoError, OSError)),
            "agenda": _intentar(agenda_de_hoy, (CalendarioError, OSError)),
            "esperando": trabajos.esperando(),
            "memoria_sin_revisar": memoria.get("datos") if memoria["ok"] else None,
            "programaciones": _intentar(proximas, (AgendaError, OSError)),
            "agenda_activa": lugares.agenda_activa,
            "sesiones": sesiones.listar()[:5],
        })

    # ------------------------------------------------------------ calendario

    def api_calendario(request: Request) -> JSONResponse:
        dias = entero(request.query_params.get("dias"), 7, 1, 60)
        inicio = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
        try:
            calendario = Calendario()
            eventos, avisos = calendario.eventos(inicio, inicio + timedelta(days=dias))
            archivos = [p.name for p in calendario.archivos()]
        except (CalendarioError, OSError) as exc:
            raise ErrorApi(404, str(exc)) from None
        return JSONResponse({"desde": inicio.isoformat(), "dias": dias, "eventos": [_evento(e) for e in eventos],
                             "avisos": avisos, "archivos": archivos})

    # ------------------------------------------------------------ correo

    def buzon() -> Any:
        try:
            return Buzon()
        except CorreoError as exc:
            raise ErrorApi(404, str(exc)) from None

    def api_carpetas(_request: Request) -> JSONResponse:
        with buzon() as b:
            try:
                return JSONResponse({"perfil": str(b.perfil), "carpetas": b.carpetas(),
                                     "direcciones": sorted(b.direcciones())})
            except CorreoError as exc:
                raise ErrorApi(404, str(exc)) from None

    def api_mensajes(request: Request) -> JSONResponse:
        q = request.query_params
        carpeta = q.get("carpeta") or "INBOX"
        filtro = q.get("filtro") or "todos"
        n = entero(q.get("n"), 50, 1, 200)
        dias = entero(q.get("dias"), 0, 0, 365) or None
        with buzon() as b:
            try:
                mensajes = b.listar(carpeta, n=n * 2 if filtro in {"para_mi", "personas"} else n,
                                    dias=dias, solo_sin_leer=filtro == "sin_leer")
                # El mas nuevo descargado, sin filtros: si es viejo, Thunderbird no esta sincronizando.
                ultimo = next(iter(b.listar(carpeta, n=1)), None)
            except CorreoError as exc:
                raise ErrorApi(404, str(exc)) from None
        if filtro == "personas":
            mensajes = [m for m in mensajes if not m.boletin]
        elif filtro == "para_mi":
            mensajes = [m for m in mensajes if m.para_mi and not m.boletin]
        return JSONResponse({"carpeta": carpeta, "mensajes": [_mensaje(m) for m in mensajes[:n]],
                             "ultimo": _fecha(ultimo.fecha) if ultimo is not None else None})

    def leer_mensaje(carpeta: str, n: int) -> Any:
        with buzon() as b:
            try:
                return b.leer(carpeta, n), sorted(b.direcciones())
            except CorreoError as exc:
                raise ErrorApi(404, str(exc)) from None

    def api_mensaje(request: Request) -> JSONResponse:
        q = request.query_params
        mensaje, _ = leer_mensaje(q.get("carpeta") or "INBOX", entero(q.get("n"), 0, 0, 10**9))
        return JSONResponse(_mensaje(mensaje, cuerpo_completo=True))

    async def api_resumen_correo(request: Request) -> JSONResponse:
        from lymi.flows.schema import Workflow

        datos = await cuerpo(request)
        dias = entero(datos.get("dias"), 1, 1, 30)
        flujo = Workflow.model_validate({"name": "resumen_de_correo", "steps": [{
            "id": "resumen", "type": "correo", "op": "resumen", "carpeta": datos.get("carpeta") or "INBOX",
            "dias": dias, "n": 60, "tier": tier(datos.get("tier")), "timeout_s": 900,
        }]})
        titulo = f"Resumen del correo · {dias} dia{'s' if dias != 1 else ''}"
        return JSONResponse(trabajos.lanzar_flujo(flujo, titulo=titulo, tipo="correo-resumen"), status_code=202)

    async def api_borrador(request: Request) -> JSONResponse:
        import asyncio

        from lymi.bench.runner import Recorder
        from lymi.correo import preparar, redactar
        from lymi.ledger import Ledger
        from lymi.llamada import completador

        datos = await cuerpo(request)
        carpeta = texto(datos.get("carpeta") or "INBOX", "carpeta", maximo=200)
        n = entero(datos.get("n"), 0, 1, 10**9)
        instruccion = texto(datos.get("instruccion"), "instruccion", maximo=2000, obligatorio=False)
        nivel = tier(datos.get("tier"))
        mensaje, mias = leer_mensaje(carpeta, n)

        def objetivo(t: Any) -> dict[str, Any]:
            local, etiqueta_local, remoto, etiqueta_remota = trabajos.proveedores()
            cliente = remoto if nivel == "remote" else local
            if cliente is None:
                return {"ok": False, "detalle": f"no hay modelo {nivel}: revisa Proveedores"}
            trabajos.evento(t, f"redacta: {etiqueta_remota if nivel == 'remote' else etiqueta_local}")
            ledger = Ledger(trabajos.ledger)
            try:
                with ledger.run("correo", "borrador", cliente.billing) as run:
                    completar = completador(Recorder(run), cliente, "correo:borrador", max_tokens=1200)
                    propuesta = asyncio.run(redactar(mensaje, completar, instruccion))
            finally:
                ledger.close()
            if not propuesta:
                return {"ok": False, "detalle": "el modelo no escribio nada utilizable", "run_id": run.run_id}
            b = preparar(mensaje, propuesta, de=mias[0] if mias else "")
            trabajos.evento(t, "borrador listo: revisalo antes de guardarlo")
            return {"ok": True, "run_id": run.run_id, "carpeta": carpeta, "n": n,
                    "para": b.para, "asunto": b.asunto, "cuerpo": b.cuerpo}

        vista = trabajos.lanzar_funcion("borrador", f"Respuesta a: {mensaje.asunto[:60]}", objetivo,
                                        contexto={"carpeta": carpeta, "n": n})
        return JSONResponse(vista, status_code=202)

    async def api_guardar_borrador(request: Request) -> JSONResponse:
        from lymi.correo import preparar
        from lymi.ejecutor import (
            CapacidadDenegada,
            Diario,
            Ejecutor,
            EjecutorError,
            cargar_perfil,
            raiz_diario,
        )

        datos = await cuerpo(request)
        carpeta = texto(datos.get("carpeta") or "INBOX", "carpeta", maximo=200)
        n = entero(datos.get("n"), 0, 1, 10**9)
        propuesta = texto(datos.get("cuerpo"), "cuerpo", maximo=20_000)
        mensaje, mias = leer_mensaje(carpeta, n)
        b = preparar(mensaje, propuesta, de=mias[0] if mias else "")
        # Guardar es la aprobacion: lo pide la persona con un clic. Pasa por el
        # ejecutor igual, con su perfil y su diario: se puede deshacer.
        base = Path.cwd()
        diario = Diario(raiz_diario() / f"borradores-{datetime.now(UTC):%Y%m%d}")
        ejecutor = Ejecutor(cargar_perfil(base / "ejecutor.yml", base), diario, base=base)
        try:
            escrito = ejecutor.escribir(f"salidas/respuesta-{n}.eml", b.como_eml().decode("utf-8"))
        except (CapacidadDenegada, EjecutorError, OSError) as exc:
            raise ErrorApi(400, str(exc)) from None
        return JSONResponse({"ruta": str(escrito["ruta"]), "para": b.para, "asunto": b.asunto})

    # ------------------------------------------------------------ chat

    def agencia_de_sesion(sesion: dict[str, Any]) -> Any:
        from lymi.agencia import AgenciaError, cargar_agencia

        modo = sesion.get("modo") or ("agencia" if sesion.get("agencia") else "asistente")
        if modo == "debate":
            return debate(sesion["tier"], sesion.get("presupuesto"))
        if modo == "asistente":
            return asistente(sesion["tier"], lugares.workflows, sesion.get("presupuesto"))
        ruta = archivo_en(lugares.agencias, sesion["agencia"])
        if ruta is None:
            raise ErrorApi(404, f"la agencia {sesion['agencia']} ya no existe")
        try:
            return cargar_agencia(ruta)
        except AgenciaError as exc:
            raise ErrorApi(400, str(exc)) from None

    def turno(sesion: dict[str, Any], texto_nuevo: str) -> dict[str, Any]:
        previos = sesion["mensajes"]
        if previos and previos[-1].get("estado") == "en_curso":
            raise ErrorApi(409, "lymi todavia esta respondiendo el mensaje anterior")
        agencia = agencia_de_sesion(sesion)
        sesiones.agregar(sesion["id"], {"rol": "persona", "texto": texto_nuevo})
        respuesta = sesiones.agregar(sesion["id"], {"rol": "lymi", "texto": "", "estado": "en_curso"})

        def guardar(vista: dict[str, Any]) -> None:
            r = vista.get("resultado") or {}
            ok = r.get("ok", False)
            final = r.get("resultado") if ok else None
            sesiones.actualizar(sesion["id"], respuesta["id"], {
                "estado": "ok" if ok else "fallo",
                "texto": final or "",
                "error": None if ok else (r.get("detalle") or "no termino"),
                "run_id": r.get("run_id"),
                "tareas": r.get("tareas", []),
                "totales": r.get("totales", {}),
            })

        try:
            vista = trabajos.lanzar_agencia(
                agencia, contexto_turno(previos, texto_nuevo), titulo=f"Chat · {sesion['titulo'][:50]}",
                tipo="chat", contexto={"sesion": sesion["id"]}, al_terminar=guardar,
                modelos=(sesion.get("modelo_local"), sesion.get("modelo_remoto")),
            )
        except Exception as exc:
            sesiones.actualizar(sesion["id"], respuesta["id"], {"estado": "fallo", "error": str(exc)})
            raise
        sesiones.actualizar(sesion["id"], respuesta["id"], {"trabajo": vista["id"]})
        return vista

    def api_sesiones(_request: Request) -> JSONResponse:
        return JSONResponse(sesiones.listar())

    def api_modelos(_request: Request) -> JSONResponse:
        """Que modelos hay para elegir: los de tu Ollama y los de tu proveedor remoto."""
        import os

        import httpx

        from lymi.bench.wiring import MODELOS_REMOTOS
        from lymi.providers import claude_code
        from lymi.providers.local import DEFAULT_MODEL, DEFAULT_URL

        url = os.getenv("LYMI_OLLAMA_URL", DEFAULT_URL).rstrip("/")
        locales: list[dict[str, Any]] = []
        error_local = None
        try:
            respuesta = httpx.get(f"{url}/api/tags", timeout=3.0)
            respuesta.raise_for_status()
            for m in respuesta.json().get("models", []):
                detalles = m.get("details") or {}
                locales.append({"id": m.get("name"), "bytes": m.get("size"),
                                "parametros": detalles.get("parameter_size"),
                                "cuantizacion": detalles.get("quantization_level")})
        except (httpx.HTTPError, ValueError) as exc:
            error_local = f"Ollama no responde en {url}: {exc}"
        if claude_code.disponible():
            remoto = "claude code (suscripcion)"
        elif os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"):
            remoto = "anthropic api (se paga por token)"
        else:
            remoto = None
        return JSONResponse({
            "locales": locales, "local_defecto": os.getenv("LYMI_LOCAL_MODEL", DEFAULT_MODEL),
            "error_local": error_local, "remoto": remoto,
            "remotos": [{"id": alias, "api": modelo} for alias, modelo in MODELOS_REMOTOS.items()] if remoto else [],
            "remoto_defecto": "opus",
        })

    async def api_nueva_sesion(request: Request) -> JSONResponse:
        datos = await cuerpo(request)
        mensaje = validar_mensaje(datos.get("texto"))
        agencia = datos.get("agencia") or None
        if agencia is not None and archivo_en(lugares.agencias, str(agencia)) is None:
            raise ErrorApi(404, "agencia no encontrada")
        modo = "agencia" if agencia else str(datos.get("modo") or "asistente")
        modelo_local = texto(datos.get("modelo_local"), "modelo_local", maximo=80, obligatorio=False) or None
        modelo_remoto = texto(datos.get("modelo_remoto"), "modelo_remoto", maximo=80, obligatorio=False) or None
        presupuesto = entero(datos.get("presupuesto"), 0, 0, 2_000_000) or None
        sesion = sesiones.crear(mensaje, tier(datos.get("tier")), agencia, modo=modo, modelo_local=modelo_local,
                                modelo_remoto=modelo_remoto, presupuesto=presupuesto)
        vista = turno(sesion, mensaje)
        return JSONResponse({"sesion": sesiones.obtener(sesion["id"]), "trabajo": vista}, status_code=202)

    def api_sesion(request: Request) -> JSONResponse:
        return JSONResponse(sesiones.obtener(request.path_params["sesion"]))

    async def api_mensaje_chat(request: Request) -> JSONResponse:
        datos = await cuerpo(request)
        sesion = sesiones.obtener(request.path_params["sesion"])
        vista = turno(sesion, validar_mensaje(datos.get("texto")))
        return JSONResponse({"sesion": sesiones.obtener(sesion["id"]), "trabajo": vista}, status_code=202)

    def api_borrar_sesion(request: Request) -> JSONResponse:
        sesiones.borrar(request.path_params["sesion"])
        return JSONResponse({"ok": True})

    # ------------------------------------------------------------ agencia

    def api_agencias(_request: Request) -> JSONResponse:
        from lymi.agencia import AgenciaError, cargar_agencia

        lista: list[dict[str, Any]] = []
        if lugares.agencias.is_dir():
            for ruta in sorted(lugares.agencias.glob("*.y*ml")):
                try:
                    a = cargar_agencia(ruta)
                except AgenciaError as exc:
                    lista.append({"archivo": ruta.name, "error": str(exc)})
                    continue
                agentes = a.agentes()
                lista.append({
                    "archivo": ruta.name, "nombre": a.name, "descripcion": a.description,
                    "departamentos": len(a.departamentos), "agentes": len(agentes),
                    "remotos": sum(1 for x in agentes.values() if x.tier == "remote"),
                })
        return JSONResponse({"carpeta": str(lugares.agencias), "agencias": lista})

    def api_agencia(request: Request) -> JSONResponse:
        from lymi.agencia import AgenciaError, cargar_agencia
        from lymi.flows.plan import _costo_agencia

        ruta = archivo_en(lugares.agencias, request.path_params["archivo"])
        if ruta is None:
            raise ErrorApi(404, "agencia no encontrada")
        try:
            a = cargar_agencia(ruta)
        except AgenciaError as exc:
            return JSONResponse({"archivo": ruta.name, "error": str(exc)})
        departamentos = []
        for nombre_dep, dep in a.departamentos.items():
            agentes = []
            for nombre, ag in dep.agentes.items():
                completo = f"{nombre_dep}.{nombre}"
                agentes.append({
                    "nombre": nombre, "completo": completo, "descripcion": ag.descripcion, "tier": ag.tier,
                    "modelo": ag.modelo, "respaldo": ag.respaldo, "herramientas": ag.herramientas,
                    "delega_a": sorted(a.destinos(completo)), "puede_crear": ag.puede_crear,
                    "lider": nombre == dep.jefe,
                })
            departamentos.append({"nombre": nombre_dep, "descripcion": dep.descripcion, "agentes": agentes})
        return JSONResponse({
            "archivo": ruta.name, "nombre": a.name, "descripcion": a.description,
            "limites": a.limites.model_dump(), "departamentos": departamentos, "costo": _costo_agencia(str(ruta)),
        })

    async def api_correr_agencia(request: Request) -> JSONResponse:
        from lymi.agencia import AgenciaError, cargar_agencia

        ruta = archivo_en(lugares.agencias, request.path_params["archivo"])
        if ruta is None:
            raise ErrorApi(404, "agencia no encontrada")
        datos = await cuerpo(request)
        tarea = texto(datos.get("tarea"), "tarea", maximo=8000)
        agente = texto(datos.get("agente"), "agente", maximo=120, obligatorio=False) or None
        try:
            agencia = cargar_agencia(ruta)
        except AgenciaError as exc:
            raise ErrorApi(400, str(exc)) from None
        if agente is not None and agencia.resolver(agente) is None:
            raise ErrorApi(400, f"{agente} no es un agente ni un departamento de {agencia.name}")
        vista = trabajos.lanzar_agencia(agencia, tarea, titulo=f"{agencia.name}: {tarea[:60]}", agente=agente,
                                        contexto={"archivo": ruta.name})
        return JSONResponse(vista, status_code=202)

    # ------------------------------------------------------------ memoria

    def api_memoria(request: Request) -> JSONResponse:
        estado = request.query_params.get("estado") or "afirmaciones"
        if estado not in {"afirmaciones", "hechos", "descartadas"}:
            raise ErrorApi(400, "estado: afirmaciones, hechos o descartadas")
        memoria = Memoria()
        try:
            notas = memoria.listar(estado)
            cuentas = {e: len(memoria.listar(e)) for e in ("afirmaciones", "hechos", "descartadas")}
        except (MemoriaError, OSError) as exc:
            raise ErrorApi(400, str(exc)) from None
        return JSONResponse({"raiz": str(memoria.raiz), "estado": estado, "cuentas": cuentas,
                             "notas": [_nota(n) for n in notas]})

    def api_buscar_memoria(request: Request) -> JSONResponse:
        consulta = texto(request.query_params.get("q"), "q", maximo=300)
        recuerdos = Memoria().buscar(consulta, 20)
        return JSONResponse([
            {**_nota(r.nota), "fragmento": r.fragmento, "linea": r.linea, "puntaje": round(r.puntaje, 3)}
            for r in recuerdos
        ])

    async def api_anotar(request: Request) -> JSONResponse:
        datos = await cuerpo(request)
        memoria = Memoria()
        try:
            nota = memoria.anotar(
                texto(datos.get("texto"), "texto", maximo=4000),
                fuente=texto(datos.get("fuente"), "fuente", maximo=300, obligatorio=False) or "anotado a mano",
                agente="persona",
                hecho=True,  # lo escribe la persona, que es quien decide que es cierto
            )
        except MemoriaError as exc:
            raise ErrorApi(400, str(exc)) from None
        return JSONResponse(_nota(nota), status_code=201)

    def mover_nota(accion: str) -> Callable[[Request], JSONResponse]:
        def manejar(request: Request) -> JSONResponse:
            memoria = Memoria()
            try:
                nota = getattr(memoria, accion)(request.path_params["nota"])
            except MemoriaError as exc:
                raise ErrorApi(400, str(exc)) from None
            return JSONResponse(_nota(nota))

        return manejar

    # ------------------------------------------------------------ programaciones

    def con_agenda(funcion: Callable[[Any], Any]) -> Any:
        agenda = Agenda(lugares.agenda)
        try:
            return funcion(agenda)
        except AgendaError as exc:
            raise ErrorApi(400, str(exc)) from None
        finally:
            agenda.close()

    def api_programaciones(_request: Request) -> JSONResponse:
        from lymi.triggers.ganchos import Ganchos

        programadas = con_agenda(lambda a: [_programacion(p) for p in a.listar()])
        ganchos = Ganchos(lugares.ganchos)
        try:
            hooks = [{"nombre": g.nombre, "workflow": g.workflow.name, "esquema": g.esquema, "activo": g.activo,
                      "aprobados": sorted(g.aprobados)} for g in ganchos.listar()]
        finally:
            ganchos.close()
        return JSONResponse({"programaciones": programadas, "webhooks": hooks,
                             "agenda_activa": lugares.agenda_activa})

    async def api_programar(request: Request) -> JSONResponse:
        datos = await cuerpo(request)
        ruta = archivo_en(lugares.workflows, str(datos.get("workflow") or ""))
        if ruta is None:
            raise ErrorApi(404, "workflow no encontrado")
        aprobados = datos.get("aprobados") or []
        entradas = datos.get("entradas") or {}
        if not isinstance(aprobados, list) or not all(isinstance(x, str) for x in aprobados):
            raise ErrorApi(400, "aprobados debe ser una lista de ids de paso")
        if not isinstance(entradas, dict):
            raise ErrorApi(400, "entradas debe ser un objeto")

        def agregar(agenda: Any) -> dict[str, Any]:
            prog = agenda.agregar(ruta.resolve(), texto(datos.get("cron"), "cron", maximo=100),
                                  zona=texto(datos.get("zona") or "UTC", "zona", maximo=64),
                                  entradas=entradas, aprobados=aprobados)
            return {**_programacion(prog), "sin_autorizar": agenda.efectos_sin_autorizar(prog)}

        return JSONResponse(con_agenda(agregar), status_code=201)

    def accion_programacion(accion: str) -> Callable[[Request], JSONResponse]:
        def manejar(request: Request) -> JSONResponse:
            prog_id = request.path_params["prog"]
            if accion == "quitar":
                con_agenda(lambda a: a.quitar(prog_id))
                return JSONResponse({"ok": True})
            return JSONResponse(_programacion(con_agenda(lambda a: getattr(a, accion)(prog_id))))

        return manejar

    # ------------------------------------------------------------ codigo

    def raiz_codigo(valor: Any) -> Path:
        from lymi.ejecutor.capacidades import CapacidadDenegada, Perfil, expandir, validar_forma

        crudo = texto(valor, "raiz", maximo=1000)
        try:
            validar_forma(crudo)
            ruta = expandir(crudo, Path.cwd())
        except CapacidadDenegada as exc:
            raise ErrorApi(400, str(exc)) from None
        if (zona := Perfil.por_defecto(Path.cwd()).zona_vetada(ruta)) is not None:
            raise ErrorApi(403, f"{ruta} esta en una zona protegida ({zona})")
        if not ruta.is_dir():
            raise ErrorApi(404, f"{ruta} no es una carpeta")
        return ruta

    async def api_codigo(request: Request) -> JSONResponse:
        import asyncio

        from lymi.codigo import IndiceError, abrir
        from lymi.codigo import formato as fmt

        datos = await cuerpo(request)
        op = datos.get("op")
        raiz = raiz_codigo(datos.get("raiz"))

        def consultar() -> dict[str, Any]:
            with abrir(raiz) as indice:
                if op == "indexar":
                    return {"texto": f"indice al dia: {indice.ultima.resumen()}", "datos": indice.mapa("", 400)}
                if op == "buscar":
                    d = indice.buscar(texto(datos.get("consulta"), "consulta", maximo=200), 50)
                    return {"texto": fmt.buscar(d), "datos": d}
                if op == "esqueleto":
                    d = indice.esqueleto(texto(datos.get("ruta"), "ruta", maximo=500))
                    return {"texto": fmt.esqueleto(d), "datos": d}
                if op == "fragmento":
                    d = indice.fragmento(texto(datos.get("nombre"), "nombre", maximo=200))
                    return {"texto": fmt.fragmentos(d), "datos": d}
                if op == "llamadores":
                    nombre = texto(datos.get("nombre"), "nombre", maximo=200)
                    d = indice.llamadores(nombre)
                    return {"texto": fmt.llamadores(nombre, d), "datos": d}
                if op == "impacto":
                    d = indice.impacto(texto(datos.get("nombre"), "nombre", maximo=200),
                                       entero(datos.get("profundidad"), 3, 1, 6))
                    return {"texto": fmt.impacto(d), "datos": d}
                if op == "mapa":
                    prefijo = texto(datos.get("ruta"), "ruta", maximo=500, obligatorio=False)
                    d = indice.mapa(prefijo, 400)
                    return {"texto": fmt.mapa(d), "datos": d}
                raise ErrorApi(400, "op: indexar, buscar, esqueleto, fragmento, llamadores, impacto o mapa")

        try:
            salida = await asyncio.to_thread(consultar)
        except IndiceError as exc:
            raise ErrorApi(400, str(exc)) from None
        return JSONResponse(json.loads(json.dumps({"raiz": str(raiz), **salida}, default=str)))

    # ------------------------------------------------------------ web

    async def api_web(request: Request) -> JSONResponse:
        from lymi.flows.schema import Workflow

        datos = await cuerpo(request)
        op = datos.get("op")
        paso: dict[str, Any] = {"id": "web", "type": "web", "op": op, "timeout_s": 600}
        if op in {"extraer", "mapear"}:
            paso["url"] = texto(datos.get("url"), "url", maximo=2000)
            titulo = f"{'Leer' if op == 'extraer' else 'Mapear'} {paso['url'][:60]}"
        elif op == "buscar":
            paso["consulta"] = texto(datos.get("consulta"), "consulta", maximo=500)
            titulo = f"Buscar: {paso['consulta'][:60]}"
        elif op == "investigar":
            paso["pregunta"] = texto(datos.get("pregunta"), "pregunta", maximo=2000)
            paso["tier"] = tier(datos.get("tier"))
            urls = datos.get("urls") or []
            if not isinstance(urls, list):
                raise ErrorApi(400, "urls debe ser una lista")
            paso["urls"] = [texto(u, "url", maximo=2000) for u in urls[:10]]
            titulo = f"Investigar: {paso['pregunta'][:60]}"
        else:
            raise ErrorApi(400, "op: extraer, mapear, buscar o investigar")
        flujo = Workflow.model_validate({"name": f"web_{op}", "steps": [paso]})
        return JSONResponse(trabajos.lanzar_flujo(flujo, titulo=titulo, tipo=f"web-{op}"), status_code=202)

    # ------------------------------------------------------------ diario del PC

    def api_diario(_request: Request) -> JSONResponse:
        from lymi.ejecutor import raiz_diario

        raiz = raiz_diario()
        corridas: list[dict[str, Any]] = []
        if raiz.is_dir():
            for carpeta in raiz.iterdir():
                registro = carpeta / "diario.jsonl"
                if not registro.is_file():
                    continue
                try:
                    entradas = [json.loads(x) for x in registro.read_text(encoding="utf-8").splitlines() if x.strip()]
                except (OSError, json.JSONDecodeError):
                    continue
                deshecho = carpeta / "DESHECHO"
                corridas.append({
                    "corrida": carpeta.name, "entradas": entradas[-50:], "total": len(entradas),
                    "ultima": entradas[-1]["ts"] if entradas else None,
                    "deshecho": deshecho.read_text(encoding="utf-8").strip() if deshecho.exists() else None,
                })
        corridas.sort(key=lambda c: c["ultima"] or "", reverse=True)
        return JSONResponse({"raiz": str(raiz), "corridas": corridas[:100]})

    def api_perfil(_request: Request) -> JSONResponse:
        from lymi.ejecutor import cargar_perfil
        from lymi.ejecutor.capacidades import PerfilError

        base = Path.cwd()
        archivo = base / "ejecutor.yml"
        try:
            perfil = cargar_perfil(archivo, base)
        except PerfilError as exc:
            raise ErrorApi(400, f"ejecutor.yml invalido: {exc}") from None
        return JSONResponse({
            "archivo": str(archivo) if archivo.exists() else f"{archivo} (no existe: rige el perfil minimo)",
            "escribibles": [str(p) for p in perfil.escribibles],
            "legibles": [str(p) for p in perfil.legibles],
            "comandos": {n: sorted(getattr(c, "subcomandos", None) or []) for n, c in perfil.comandos.items()},
        })

    def api_deshacer(request: Request) -> JSONResponse:
        from lymi.ejecutor import DiarioError, deshacer, raiz_diario

        corrida = request.path_params["corrida"]
        if not corrida.replace("-", "").replace("_", "").isalnum() or len(corrida) > 80:
            raise ErrorApi(404, "corrida no encontrada")
        try:
            informe = deshacer(raiz_diario() / corrida)
        except DiarioError as exc:
            raise ErrorApi(400, str(exc)) from None
        return JSONResponse({"informe": informe})

    def manejar_sesion_error(funcion: Callable[..., Any]) -> Callable[..., Any]:
        """Los errores de sesion son 404/400 de la API, no 500."""
        import functools
        import inspect

        if inspect.iscoroutinefunction(funcion):
            @functools.wraps(funcion)
            async def asincrona(request: Request) -> JSONResponse:
                try:
                    return await funcion(request)
                except SesionError as exc:
                    raise ErrorApi(404 if "no encontrada" in str(exc) else 400, str(exc)) from None
            return asincrona

        @functools.wraps(funcion)
        def sincrona(request: Request) -> JSONResponse:
            try:
                return funcion(request)
            except SesionError as exc:
                raise ErrorApi(404 if "no encontrada" in str(exc) else 400, str(exc)) from None
        return sincrona

    # ------------------------------------------------------------ voz

    from lymi.voz import Lector, VozError

    lector = Lector()

    def api_voz(_request: Request) -> JSONResponse:
        from lymi.voz import estado

        return JSONResponse(estado())

    async def api_transcribir(request: Request) -> JSONResponse:
        import asyncio

        from lymi.voz import MAX_BYTES_AUDIO, transcribir

        audio = bytearray()
        async for trozo in request.stream():
            audio += trozo
            if len(audio) > MAX_BYTES_AUDIO:
                raise ErrorApi(413, "el audio es demasiado largo: dicta en partes mas cortas")
        idioma = (request.query_params.get("idioma") or "es")[:5]
        if not idioma.replace("-", "").isalpha():
            raise ErrorApi(400, "idioma invalido")
        try:
            t = await asyncio.to_thread(transcribir, bytes(audio), idioma)
        except VozError as exc:
            raise ErrorApi(400, str(exc)) from None
        return JSONResponse({"texto": t.texto, "modelo": t.modelo, "segundos": t.segundos})

    async def api_hablar(request: Request) -> JSONResponse:
        datos = await cuerpo(request)
        try:
            lector.hablar(texto(datos.get("texto"), "texto", maximo=20_000))
        except VozError as exc:
            raise ErrorApi(400, str(exc)) from None
        return JSONResponse({"ok": True})

    def api_callar(_request: Request) -> JSONResponse:
        return JSONResponse({"callado": lector.callar()})

    s = manejar_sesion_error
    return [
        Route("/api/hoy", api_hoy, methods=["GET"]),
        Route("/api/calendario", api_calendario, methods=["GET"]),
        Route("/api/correo/carpetas", api_carpetas, methods=["GET"]),
        Route("/api/correo/mensajes", api_mensajes, methods=["GET"]),
        Route("/api/correo/mensaje", api_mensaje, methods=["GET"]),
        Route("/api/correo/resumen", api_resumen_correo, methods=["POST"]),
        Route("/api/correo/borrador", api_borrador, methods=["POST"]),
        Route("/api/correo/borrador/guardar", api_guardar_borrador, methods=["POST"]),
        Route("/api/modelos", api_modelos, methods=["GET"]),
        Route("/api/sesiones", s(api_sesiones), methods=["GET"]),
        Route("/api/sesiones", s(api_nueva_sesion), methods=["POST"]),
        Route("/api/sesiones/{sesion}", s(api_sesion), methods=["GET"]),
        Route("/api/sesiones/{sesion}", s(api_borrar_sesion), methods=["DELETE"]),
        Route("/api/sesiones/{sesion}/mensajes", s(api_mensaje_chat), methods=["POST"]),
        Route("/api/agencias", api_agencias, methods=["GET"]),
        Route("/api/agencias/{archivo}", api_agencia, methods=["GET"]),
        Route("/api/agencias/{archivo}/correr", api_correr_agencia, methods=["POST"]),
        Route("/api/memoria", api_memoria, methods=["GET"]),
        Route("/api/memoria", api_anotar, methods=["POST"]),
        Route("/api/memoria/buscar", api_buscar_memoria, methods=["GET"]),
        Route("/api/memoria/{nota}/promover", mover_nota("promover"), methods=["POST"]),
        Route("/api/memoria/{nota}/descartar", mover_nota("descartar"), methods=["POST"]),
        Route("/api/programaciones", api_programaciones, methods=["GET"]),
        Route("/api/programaciones", api_programar, methods=["POST"]),
        Route("/api/programaciones/{prog}/pausar", accion_programacion("pausar"), methods=["POST"]),
        Route("/api/programaciones/{prog}/reanudar", accion_programacion("reanudar"), methods=["POST"]),
        Route("/api/programaciones/{prog}", accion_programacion("quitar"), methods=["DELETE"]),
        Route("/api/codigo", api_codigo, methods=["POST"]),
        Route("/api/web", api_web, methods=["POST"]),
        Route("/api/voz", api_voz, methods=["GET"]),
        Route("/api/voz/transcribir", api_transcribir, methods=["POST"]),
        Route("/api/voz/hablar", api_hablar, methods=["POST"]),
        Route("/api/voz/callar", api_callar, methods=["POST"]),
        Route("/api/diario", api_diario, methods=["GET"]),
        Route("/api/equipo/perfil", api_perfil, methods=["GET"]),
        Route("/api/diario/{corrida}/deshacer", api_deshacer, methods=["POST"]),
    ]
