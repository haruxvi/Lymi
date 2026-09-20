# lymi — instrucciones para el agente

Este archivo se carga solo al abrir una sesion en este directorio. Es la puerta
de entrada: dice que es el proyecto, donde esta el contexto y que reglas no se
rompen. **Leelo entero antes de tocar nada.**

## Retomar una sesion (en este orden)

1. `docs/CONTEXTO.md` — que es lymi, por que existe, vision, decisiones tomadas.
2. `docs/PENDIENTES.md` — que falta para que este operativo, en orden.
3. `docs/BITACORA.md` — que se hizo por ultimo y en que quedo cada hilo.
4. `CLAUDE.local.md` (no versionado) — rutas, maquina y cuentas del desarrollador,
   incluida la ruta del vault de Obsidian. En el vault, `index.md` primero: es la
   memoria larga del proyecto (patron LLM Wiki).
5. Corre las pruebas antes de cambiar codigo (ver "Verificar").

No le pidas al usuario que re-explique el proyecto: esta todo aqui. Si algo no
esta documentado y lo descubres, **documentalo** antes de terminar la sesion.

## Quien es el usuario y como trabajar con el

- Escribe en espanol; responde en espanol.
- Detesta el "humo": afirmaciones no verificables, graficos decorativos, agentes
  que queman tokens. Toda afirmacion de ahorro se mide contra una linea base
  publica, o no se hace.
- Exige seguridad maxima, codigo limpio, pruebas unitarias y de rendimiento.
- Decidio que lymi tenga **todas** las funcionalidades de Hermes Agent, mejoradas,
  conviviendo con el ecosistema (MCP, n8n, Obsidian, ECC). No re-discutir alcance.
- Audiencia: desde un estudiante (solo modelo local, sin API key) hasta un CEO
  (auditoria de egress presentable).
- Rechazo explicitamente: diseno "robotico" (panel gris, cajas con borde), estilo
  "carta de vinos" (serif sobre papel), terminal pura, y efectos de scroll
  cinematograficos. Direccion visual elegida: **risografia** (ver CONTEXTO.md).

## Reglas de desarrollo (no negociables)

1. **Nada sin prueba.** Una funcionalidad no esta hecha hasta que una prueba la
   ejercita. Integraciones: contra un servidor real, no solo mocks.
2. **Todo pasa por el ledger.** Toda llamada a un modelo o integracion se registra
   (tokens, costo, egress). Una llamada sin registrar invalida la corrida.
3. **El payload nunca se persiste.** Solo su SHA-256 y tamano.
4. **Secretos** solo en variables de entorno o en el almacen del sistema
   (`keyring`). Nunca en YAML, prompts, logs, vistas previas ni SQLite.
5. **Ningun texto ajeno ejecuta codigo.** Plantillas = busqueda de rutas pura.
   Condiciones = lista blanca sobre `ast`. Nunca `eval`, nunca Jinja completo.
6. **Minimo privilegio.** Pasos con efectos piden aprobacion, nunca se reintentan;
   en modo desatendido solo corren los preaprobados por nombre.
7. **Nunca inventar tarifas, esquemas ni APIs.** Verificar contra el SDK instalado
   (`inspect.signature`) o una sonda real antes de escribir el cliente.
8. **Licencias.** Solo se copia codigo MIT/BSD/Apache con atribucion en
   `THIRD_PARTY_NOTICES.md`. Sin licencia = solo ideas. Nunca copiar codigo sin
   licencia.
9. **Integrar donde hay ecosistema; construir solo lo que nadie tiene.** MCP para
   conectores, Serena para retrieval, esquemas de ECC para skills.
10. **No hacer commits ni push sin que el usuario lo pida.**
11. Comentarios explican el **por que**, no el que. Nombres en espanol, como el resto.
12. **Evidencia antes de afirmar** (superpowers): no decir "pasa" o "funciona" sin
    haber corrido la verificacion en ese mismo momento y leido la salida.
13. **Causa raiz antes de arreglar** (superpowers): ninguna correccion de un fallo
    sin entender por que ocurre.
14. **Al cerrar una sesion:** actualizar `docs/BITACORA.md`, `docs/PENDIENTES.md` y
    el wiki del vault (`index.md`, `log.md`, pagina de sesion).

## Verificar

```bash
uv sync --extra dev
uv run --extra dev pytest -q
.venv/Scripts/python.exe -m ruff check src tests
node design/estilos/sincronizar.mjs --check
```

Estado al 2026-09-19: **696 pruebas: 694 verdes, 1 omitida, 1 de rendimiento que falla por el disco; ruff limpio, estilos sincronizados.**

El roadmap completo hacia "elite" (13 ejes con su puerta medible) esta en
`docs/ELITE.md` y en el vault como `camino-a-elite`.
La que falla es `test_perf.py::test_registro_de_llamadas_es_despreciable` y depende
del disco: ese dia un commit de SQLite en crudo tardaba 10 ms por fila en esta
maquina (el ledger, 2,3 ms; limite 1 ms). El codigo del ledger no cambio.
La CI (`.github/workflows/ci.yml`) corre lo mismo en cada push y PR.

## Trampas conocidas (ya costaron tiempo)

- `uv sync` sin `--extra dev` **desinstala pytest y ruff** en silencio.
- Consola de Windows en cp1252: no imprime caracteres de caja. `cli.py` reconfigura
  a UTF-8 y `report.py` cae a ASCII.
- En heredocs de bash, `\n` dentro de un string de Python se vuelve salto de linea
  real y rompe el archivo. Usar la herramienta Edit/Write para esos casos.
- `mcp>=2,<3`: usa `httpx2` (no `httpx`) y snake_case (`is_error`,
  `structured_content`). Leer `isError` hace pasar fallos como exitos.
- `claude -p --output-format json`: fallos llegan con `is_error: true` pero
  `subtype: "success"` y codigo 0. Solo `is_error` es fiable.
- Windows no trae base de zonas horarias: dependencia `tzdata`.
- Credential Manager limita secretos a ~1200 caracteres: tokens OAuth se trocean.
- Un modulo cargado con `importlib` debe registrarse en `sys.modules` antes de
  ejecutarse, o `@dataclass` falla.
- `--bare` de Claude Code **no** usa la suscripcion (solo API key).
- `test_perf.py` mide escrituras a SQLite: si falla, medir primero la latencia de un
  commit en crudo antes de sospechar del codigo (o de relajar el umbral).
- Los modelos pequenos mandan `""` o `null` en argumentos opcionales: el motor de
  la agencia los descarta antes de validar. No "arreglarlo" en cada herramienta.
- Thunderbird guarda el correo en mbox; `mailbox` de la libreria estandar tarda 15 s
  en un buzon de 5.000 mensajes. Por eso el indice propio cuenta separadores y lee
  las cabeceras del mismo bloque que ya tiene en memoria.
- RFC 5545: `COUNT` cuenta la ocurrencia aunque un `EXDATE` la excluya, y una
  repeticion mensual desde un dia 31 SALTA los meses cortos (no se corre al 28).
- En Git Bash, `/tmp` y el `C:\tmp` que ve Python NO son la misma carpeta: una
  prueba manual con rutas temporales puede leer una base vacia y parecer un bug.
- Un `Message-ID` largo sin espacios no cabe en 78 caracteres y `email` lo codifica
  en `=?utf-8?q?...`, con lo que el cliente pierde el hilo. Los borradores usan el
  limite real del estandar (998).
- Gmail marca todo como leido al leerlo en la web: no sirve filtrar por "no leidos";
  el resumen va por fechas.
- La suscripcion de Claude que usan los agentes remotos es la MISMA que usa Claude
  Code: medir con ella gasta la cuota de la sesion de trabajo. Preguntar antes.
- `.gitignore`: anclar a la raiz (`/memoria/`). `memoria/` a secas ignoraba tambien
  el codigo fuente `src/lymi/memoria/`.
- qwen2.5:3b sigue el protocolo de acciones pero no es confiable redactando lo que
  leyo (inventa rutas y lineas). No ajustar prompts para que una demo salga bien:
  medir y documentar.
- Bash del harness: un heredoc largo con comillas escapadas puede romperse al
  interpretarse. Para scripts de edicion, escribir un .py en el scratchpad.
- El indice de codigo guarda su `VERSION` de extractor: si cambia lo que se extrae,
  subirla, o los archivos sin cambios conservan datos viejos.

## Mapa del codigo

```
src/lymi/
  ledger/      contabilidad de tokens, tarifas, egress por hash
  providers/   anthropic_client, claude_code (suscripcion), local (Ollama), fake
  bench/       tareas con puertas, estrategias, runner, recibo, wiring de proveedores
  flows/       workflows YAML: schema, template, condition, nodes (incluye el
               supervisor MCP), engine, plan, aprobaciones, catalogo (manifiestos
               de Hermes), oauth (navegador), oauth_dispositivo (RFC 8628)
  triggers/    cron, agenda, webhook, ganchos, politica desatendida, servidor
  ejecutor/    la unica puerta al PC: capacidades por ruta y comando, operaciones
               cerradas, diario de deshacer (`lymi undo`). Nunca hay shell
  agencia/     departamentos de agentes: definicion (YAML + roles .md), protocolo
               (una accion JSON por turno), motor (delegacion, ayudantes, topes,
               parada), enrutador. Las herramientas son pasos de workflow
  calendario/  archivos .ics locales: eventos y repeticiones, sin conexiones
  correo/      buzon local de Thunderbird (mbox) de solo lectura y resumen anotado
  memoria/     afirmaciones de agentes y hechos promovidos por personas, en markdown
  codigo/      mapa del codigo (extraer con `ast`, indice SQLite fresco, formato
               compacto, servidor MCP). `lymi codigo servir` para otros agentes
  web/         lectura de la web hecha por lymi: red (guardia SSRF + robots),
               markdown (HTML limpio), buscar (SearXNG), investigar (pasajes por
               BM25 y citas verificadas contra la fuente)
  privacidad/  unicode (saneamiento), redaccion (reversible, bloqueo), etiquetas
               (sensibilidad por ruta). La pasarela que los aplica es
               `bench/runner.Recorder.preparar`: toda llamada a un modelo pasa por ahi
  control.py   parada por archivo (`lymi stop|resume`) y presupuestos
  doctor.py    diagnostico de proveedores (`lymi setup`)
  cli*.py      comandos
  ui/          `lymi ui`: app Starlette local (host + token + CSP), trabajos en
               segundo plano con aprobaciones desde el navegador, tema;
               static/ = index.html, app.js (sin dependencias), app.css, riso.css
               (generado por design/estilos/sincronizar.mjs)
tests/         pruebas; tests/servidores/eco_mcp.py = servidor MCP real
workflows/     ejemplos
design/        maquetas (*.dc.html) y sitio; estilos en design/estilos/ (riso.css +
               pantallas/*.css), copiados a cada artboard por sincronizar.mjs
docs/          CONTEXTO, PENDIENTES, BITACORA, ARQUITECTURA_AGENTE_SEGURO,
               METHODOLOGY, ROADMAP, PARIDAD_HERMES, REFERENCIAS
```
