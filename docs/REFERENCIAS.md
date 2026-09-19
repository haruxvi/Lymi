# Repositorios de referencia: que tomar de cada uno

Auditoria del 2026-09-13 sobre los repositorios clonados: licencia leida del
archivo, estructura y el codigo de los mecanismos relevantes. Criterio del
usuario: tomar lo que ayude al **ahorro de tokens** y, en general, lo que sirva.

Regla de licencias: MIT/BSD/Apache → se puede incorporar codigo con atribucion.
Apache modificada, BSL o sin licencia → **solo ideas**, se escribe nuestra
implementacion.

## Resumen

| Repo | Licencia | Que es | Veredicto |
|---|---|---|---|
| free-claude-code | MIT | Proxy multi-proveedor para 10 agentes de codigo | **Tomar**: respuestas locales a llamadas auxiliares, fallback entre modelos, integracion RTK |
| claude-mem | Apache 2.0 (NOTICE) | Memoria persistente para Claude Code (activa en esta sesion) | **Tomar**: compuerta de inyeccion por archivo y epoca, divulgacion progresiva |
| dsh-mneme | MIT | Memoria entre sesiones para DeepSeek Harness | **Tomar**: recibos de decision reproducibles, calor con decaimiento por tipo, espejo markdown con prioridad humana |
| memanto | MIT | Agente de memoria: consolida, reconcilia, olvida, informa | **Tomar**: expiracion con motivo, supersesion en vez de sobrescritura, "briefing" minimo |
| zettelforge | MIT | Memoria agentica para inteligencia de amenazas | **Tomar**: defensa contra envenenamiento de memoria, accion PII log/redact/block |
| memU | Apache 2.0 | Memoria personal como wiki, nucleo de ~500 lineas | **Tomar**: destilar skills del historial; programacion en Windows |
| zvec | Apache 2.0 | Base vectorial embebida (C++), busqueda hibrida | **Evaluar** como backend de recuperacion local sin servidor |
| superpowers | MIT | Metodologia de desarrollo como skills | **Adoptar** en las reglas: evidencia antes de afirmar, causa raiz antes de arreglar |
| obsidian-skills | MIT | Skills para Obsidian | **Instalado** en el vault; `defuddle` ahorra tokens en web |
| mcp-server-chart | MIT | 26 graficos via MCP | **Solo con servidor de render propio**: por defecto envia los datos a Alipay |
| dify | Apache 2.0 **modificada** | Plataforma de apps LLM con workflows visuales | **Solo ideas**: nodo `human_input` con vencimiento |
| Everywhere | **BSL 1.1** | Asistente que lee el contexto de pantalla | **Solo ideas**: leer arbol de accesibilidad en vez de capturas |
| OpenSandbox | Apache 2.0 | Plataforma de sandbox para agentes (Docker/Kubernetes, SDKs, MCP) | **Candidato** a runtime de sandbox via su MCP; **idea adoptada**: la credencial real la inyecta la salida, nunca la ve la carga de trabajo |
| claude-unlimited | MIT | Proxy que rota varias cuentas de Claude/ChatGPT cuando una llega al limite | **Nucleo descartado** (esquiva limites de uso por cuenta: choca con los terminos de los proveedores); ideas neutras: avisar antes de agotar cuota, atribucion por proyecto |

## Detalle por repositorio

### free-claude-code (MIT) — ahorro directo

`src/free_claude_code/api/detection.py` y `optimization_handlers.py` detectan
por la forma de la peticion llamadas auxiliares que el harness hace al modelo, y
las responden **localmente, sin llamar a ningun proveedor**:

- sondeos de cuota (`is_quota_check_request`),
- generacion de titulo de conversacion,
- deteccion del prefijo de un comando (`extract_command_prefix`),
- modo sugerencia,
- extraccion de rutas de archivo desde un comando.

Ademas: fallback automatico al siguiente modelo tras agotar reintentos, y RTK
(`rtk-ai/rtk`), filtro externo que dice recortar hasta 90% de tokens de salida de
terminal.

**Para lymi:** un interceptor de llamadas auxiliares en el gateway, con cada
respuesta local registrada en el ledger como tokens evitados (medible, no
estimado). Evaluar RTK como paso opcional sobre la salida de herramientas.

### claude-mem (Apache 2.0) — no reinyectar lo mismo

`src/cli/handlers/file-context-dedupe.ts`: tabla SQLite con clave
(sesion, archivo) y la **epoca** de la observacion ya inyectada. Una lectura
repetida de un archivo sin cambios no se vuelve a inyectar salvo que haya una
observacion mas nueva. Reclamar y registrar es una sola sentencia
(`INSERT ... ON CONFLICT ... WHERE ... RETURNING`), asi dos lecturas simultaneas
no pasan ambas. Divulgacion progresiva: primero un indice compacto, el detalle
solo bajo demanda.

**Para lymi:** compuerta de deduplicacion en el recuperador de contexto y en la
memoria. Mismo patron SQLite atomico.

### dsh-mneme (MIT, JavaScript) — memoria auditable

- `lib/dream/decisions.js`: las consolidaciones que propone el modelo se
  **validan** antes de aplicarse (acciones permitidas, tope de actualizaciones por
  corrida, cobertura minima, resolucion de ids por prefijo unico al estilo git) y
  dejan un **recibo**: instantanea de entrada + decisiones + hash del resultado,
  reproducible. Confianza epistemica: observado > inferido > subjetivo.
- `lib/heat.js`: "calor" con curva de olvido y decaimiento **por tipo**
  (preferencias y resumenes inmunes; decisiones medio; historial rapido).
- `lib/mirror.js`: espejo markdown bidireccional; distingue una edicion humana de
  una escritura de la maquina por hash, y **la edicion humana gana**.
- Contradicciones se congelan hasta que el usuario decide.

**Para lymi:** exactamente la filosofia del ledger aplicada a la memoria.
Recibos de decision, calor por tipo, espejo con prioridad humana hacia el vault.

### memanto (MIT) — ciclo de vida de la memoria

`memanto/app/core.py`: un recuerdo expira con `expired_at` y `expired_by`
(regla, "manual"...), y se restaura limpiando ambos. Supersesion en vez de
sobrescritura ("que es verdad ahora" y "que creiamos entonces" son preguntas
distintas). Antes de que un agente actue, recibe la porcion minima relevante.

### zettelforge (MIT) — defensa de la memoria

`config.default.yaml`, `governance`:

- `pii.action`: `log | redact | block` (via Microsoft Presidio).
- `memory_defense.mode`: `audit | block | quarantine`, deteccion de anomalias
  calibrada con notas de referencia, cuarentena en JSONL.
- Registro de auditoria en esquema OCSF; limites de tamano y tiempo de recuperacion.

**Para lymi:** la memoria persistente es un vector de inyeccion. Modo auditoria /
bloqueo / cuarentena en la escritura de recuerdos; accion PII en el gateway.

### memU (Apache 2.0)

Memoria como wiki compartido entre sesiones y agentes; destila skills reutilizables
del historial; adaptador de programacion para Windows
(`hosts/scheduling/windows.py`). Su modo por defecto usa un servicio en la nube
(`memu.so`): lymi solo toma el patron local.

### zvec (Apache 2.0)

Base vectorial en proceso, sin servidor: HNSW/DiskANN, busqueda hibrida (vectores
+ texto completo + filtros), WAL. Wheels de Python de 64 bits. Candidato para la
recuperacion local cuando el indice supere lo que resuelve SQLite FTS. Medir antes
de adoptar.

### superpowers (MIT)

14 skills de metodologia. Tres pasan a las reglas de desarrollo de lymi:

- **verification-before-completion:** ninguna afirmacion de "funciona" sin haber
  corrido la verificacion en ese momento.
- **systematic-debugging:** ninguna correccion sin causa raiz.
- **using-git-worktrees:** aislar trabajo, detectando antes si ya hay aislamiento.

### obsidian-skills (MIT) — instalado

Copiado al vault de Obsidian del usuario (`.claude/skills/`) con licencia y SHA de origen:
`defuddle` (web limpia a markdown, ahorra tokens), `obsidian-markdown`,
`obsidian-bases`, `json-canvas`, `obsidian-cli`, `knap`. Se cargan cuando Claude
Code se abre con el vault como directorio de trabajo.

### mcp-server-chart (MIT) — cuidado con el egress

`src/utils/env.ts`: si no se define `VIS_REQUEST_SERVER`, cada grafico se
renderiza en `https://antv-studio.alipay.com/api/gpt-vis`. **Los datos del grafico
salen de la maquina.** Utilizable solo con servidor de render propio, y la
integracion debe declararse con su egress visible.

### dify (Apache 2.0 modificada) — solo ideas

Prohibe operar multi-tenant y retirar su logo del frontend. Tipos de nodo que
validan el diseno de lymi: `trigger_schedule`, `trigger_webhook` y `human_input`,
formulario de intervencion humana con vencimiento. Idea para aprobaciones
ampliadas: una aprobacion pendiente **expira** y el workflow sigue un camino
definido.

### Everywhere (BSL 1.1) — solo ideas

Prohibe usos competidores. Idea clave para el Jarvis: leer el **arbol de
accesibilidad** del sistema (UI Automation en Windows, AX en macOS) y convertir
paginas web a markdown via accesibilidad, en vez de enviar capturas de pantalla.
Texto estructurado cuesta una fraccion de los tokens de una imagen.

### OpenSandbox (Apache 2.0) — candidato para el sandbox

Auditado el 2026-09-14 (commit 47ccb7a). Go en el nucleo, SDKs en Python, TS, Java,
Go y C#, servidor MCP con creacion de sandbox, comandos y archivos. Aislamiento
fuerte opcional (gVisor, Kata, Firecracker) y control de egress por sandbox.

- **Para lymi**: el pendiente "sandbox para codigo generado" puede usar su MCP en
  vez de construir un runtime. Requiere Docker: en una maquina de 16 GB compite
  con el modelo local, asi que va como opcion, no como dependencia.
- **Idea adoptada, "Credential Vault"**: la carga de trabajo recibe credenciales
  falsas y la salida inyecta la real al hacer la peticion. Es la misma regla que
  ya sigue lymi (`${VAR}` solo se expande en la URL de la pasarela, nunca llega al
  modelo) llevada a procesos ajenos. Aplica cuando exista el ejecutor del host.

### claude-unlimited (MIT) — nucleo descartado

Auditado el 2026-09-14 (commit d075fbe). Proxy local en `127.0.0.1:4317` que junta
varias suscripciones de Claude, ChatGPT/Codex y claves de API, y cambia de cuenta
cuando una llega a su limite, sin que la sesion lo note. Incluye traduccion de
Codex a la forma de la API de Anthropic.

- **Descartado**: rotar cuentas para seguir cuando una llega a su limite es
  esquivar los limites por cuenta, algo que los terminos de los proveedores no
  permiten. lymi no va a depender de eso ni a ofrecerlo.
- **Ideas neutras que si sirven**: avisar antes de agotar la cuota (lymi ya tiene el
  consumo por llamada en el ledger), atribucion de uso por proyecto, export/import
  cifrado de la configuracion.

### Firecrawl, Playwright y Perplexity — ideas, no dependencias

El usuario propuso integrarlos y luego preciso el criterio: **no enchufar las
plataformas, sino potenciar sus funcionalidades dentro de lymi**. Lo que se tomo
es la forma del producto, no su codigo:

- De un scraper tipo Firecrawl: "pagina a markdown limpio" y "mapa de un sitio"
  como operaciones de primera clase. Implementacion propia con `html.parser`
  (`web/markdown.py`), mas lo que ellos no hacen: descartar el texto oculto y
  avisar cuando la pagina intenta dar instrucciones a un modelo.
- De un buscador con respuesta tipo Perplexity: la respuesta con fuentes
  numeradas. Implementacion propia (`web/investigar.py`) con dos diferencias:
  los pasajes se eligen en local con BM25 (no se paga por mandar la pagina
  entera) y **cada cita textual se busca en su fuente**, asi una cita inventada
  queda marcada. La busqueda la hace el buscador del usuario (SearXNG local,
  AGPL, consumido por su API HTTP; no se distribuye ni se enlaza su codigo).
- De Playwright: la idea de manejar un navegador con acciones nombradas. Queda
  pendiente como driver CDP propio contra el navegador ya instalado, con perfil
  temporal aislado y lista blanca de dominios.

No se copio codigo de ninguno de los tres. Lo mismo vale para OpenClaw y Hermes
Agent: de ellos se toma **que** resuelven (actuar en el PC, automatizar), no
**como**; sus desventajas (shell abierto, sin diario de deshacer, sin cuenta del
egress) son justamente lo que lymi corrige.

## Evaluacion del 2026-09-19

Criterio del usuario: ideas funcionales, sin humo, demostrables. Las cinco
licencias son permisivas; no se copio codigo de ninguna.

### codebase-memory-mcp (MIT, C) — idea tomada: mapa estructural por MCP

Grafo de conocimiento del codigo con tree-sitter (162 lenguajes), 15 herramientas
MCP, analisis de impacto. Se tomo la forma: consultas estructurales servidas a un
agente por MCP e impacto transitivo de un cambio. No se tomo: el instalador que
escribe la configuracion de decenas de clientes (invasivo) ni el binario nativo.
Sus cifras ("120x menos tokens") no las verificamos; las nuestras se miden sobre
lymi y se publican con su metodo.

### Graft (MIT, TypeScript) — ideas tomadas: frescura, cache por hash, metodo de medicion

- Refrescar el indice antes de cada consulta comparando fecha y tamano, y no
  re-analizar lo que tiene el mismo hash: el indice nunca describe codigo viejo.
- Comandos esqueleto / llamadores / mapa como primera clase.
- **Su metodo de benchmark**: una puerta de correccion con palabras obligatorias,
  para que una respuesta rapida y equivocada no gane; costo con la cache contada.
  Queda como pendiente para la tarea `repo` del bench.
- No se tomo: los resumenes escritos por un modelo (gastan tokens; si llegan,
  medidos) ni la telemetria, aunque sea opcional: lymi no manda nada sin que se vea.

### agency-agents (MIT) — sin codigo que tomar; formato reutilizable

Coleccion de prompts de "personalidades" de agente en markdown con frontmatter.
Una personalidad larga se paga en tokens en cada llamada y el repo no mide si
mejora algo. Queda como pendiente solo el formato: importar un rol como `system`
de un paso, con su costo visible en `flow plan` y medido en el bench.

### colibri (Apache 2.0, C) — principio tomado; motor no aplicable

Motor de inferencia para modelos MoE enormes repartiendo VRAM, RAM y disco. Su
propia demo usa seis GPU de gama alta para 4 tokens/s: no aplica a una maquina
con 4 GB de VRAM. Se tomo su principio: "sin garantia de velocidad, garantia dura
de semantica: nunca cambiar la precision en silencio". Pendiente: registrar la
cuantizacion del modelo local en el ledger y el recibo.

### AIS-OS (MIT, kit de markdown) — confirma el rumbo; marcas registradas

Kit de carpetas y comandos para un "sistema operativo" personal con IA. Sus
marcos (Three Ms, Four Cs) son marcas registradas: no se usan sus nombres. Coincide
con decisiones ya tomadas en lymi: los workflows ganan a los agentes, interruptor
de parada, cadena de validacion, registro de decisiones. Su prueba de fuego
("observa un evento real mientras no estas y produce algo mejor que tu") es lo que
los disparadores de lymi ya permiten, con la diferencia de que aqui cada salida
queda en el ledger.

### FounderOS-DEMO (MIT, Next.js) — ideas tomadas; la delegacion no existia

Demo de un "sistema operativo" para un negocio de una persona: departamentos,
agentes con nombre, conductor, tablero de aprobaciones, memoria gobernada. Casi
todo es interfaz sobre datos sembrados; sus agentes son funciones `run()` sin
bucle, y **no hay agentes que deleguen ni creen otros**: eso lo diseno lymi.

Tomado (sin copiar codigo):
- Departamentos con lider y un organigrama declarado.
- Conductor: primero `@agente` explicito, si no lo elige un modelo, y nunca falla
  por un nombre desconocido. En lymi enruta el modelo local, gratis.
- El rol como archivo markdown que ES el prompt (que recibe, que entrega, reglas),
  con la regla "nunca afirmes una cifra que no te dieron".
- Estado honesto de cada conector (lymi ya lo hacia).

Pendiente, anotado en PENDIENTES:
- Memoria con promocion (fuente -> senal -> afirmacion -> hecho): los agentes
  escriben afirmaciones; solo lo revisado se vuelve hecho.
- Respaldo de modelo al agotarse la cuota, con una cadena **sin ciclos** (su propio
  codigo documenta una que oscilo entre dos modelos durante hora y media).
- Cola de aprobaciones por tipo (decision, borrador, compuerta) con plazo.
