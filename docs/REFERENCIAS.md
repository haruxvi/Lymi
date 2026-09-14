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
