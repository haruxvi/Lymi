# Bitacora

Registro cronologico, solo se agrega al final. Cada entrada empieza con
`## [AAAA-MM-DD] tipo | titulo` para poder filtrarla con `grep "^## \[" BITACORA.md`.

## [2026-09-08] inicio | Discusion de la idea y fase 0

- Tesis definida: ahorro falsable por curva de escalamiento, no por porcentaje.
- Ledger con tarificacion, hash de payload, separacion api/suscripcion/local.
- Guarda de loopback del tier local. 35 pruebas.

## [2026-09-08] diseno | App de escritorio y temas

- Canvas de 7 pantallas (App, Apariencia, Conocimiento). Editor de temas sobre
  `theme.toml`, vista "riced", mapa de costos.

## [2026-09-10] codigo | Banco de pruebas y recibo

- Puertas: Snake ejecuta el codigo generado; investigacion por rubrica; repo.
- Estrategias linea base y lymi; recibo terminal + tarjeta HTML con sello demo.
- Bugs hallados corriendo: arnes sin `sys.modules`, consola cp1252.

## [2026-09-11] codigo | Proveedores reales y suscripcion

- `lymi setup`. Suscripcion via `claude -p` con herramientas apagadas.
- Sonda real: `is_error` vs `subtype`; sesion OAuth del usuario caducada.

## [2026-09-12] diseno | Cuatro intentos y direccion elegida

- Rechazados: panel gris, carta de vinos (serif), terminal pura, scroll cinematico.
- Elegido: risografia (punto medio otaku + fanzine). Aun no aplicada.

## [2026-09-12] codigo | Workflows, MCP, OAuth, disparadores

- Motor de workflows YAML con plantillas y condiciones seguras, plan, CLI.
- MCP stdio y HTTP probados contra servidor real; OAuth con keyring troceado;
  importador del catalogo de Hermes.
- Cron, agenda, webhooks firmados, `lymi serve`. 292 pruebas.
- Decision: paridad total con Hermes (`PARIDAD_HERMES.md`, 98 capacidades).

## [2026-09-13] docs | Memoria persistente

- `CLAUDE.md`, `CONTEXTO.md`, `PENDIENTES.md`, `ARQUITECTURA_AGENTE_SEGURO.md`,
  esta bitacora, y wiki en el vault de Obsidian.
- Detectado: el repositorio git no tiene ningun commit.

## [2026-09-13] investigacion | 12 repositorios de referencia

- Veredicto en `REFERENCIAS.md`. Palancas de ahorro en `PENDIENTES.md` 4b.
- Alertas: mcp-server-chart envia datos a Alipay por defecto; Everywhere es BSL;
  dify es Apache modificada.
- obsidian-skills instalado en el vault del usuario (`.claude/skills/`).
- Reglas de superpowers adoptadas en `CLAUDE.md` (12-14).

## [2026-09-13] codigo | Cierre de oleada 1

- Supervisor MCP (reinicio y degradacion). Causa raiz de un fallo: el error se
  entregaba antes de decidir si la sesion seguia viva; ahora se decide primero.
- OAuth por codigo de dispositivo (el SDK de MCP no lo trae).
- Aprobaciones ampliadas: reglas, memoria con vencimiento, vencimiento de la
  pregunta. Una regla que rechaza gana siempre, incluso con `--yes`.
- 342 pruebas verdes, ruff limpio.

## [2026-09-13] diseno | Sitio en risografia

- `design/sitio-lymi.html` reescrito y publicado, con seccion nueva sobre los
  tres riesgos de los agentes con control del PC.

## [2026-09-13] legal | Auditoria para publicar el repo

- Faltaba `LICENSE`: agregado el texto estandar de Apache-2.0 (coincide con
  `pyproject.toml`).
- Dependencias instaladas revisadas: todas MIT/BSD/Apache/ISC/PSF; certifi es
  MPL-2.0 pero no se vendoriza. Compatibles con Apache-2.0.
- Sin secretos en archivos versionables. Sin codigo de terceros copiado.
- Los bundles del canvas traen runtime de terceros (React y la herramienta de
  diseno): pasan a `.gitignore`; los `.dc.html` fuente son originales.
- THIRD_PARTY_NOTICES amplia fuentes (OFL), paletas y marcas.

## [2026-09-13] diseno | 7 pantallas en risografia

- Main, Session, Workflow, Egress, Grafo, Temas (interactivo) y Riced
  reescritas; canvas republicado en la misma URL.
- Regla: textura, sellos, cinta y rotaciones solo en marca y acentos; tablas,
  formularios y cifras rectos.
- Workflow rehecho como lienzo de nodos (n8n) a pedido del usuario: paleta,
  cuadricula, cables con rama si/no, inspector del nodo. Se conservan los extras
  propios: tier por nodo, color del cable segun destino, costo medido y egress
  del nodo, plan sin gastar tokens, YAML como fuente de verdad.

## [2026-09-13] bug | Primera medicion real: tres defectos del tier local

- `lymi setup` mandaba a reinstalar Ollama estando instalado: la terminal tenia
  el PATH viejo. Causa raiz: el doctor decidia por el binario, no por el
  servidor. Ahora consulta siempre el servidor y busca el binario en las rutas
  de instalacion.
- `lymi bench snake` murio con `ReadTimeout` y una traza. Causa raiz: timeout
  sobre la respuesta completa (300 s) con un modelo a 13 tok/s y 4096 tokens
  pedidos. Ahora se lee en streaming y el limite mide silencio (120 s); el
  silencio se reporta en una frase.
- `qwen3:4b` no sirve para el tier local en 4 GB de VRAM: 33/67 CPU/GPU,
  razona 700 tokens y no responde un resumen de una frase en 64 s; ni
  `think: false` ni `/no_think` lo detienen en Ollama 0.34. `qwen2.5:3b`: 100%
  GPU, 0.4 s, 20 tokens. Nuevo modelo por defecto.
- 351 pruebas verdes.

## [2026-09-13] bug | El primer recibo real mentia por omision

Contrastado contra las filas del ledger de las corridas `1f85e5ee2e1c` y
`6c71c5bdd006`:

- **Suscripcion registrada como api.** `_facturacion` decidia por
  `total_cost_usd > 0`, pero el CLI reporta ese costo equivalente tambien con
  sesion pro (0.0559 USD por un "di: ok", sin clave). Ahora decide el entorno:
  con `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN` es api; sin clave, suscripcion.
  Las estrategias heredan el modo del cliente en vez de fijar `api` a mano.
- **Consumo remoto sin cache.** `remote_tokens` sumaba input + output: el recibo
  decia 3.1k contra 2.9k cuando el proveedor proceso 44.9k contra 27.2k. El
  prefijo del harness de Claude Code son ~28-42k tokens por llamada. La vista
  suma ahora la cache y expone `remote_cache_tokens`.
- **Costo parcial presentado como total.** `SUM(cost_usd)` ignoraba los NULL y
  mostraba `$0.0000`. Ahora un solo costo desconocido deja el total en NULL.
- **Ahorro inflado por orden de ejecucion.** La linea base corre primero y deja
  su prefijo en cache (TTL 1 h); lymi leyo 11.9k de esa cache. El recibo ya no
  anuncia ahorro si lymi leyo mas cache que la linea base.
- **Modelo guardado como alias** (`opus`), sin tarifa. Ahora se toma el id real
  de `modelUsage`, y `price_for` acepta el sufijo de fecha.
- "0 salieron de tu maquina" era falso para la corrida: habia 1 llamada con
  egress. El recibo lo declara.
- La vista se recrea al abrir el ledger para que bases viejas no sigan con la
  formula anterior. 370 pruebas verdes.
- **Linea base de paja por la puerta.** La base reprobo dos veces con el mismo
  `FrozenInstanceError: cannot assign to field 'comida'`: la puerta asignaba
  `estado.comida` a mano, exigiendo un estado mutable que el enunciado no pide
  (y que "devuelve el estado nuevo" desaconseja). Ahora coloca la comida con
  `dataclasses.replace`/`_replace`/`model_copy` si hace falta. Pruebas nuevas:
  mutable, congelado y namedtuple pasan; soluciones rotas siguen reprobando.
  378 pruebas verdes. Verificado en real despues del arreglo de contabilidad:
  45.6k vs 28.4k tokens remotos, suscripcion y `claude-opus-5` bien registrados;
  sin re-medir aun con la puerta corregida.

## [2026-09-13] medicion | Tercera corrida real: la puerta ya es justa

- Corrida del usuario `e7722a8976cd` vs `9ff65fe0af35`: ambas puertas pasaron
  (el arreglo de la puerta funciono). 39.5k vs 21.7k tokens remotos.
- Sin ahorro anunciable: lymi leyo 3.4k tok de cache que calento la linea base.
  La guarda hizo su trabajo. Siguiente paso: calentar la cache antes de ambas
  corridas o alternar el orden (ver PENDIENTES 1).
- El usuario creyo que el bench estaba colgado: 3 minutos sin salida. Ahora
  imprime `[1/2]`/`[2/2]` y el veredicto de cada puerta.

## [2026-09-13] diseno | CSS separado del HTML

- 188 errores del linter de CSS en VS Code: todos por `{{ }}` dentro de
  `style=""`. Los valores dinamicos pasaron a clases (`tier-local`, `activo`...)
  o a atributos SVG; los nodos del workflow viven en `<foreignObject>` para que
  su posicion salga de los mismos numeros que dibujan los cables.
- Fuente de verdad: `design/estilos/riso.css` (tokens y componentes) +
  `design/estilos/pantallas/<pantalla>.css`. El canvas no carga hojas externas,
  asi que `node design/estilos/sincronizar.mjs` las copia en el
  `<style data-estilos>` de cada artboard; `--check` falla si quedan
  desincronizadas o si reaparece un `{{ }}` en `style=""`.
- Riced demuestra el motor de temas: mismos componentes, solo redefine tokens.
- Revision visual en navegador (vistas enfocadas por artboard): Main, Session,
  Egress, Temas y Riced bien a la primera. Corregido: en Workflow los ultimos
  nodos quedaban sobre el inspector (el lienzo mide ~750 px, no 900: ahora
  escala con `viewBox`), los disparadores y el ledger se partian en lineas; en
  Grafo el titulo se partia. Regla nueva en riso.css: sellos, pastillas,
  etiquetas y ledger nunca parten linea.

## [2026-09-14] legal | Preparacion para el primer commit publico

- Auditoria final sobre los 116 archivos versionables: sin secretos, sin datos
  personales, sin afirmaciones sin fuente sobre terceros. Lock solo de PyPI.
- Datos del desarrollador (rutas, maquina, cuentas) movidos a `CLAUDE.local.md`,
  ignorado por git.
- Menciones a un producto concreto como "lo que rompe" pasaron a "riesgos de los
  agentes con control del PC"; la descripcion de JARVIS quedo neutral.
- Corregido en CONTEXTO un dato ya refutado (`total_cost_usd` no delata clave).
- Repo profesional: CI (Windows: ruff, pytest, estilos), Dependabot, SECURITY,
  CONTRIBUTING, plantilla de PR, `.gitattributes`, README con estado real.
- 378 pruebas verdes, `uv lock --check` ok.

## [2026-09-14] codigo | App navegable y calentamiento de cache

- `lymi bench` calienta la cache del proveedor antes de medir (`calentar_cache`,
  corrida aparte `calentamiento`), para que la linea base no le regale cache a
  lymi. `--sin-calentar` lo apaga.
- `lymi ui`: app local sobre datos reales, en `src/lymi/ui/`. Starlette con
  guardia propia: host exacto (DNS rebinding), token por proceso en toda la API,
  Origin ajeno rechazado, CSP sin inline, sin internet. Bench y workflows corren
  como trabajos en hilos; los efectos piden aprobacion en el navegador con
  vencimiento (vencer = rechazar) y "siempre para este destino".
- Frontend sin dependencias: ningun dato entra como HTML (todo por nodos de
  texto) y los estilos dinamicos van por CSSOM. `riso.css` de la app lo genera
  `sincronizar.mjs` desde la misma fuente que las maquetas.
- Revisada en el navegador contra el ledger real (14 corridas): corregidos el
  texto pegado en las opciones de Medir y los cortes a mitad de palabra en tablas.
- 412 pruebas verdes (34 nuevas), ruff limpio.

## [2026-09-14] codigo | Pasarela de egress, parada y presupuestos

- Medicion real con calentamiento: la linea base paso; la suscripcion llego a su
  limite de sesion a mitad de lymi y cayo con una traza. Nuevo
  `ClaudeCodeLimiteError`: el bench lo explica en una linea.
- Pasarela en `Recorder.preparar`, usada por el bench y por los pasos LLM de
  workflows: parada -> presupuesto -> saneamiento Unicode -> contenido
  `nunca-sale` -> redaccion reversible (solo si sale). La respuesta se rehidrata.
  El egress registrado es el texto redactado: lo que de verdad salio. Nueva
  columna `redacciones` (migracion automatica de bases viejas).
- Lo que corta la pasarela no se reintenta en workflows.
- Etiquetas de sensibilidad por ruta con piso fijo (.env, llaves, .ssh, bovedas).
  `flow run -i x=@archivo` protege el literal `nunca-sale`; el modelo local si lo lee.
- `lymi stop|resume` (archivo de parada, visible para todo proceso) y boton en la
  app que revoca aprobaciones pendientes. `flow run --max-tokens-remotos --max-llamadas`.
- `lymi flow approvals list|forget`.
- Leccion: la herramienta de escritura convirtio escapes `‮` en caracteres
  invisibles literales dentro del codigo (Trojan Source). Ruff lo detecto
  (PLE2502/PLE2515); se reemplazaron por escapes con un script sin barras.
- Repos evaluados: OpenSandbox (Apache 2.0, candidato a sandbox via MCP; idea de
  inyectar credenciales en la salida), claude-unlimited (MIT, nucleo descartado:
  rota cuentas para esquivar limites de uso). dify ya estaba evaluado.
- 480 pruebas verdes, ruff limpio.

## [2026-09-15] codigo | Ejecutor del host y capa web propia

Dos bloques que cierran el fallo 1 y abren la lectura de internet sin depender de
nadie. Decision del usuario: **no integrar** Firecrawl, Playwright ni Perplexity
como servicios; tomar lo que hacen bien y construirlo dentro de lymi.

**Ejecutor del host** (`src/lymi/ejecutor/`, paso `pc`, `lymi undo`)

- Seis operaciones cerradas. Nunca un shell: interpretes y `.bat`/`.cmd`
  rechazados, `shell=False`, sin stdin, entorno minimo (probado: una variable
  secreta del entorno de lymi no llega al proceso hijo).
- Tres capas de capacidades: zonas vetadas fijas (sistema, credenciales, `runs/`,
  `.git`), forma de la ruta (UNC, `archivo:flujo`, `CON`/`NUL`) y perfil
  (`ejecutor.yml`; por defecto solo `./salidas` y ningun comando).
- Diario: copia antes de tocar, borrar = mover al diario, `lymi undo <corrida>`
  revierte en orden inverso y una sola vez.
- Leer un archivo etiquetado `nunca-sale` (ej. `.env`) protege su texto para el
  resto de la corrida: el paso siguiente que quiera mandarlo a un modelo remoto
  falla. Probado de punta a punta.

**Capa web** (`src/lymi/web/`, paso `web`, `lymi web leer|mapear|buscar|investigar`)

- HTML a markdown con la libreria estandar: se queda con `main`/`article` y tira
  menus, pies, scripts y **lo que el navegador no muestra** (`hidden`,
  `aria-hidden`, `display:none`, letra de tamano cero), que es la via barata de
  inyeccion de instrucciones.
- Guardia SSRF real: se resuelve el nombre, se exige que TODAS sus direcciones
  sean publicas y se conecta a la IP comprobada con el nombre en `Host` y en SNI
  (el certificado se sigue validando). Las redirecciones se repiten igual. Una IP
  literal se juzga sin pasar por el DNS.
- La URL y la consulta son egress: el Redactor las revisa y un correo, una clave
  o una tarjeta en la URL bloquean la peticion. Cada salto queda en el ledger
  (`provider = web`), incluido el robots.txt.
- `investigar`: pasajes elegidos en local con BM25 y **citas verificadas** contra
  la fuente. Primera corrida real (qwen2.5:3b sobre la RFC 2606): el modelo cito
  una fuente `[4]` que no existia y dejo una oracion sin respaldo; la verificacion
  lo dijo. Eso es exactamente lo que tiene que pasar.
- Se acepta cualquier tipo de comilla en las citas: un modelo pequeno cambia el
  simbolo y una cita real no puede quedar sin verificar por tipografia.

Ejemplos nuevos: `workflows/investigar-y-archivar.yml`, `workflows/resumen-de-pagina.yml`,
`ejecutor.example.yml`.

559 pruebas verdes, ruff limpio.

## [2026-09-19] codigo | Mapa del codigo: menos lectura a ciegas, medido

Cinco repos evaluados (ver REFERENCIAS). El que aporta ahorro demostrable es la
idea compartida por Graft y codebase-memory-mcp: que un agente no re-explore el
repositorio en cada tarea. Implementacion propia en `src/lymi/codigo/`.

- `ast` de la libreria estandar para Python (exacto, sin ejecutar nada); JS/TS,
  Go y Rust por patrones, marcados como aproximados en cada respuesta.
- Indice SQLite fresco antes de cada consulta: en lymi, 104 archivos en 1 s la
  primera vez y 0,1 s cuando nada cambio. Version de extractor: si cambia, se rehace.
- Consultas: `buscar`, `esqueleto`, `fragmento`, `llamadores`, `impacto`, `mapa`.
  Por terminal (`lymi codigo`), en workflows (paso `codigo`, raiz juzgada por el
  perfil del ejecutor) y por MCP (`lymi codigo servir`, probado de punta a punta
  con el cliente MCP de lymi contra el proceso real).
- **Defecto encontrado al usarlo**: el impacto arrastraba homonimos (`Agenda.obtener`
  aparecia como afectado por un cambio en `Web.obtener`). Ahora una llamada solo
  se confirma si el archivo importa el modulo que define el simbolo (con un salto a
  traves del `__init__` del paquete); el resto se informa como "posibles homonimos",
  sin esconderlo. El impacto de `revisar_saliente` paso de seis archivos de prueba
  a uno, el correcto.
- Medido sobre las 66 fuentes de lymi: esqueletos 82% menos bytes que los archivos;
  un `fragmento`, 95% menos que el archivo que contiene la funcion (564 funciones).
  Son bytes de contexto. Si un agente acierta igual con menos contexto se mide
  despues en el bench, con puerta de correccion.
- `test_perf.py::test_registro_de_llamadas_es_despreciable` falla: 2,3 ms por
  registro contra 1 ms. Causa medida: el disco. Un commit de SQLite en crudo tarda
  10 ms por fila en esta maquina hoy; el ledger no cambio. No se relajo el umbral.

583 pruebas verdes (1 de rendimiento falla por el disco), ruff limpio.

## [2026-09-19] codigo | Agencia: departamentos que delegan, en paralelo y con ayudantes

Pedido del usuario: departamentos con flujo de agentes, tareas derivadas y agentes
que crean otros, sincronico y asincronico. FounderOS aporto la forma (departamentos,
conductor, rol como archivo), pero no tenia delegacion: es diseno de lymi.

- Un agente es un bucle: el modelo propone UNA accion JSON (usar, delegar, crear,
  esperar, enviar, terminar) y lymi la valida y la ejecuta. Uniforme para el modelo
  local y el remoto, sin depender del "tool calling" de cada proveedor.
- Las herramientas SON pasos de workflow: heredan pasarela, ledger, perfil del
  ejecutor y aprobaciones sin codigo nuevo. Y un workflow puede entregarle una
  tarea a un departamento (paso `agencia`): los dos se enriquecen.
- Seguridad: topes compartidos por el arbol (profundidad, agentes, simultaneos,
  turnos, llamadas, tokens, tiempo); delegacion solo por aristas declaradas; un
  ayudante tiene un subconjunto de las herramientas de su creador y no delega ni
  crea; esperar no ocupa cupo y solo se esperan hijas (sin bloqueos mutuos); la
  parada, un tope o una falla cancelan a los descendientes.
- Dos defectos hallados por las pruebas: (1) `esperar` sin lista solo recogia las
  hijas aun en curso, y el resultado de una hija rapida se perdia; ahora se
  entrega todo resultado no recibido. (2) Una accion decidida despues de `lymi stop`
  alcanzaba a ejecutarse; ahora se verifica la parada antes de actuar.
- Corrida real con qwen2.5:3b sobre el codigo de lymi: el motor funciono (protocolo,
  herramientas, 0 tokens remotos). Destapo un tercer defecto: el modelo manda
  `"raiz": ""`; ahora un argumento vacio cuenta como no enviado. Pero el modelo no
  es confiable: una vez acerto la ubicacion y nego llamadores que existen; otra vez
  invento `buscar.py:39`. Conclusion documentada, no maquillada: el local de 3B
  sirve para enrutar y destilar; razonar varios pasos pide el remoto, y hace falta
  verificar cada `ruta:linea` que afirme un agente.

611 pruebas verdes y 1 omitida; la de rendimiento del disco sigue fallando. Ruff limpio.

## [2026-09-19] medicion | Que modelo sirve como agente, medido; memoria entre sesiones

Pregunta del usuario: si qwen falla tanto, ¿conviene la suscripcion de Claude?

- `lymi agencia evaluar`: preguntas del codigo de lymi (donde se define X y quien la
  llama) corregidas contra el indice. Sin juez: cita exacta, llamador real y ninguna
  cita sin respaldo.
- qwen2.5:3b: 3/10, 7 s por pregunta, 3k tokens locales. Tras la verificacion de
  procedencia, 0/10 citas inventadas: el mecanismo funciona; el razonamiento no.
- qwen3:4b: 1/2 y ~9 minutos por pregunta. Causa medida con `ollama ps`: 3,5 GB con
  contexto, 33% en CPU porque el escritorio ocupa ~2 GB de los 4 GB de VRAM.
  `lymi setup` ahora lo avisa (`gpu local`).
- Remoto: no se pudo medir; la suscripcion estaba en su limite de sesion (la misma
  que usa Claude Code). lymi lo reporto en una linea, sin gastar tokens.
- Tolerancia del protocolo a dos errores inequivocos de modelos pequenos (herramienta
  como accion; terminar sin `resultado`), sin relajar permisos ni verificacion.
- Procedencia de citas en la agencia: solo se cita lo visto; el aviso de lymi no
  cuenta como visto (defecto encontrado y cerrado antes de publicarlo).
- Modelo por agente y respaldo remoto -> local visible.
- Memoria (fallo 2): afirmaciones de agentes SIN REVISAR, hechos promovidos por una
  persona, notas propias del vault, sin secretos, BM25 con `ruta:linea`.
- Defecto de `.gitignore` corregido: `memoria/` ignoraba `src/lymi/memoria/`.

651 pruebas verdes y 1 omitida; la de rendimiento del disco sigue fallando. Ruff limpio.

## [2026-09-19] codigo | Correo local: leer sin credenciales y resumir sin inventar

Decision con el usuario: nada de construir un gestor de correo ni de manejar su
navegador con la sesion abierta. Thunderbird resuelve OAuth, cuentas y carpetas;
lymi solo lee los archivos que deja en disco.

- `src/lymi/correo/`: indice propio sobre mbox. La libreria estandar tarda 15 s en
  un buzon de 5.238 mensajes; contar separadores y leer las cabeceras del bloque ya
  cargado baja a ~8 s la primera vez y a 0,1 s despues (solo se relee la cola).
- El indice guarda posiciones, fechas y banderas. Nunca asuntos, remitentes ni
  cuerpos: el correo vive en un solo lugar. Hay una prueba que lo verifica.
- Nunca se escribe: ni en los mbox ni en los `.msf`. Tambien con prueba.
- El resumen reparte el trabajo al reves de lo habitual: los datos los pone lymi
  desde el archivo y el modelo solo anota prioridad y accion por numero. No puede
  inventar un remitente ni un asunto, y si contesta cualquier cosa el resumen sale
  igual, diciendolo.
- Clasificacion sin modelo: cabeceras de lista, subdominios de envio masivo
  (`hello@news.railway.app` no traia `List-Unsubscribe`) y buzones `noreply@`.
  Ademas, si tu direccion no esta en Para/CC, la prioridad no puede ser alta,
  diga lo que diga el modelo.
- Hallazgos del correo real: los 5.238 mensajes estan marcados como leidos (Gmail
  los marca en la web), asi que el resumen va por fechas, no por "no leidos". Y
  un mensaje pesaba 12 MB por un PDF: se lee con tope y sin cargar adjuntos.
- Primera corrida real: qwen2.5:3b marco un boletin como "atiende primero". Tras
  agregar las senales deterministas, los 8 correos de esos dias se clasificaron
  solos y el resumen costo 0 tokens: el modelo ni siquiera hizo falta.

674 pruebas verdes y 1 omitida; la de rendimiento del disco sigue fallando. Ruff limpio.

## [2026-09-19] codigo | Borradores de respuesta, sin forma de enviarlos

- `lymi correo borrador <id>`: el modelo escribe SOLO el cuerpo; a quien, el asunto
  y el hilo los arma lymi desde el correo original. Un modelo distraido no puede
  cambiar el destinatario.
- El borrador queda como `.eml` escrito por el ejecutor (aprobacion y `lymi undo`).
  lymi no envia correo: no hay SMTP en el paquete y hay una prueba que recorre las
  fuentes para comprobarlo.
- Defecto encontrado con correo real: el `Message-ID` de GitHub mide 86 caracteres
  sin espacios; `email` no lo puede plegar en 78 y lo codifica como `=?utf-8?q?...`,
  con lo que el cliente pierde el hilo. Los borradores se escriben con el limite
  real del estandar (998) y hay prueba de regresion.
- Presentacion del resumen: `1 mensaje` en singular y el remitente con su dominio
  (`Vicente (github.com)`), que se veia como si el usuario se escribiera a si mismo.
- El resumen diario no necesito codigo nuevo: `lymi schedule add` ya programa el
  workflow y preaprueba el paso que escribe. Probado en una agenda temporal.

679 pruebas verdes y 1 omitida; la de rendimiento del disco sigue fallando. Ruff limpio.

## [2026-09-19] medicion | La cadena proactiva funciona, verificada

El usuario programo el resumen diario. En vez de confiar, se probo: misma
programacion cada minuto en una agenda temporal y `lymi serve` durante 90 s.

- Resultado: la agenda disparo sola, el workflow corrio sin nadie delante, escribio
  `salidas/correo-hoy.md` y la corrida quedo en el ledger como
  `resumen_de_correo / agenda:<id> / passed / 2 pasos ok`.
- Susto: el ledger que consulte aparecia vacio. No era lymi: en Git Bash `/tmp` y el
  `C:\tmp` que ve Python son carpetas distintas, y estaba leyendo otra base. Anotado
  en las trampas de CLAUDE.md.
- Resumen agrupado por hilo (`Message-ID`/`References`): un ida y vuelta ocupa una
  linea. Un correo sin `Message-ID` se deja aparte en vez de adivinar por asunto.
- Plurales del informe: "1 mensaje", "1 boletin".

681 pruebas verdes y 1 omitida; la de rendimiento del disco sigue fallando. Ruff limpio.

### Hilos abiertos al cierre

- Bloqueante del usuario: primer commit (configurar correo noreply antes).
- Navegador propio (CDP sobre el Edge/Chrome instalado, perfil aislado) para lo
  que no se puede leer con HTTP.
- Probar `lymi web buscar` contra un SearXNG real.
- Pasos `foreach` en workflows.
- Medir el mapa de codigo en el bench (tarea `repo`) con puerta de correccion.
- Verificar las `ruta:linea` que afirme un agente contra el indice de codigo.
- Agencia en la app y con modelo remoto medido.
- Correo: aviso al celular del resumen y calendario.
- Que `lymi serve` arranque con Windows para que la agenda dispare sin recordarlo.
- Revisar la latencia del disco antes de volver a correr `test_perf.py`.
- Repetir `lymi bench snake` real con calentamiento cuando la suscripcion se restablezca.
- Primera medicion real.
- Editor de temas funcional sobre `theme.toml`.
