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

### App de escritorio

```bash
uv sync --extra escritorio
uv run lymi escritorio                     # ventana propia; la agenda corre mientras esta abierta
uv run lymi escritorio --verificar-red 60  # mide con quien habla todo el arbol de procesos
```

La ventana usa Qt WebEngine (Chromium abierto, sin servicios de Google ni de
Microsoft). Medido: **0 conexiones fuera de la maquina en 60 s**. WebView2, el
motor de Windows, abre conexiones a Microsoft que ninguna bandera apaga: solo se
usa con `--motor edge`, avisado. Los datos viven en `%LOCALAPPDATA%\lymi`
(Windows) o `~/.local/share/lymi` (Linux), o donde diga `LYMI_HOME`.

Que trae: **Hoy** (agenda, correo que importa, lo que espera tu decision), **Chat**
con herramientas (asistente, debate entre agentes o una de tus agencias; modelo
local o remoto, y tope de tokens por conversacion), **Correo** (Thunderbird, solo
lectura, resumen por prioridad y borradores .eml), **Calendario**, **Agencia**
(organigrama y corridas), **Workflows** con editor de nodos (paleta, lienzo,
inspector, plan sin gastar un token, costo medido por nodo, ejecucion en vivo con
aprobaciones), **Programaciones**, **Memoria**, **Codigo**, **Web**, **Tu PC**
(diario con deshacer) y el ledger completo.

Cerrar la ventana la deja en la **bandeja del sistema**: la agenda sigue
corriendo y lymi avisa con notificaciones locales cuando una programacion
termina, cuando algo espera tu aprobacion y 15 minutos antes de cada evento del
calendario. Salir de verdad es desde el menu del icono.

### Voz

Boton de microfono en el chat: dicta y lymi transcribe con **whisper.cpp en tu
equipo** (sin red, sin telemetria). Descarga `whisper-cli` de
<https://github.com/ggml-org/whisper.cpp/releases> y un modelo de
<https://huggingface.co/ggerganov/whisper.cpp> en la carpeta `voz/` de los datos
(o `LYMI_WHISPER` / `LYMI_WHISPER_MODELO`). lymi sugiere el modelo segun tu RAM
(tiny < 8 GB < base < 16 GB <= small) y siempre dice cual transcribio. Las
respuestas se pueden leer en voz alta con la voz del sistema (SAPI en Windows,
`say` en macOS, `espeak-ng` en Linux). El audio se borra al transcribirse.

### Docker (servidor, sin escritorio)

```bash
docker build -t lymi .
docker run -d --name lymi -v lymi-datos:/datos lymi
```

Corre `lymi serve`: la agenda y los webhooks, como usuario sin privilegios y con
los datos en el volumen. La interfaz no va en la imagen a proposito (solo
escucha en loopback). Los webhooks necesitan un almacen de claves del sistema;
sin el, se rechazan (falla del lado seguro). El modelo local se busca en
`host.docker.internal:11434`.

### Instaladores

`.github/workflows/instaladores.yml` los construye en cada sistema al publicar
una etiqueta `v*` (o a mano): `.exe` (Inno Setup, por usuario, sin administrador),
`.tar.gz` con `instalar.sh` sin root para Linux, y `.dmg` para macOS. En Linux el
programa empaquetado se abre y se vigila su red: si habla con alguien, el
trabajo falla. Para construir localmente:

```bash
uv sync --extra escritorio --extra empaquetar
uv run pyinstaller empaquetado/lymi.spec --noconfirm   # dist/lymi/
```

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

uv run lymi agencia plan agencias/startup.example.yml     # organigrama, permisos y topes duros
uv run lymi agencia evaluar --modelo qwen2.5:3b -n 10     # que modelo sirve como agente, medido
uv run lymi memoria pendientes                            # lo que anotaron los agentes, por revisar

uv run lymi correo carpetas                               # tu correo local de Thunderbird (solo lectura)
uv run lymi correo resumen --dias 1                       # el dia en una pagina, con el modelo local
uv run lymi correo borrador INBOX:57 --instruccion "..."  # propone la respuesta; la envias tu
uv run lymi calendario hoy --dias 7                       # tu agenda, desde archivos .ics locales
uv run lymi flow run workflows/informe-del-dia.yml        # correo + agenda en una pagina
uv run lymi agencia correr agencias/startup.example.yml "@producto donde se valida una URL?"
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
