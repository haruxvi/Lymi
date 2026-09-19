# lymi

[![CI](https://github.com/haruxvi/lymi/actions/workflows/ci.yml/badge.svg)](https://github.com/haruxvi/lymi/actions/workflows/ci.yml)
[![Licencia: Apache-2.0](https://img.shields.io/badge/licencia-Apache--2.0-blue.svg)](LICENSE)
![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)

Orquestador de agentes local-first con **contabilidad de tokens** y **control de
egress** auditables.

> Estado: **alfa temprana** (`0.0.1`). Hay ledger, banco de pruebas con recibo,
> proveedores (API, suscripcion de Claude Code, Ollama local) y workflows
> declarativos con aprobaciones. Todavia no hay agente autonomo ni interfaz
> grafica: las pantallas de `design/` son maquetas.

## Por que existe

La mayoria de los "sistemas de agentes" y "segundos cerebros" afirman ahorrar
tokens sin publicar contra que comparan, y afirman ser "locales" mientras envian
cada documento por una API remota. Ninguna de las dos afirmaciones es
verificable, y por eso ninguna es seria.

lymi invierte el orden: primero la medicion, despues las funcionalidades.

- **Ledger de tokens**: toda llamada a un modelo queda registrada con proveedor,
  modelo, tokens (incluido cache), costo, latencia y modo de facturacion.
- **Log de egress**: que salio de la maquina, hacia donde, y con que hash. Se
  guarda el hash y el tamano del payload, nunca el payload.
- **Linea base publica**: el agente ingenuo contra el que comparamos es codigo de
  este repositorio, ejecutable por cualquiera.

La afirmacion que el proyecto debe sostener, y como se falsa, esta en
[docs/METHODOLOGY.md](docs/METHODOLOGY.md). El plan por fases, en
[docs/ROADMAP.md](docs/ROADMAP.md).

## Proveedores

Tu eliges. Los tres modos conviven y el ledger los mantiene separados:

| Modo | Ejemplo | Contexto lo arma | Se mide en |
|---|---|---|---|
| `api` | Anthropic / OpenAI con API key | **lymi** | tokens y dolares |
| `subscription` | Claude Code headless | el harness externo | tokens (cuota fija) |
| `local` | Ollama en tu maquina | **lymi** | tokens (sin costo monetario) |

El modo `api` es el unico donde lymi controla el prompt y por lo tanto el unico
donde el ahorro es demostrable de punta a punta. En modo `subscription` la moneda
no son dolares sino tu ventana de uso.

## Instalacion

```bash
uv sync --extra dev
cp .env.example .env
```

Ninguna credencial es obligatoria: lymi corre con los proveedores que tengas
configurados y omite los demas.

## Seguridad

- El payload enviado a un proveedor **no se persiste**; solo su SHA-256 y su
  tamano. El log es auditable sin ser una segunda copia de tus datos.
- El tier "local" **verifica que su endpoint resuelva a loopback**. Si apunta a
  un host remoto, falla al arrancar salvo opt-in explicito. Un tier "local" que
  envia datos a otra maquina seria exactamente la mentira que este proyecto
  existe para no cometer.
- Sin `shell=True` en subprocesos, SQL siempre parametrizado, timeouts explicitos
  en toda llamada de red.
- **Acciones en tu PC** (paso `pc`) solo por el ejecutor: seis operaciones, lista
  blanca de carpetas y comandos, jamas un shell, y un diario que `lymi undo`
  revierte. El sistema operativo, tus credenciales, `runs/` y `.git` estan vetados
  aunque el perfil diga otra cosa.
- **Lectura de la web** (paso `web`) con guardia contra SSRF: cada salto se resuelve
  y se conecta a la IP ya comprobada, nunca a tu red interna; se respeta robots.txt;
  una URL o consulta con un secreto no sale; el texto oculto de las paginas se
  descarta antes de que lo vea un modelo.

## Uso rapido

```bash
uv run lymi ui             # la app en el navegador, solo en esta maquina
uv run lymi setup          # que proveedores estan listos y que falta
uv run lymi bench snake    # mide una tarea contra la linea base y emite el recibo
uv run lymi ledger         # corridas registradas

uv run lymi web leer https://ejemplo.com          # la pagina como markdown limpio
uv run lymi web investigar "tu pregunta"          # responde con fuentes y verifica cada cita
uv run lymi flow run workflows/resumen-de-pagina.yml -i url=https://ejemplo.com
uv run lymi undo <corrida>                        # deshace lo que una corrida hizo en tus archivos

uv run lymi codigo esqueleto src/lymi/web/red.py  # firmas sin cuerpos, con el ahorro medido
uv run lymi codigo impacto revisar_saliente        # que codigo y que pruebas toca un cambio
claude mcp add lymi-codigo -- uv run lymi codigo servir   # el mismo mapa para Claude Code
```

## Desarrollo

```bash
uv sync --extra dev
uv run --extra dev pytest -q
uv run --extra dev ruff check src tests
node design/estilos/sincronizar.mjs --check
```

Ver [CONTRIBUTING.md](CONTRIBUTING.md). Para reportar una vulnerabilidad, sigue
[SECURITY.md](SECURITY.md): no abras un issue publico.

## Licencia

Apache-2.0. Ver [`LICENSE`](LICENSE) y [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
