# Paridad con Hermes

**Decision (2026-09-12):** lymi incorpora todas las funcionalidades de Hermes
Agent, conviviendo con el resto del ecosistema del proyecto, y cada una
**mejorada** segun las reglas de abajo. No es un clon: es la version que ademas
mide lo que gasta y audita lo que saca de la maquina.

Este documento es el seguimiento. Una fila solo pasa a **HECHO** con pruebas que
la ejerciten. Escrito pero sin probar contra un sistema real es **PARCIAL**.

Fuente: inventario de `NousResearch/hermes-agent` (MIT) sobre el repositorio
clonado. Es un censo de estructura: la logica interna no se ha leido.

## Que significa "mejorada"

Una funcionalidad no esta terminada en lymi hasta cumplir las reglas que le
apliquen. La columna **Reglas** de la matriz dice cuales.

| | Regla |
|---|---|
| **L** | Toda llamada a un modelo o integracion queda en el ledger, con tokens y costo. |
| **E** | Todo dato que sale de la maquina queda en el log de egress: destino y hash, nunca el contenido. |
| **P** | Minimo privilegio por defecto: solo lectura, efectos con aprobacion, efectos sin reintento. |
| **S** | Secretos solo en el entorno o en el almacen del sistema; nunca en prompts, YAML, logs ni vistas previas. |
| **X** | Ningun texto ajeno ejecuta codigo: plantillas de busqueda pura, condiciones con lista blanca. |
| **M** | Si promete ahorro o calidad, se mide contra una linea base publica. |

## Estado

**98 capacidades · 10 hechas · 16 parciales · 72 pendientes**

## Coexistencia con el ecosistema

lymi no reemplaza lo que ya funciona: habla sus formatos.

- **MCP en ambos sentidos:** cliente de cualquier servidor, y servidor para que
  otros agentes usen los workflows y el ledger de lymi.
- **Catalogo de Hermes:** sus 66 manifiestos se importan tal cual.
- **Esquemas de ECC:** skills, plugins, memoria y procedencia en su formato.
- **n8n:** se opera via su puente MCP en vez de competirle.
- **Obsidian y Logseq:** la memoria es markdown plano con wikilinks.
- **API compatible con OpenAI:** cualquier herramienta que hable OpenAI puede
  apuntar a lymi.
- **A2A:** otros agentes pueden delegarle trabajo.

## Matriz

### 1. Nucleo del agente

| Capacidad | En Hermes | lymi | Via | Reglas |
|---|---|---|---|---|
| Bucle de agente con herramientas | `agent/conversation_loop` | PENDIENTE | construir | L E P X M |
| Compresion de contexto | `agent/context_compressor`, `docs/micro-compaction` | PENDIENTE | construir con presupuesto duro | L M |
| Subagentes y delegacion | `tools/delegate`, `async_delegation`, `subagent_worktree` | PENDIENTE | construir | L P M |
| Mezcla de agentes (debate) | `moa_cmd`, `moa_config` | PENDIENTE | construir, opt-in y medido | L M |
| Objetivos y bucles autonomos | `goal_command`, `goals`, `loops` | PENDIENTE | construir | L P |
| Personalidad | `default_soul`, `personality`, `SOUL.md` | PENDIENTE | construir | |
| Checkpoints y deshacer | `checkpoint_manager`, `checkpoints` | PENDIENTE | construir | P |
| Preguntas de aclaracion | `tools/clarify` | PENDIENTE | construir | |
| Lista de tareas | `tools/todo` | PENDIENTE | construir | |
| Presupuesto por tarea | `tools/budget_config` | PARCIAL: el ledger mide, todavia no limita | construir | L M |

### 2. Proveedores de modelos

| Capacidad | En Hermes | lymi | Via | Reglas |
|---|---|---|---|---|
| Anthropic por API | `model-providers/anthropic` | PARCIAL: cliente con telemetria de cache; sin corrida real | construir | L S |
| Suscripcion de Claude Code | `auth_codex`, `copilot_auth` (equivalentes) | PARCIAL: cableada y probada; sesion del usuario caducada | construir | L S |
| Modelos locales | `models_local`, `ollama-cloud` | PARCIAL: cliente y guarda de loopback probados; Ollama sin instalar | construir | L E |
| 35 proveedores restantes (OpenRouter, Gemini, Bedrock, Vertex, Azure Foundry, DeepSeek, xAI, Qwen, Kimi, MiniMax, Nvidia, Fireworks, DeepInfra, Hugging Face, Copilot...) | `plugins/model-providers` (38) | PENDIENTE | construir adaptadores nativos | L S |
| Autenticacion por proveedor | `auth_*`, `auth_device_flow` | PENDIENTE | construir | S |
| Catalogo, precios y guarda de costo | `model_catalog`, `models_pricing`, `model_cost_guard` | PARCIAL: tarifas de Anthropic y overrides; sin guarda | construir | L M |
| Respaldo entre modelos | `fallback_cmd`, `fallback_config` | PENDIENTE | construir | L |
| Politica de datos por modelo | `model_data_policy_guard` | PENDIENTE | construir junto al tiering de sensibilidad | E S |

### 3. Herramientas

| Capacidad | En Hermes | lymi | Via | Reglas |
|---|---|---|---|---|
| Operaciones de archivo | `file_operations*`, `patch_parser` | PENDIENTE | integrar MCP + sandbox propio | E P X |
| Terminal y procesos | `terminal`, `process_registry*`, `pty_*` | PENDIENTE | construir en sandbox | P X |
| Ejecucion de codigo | `code_execution`, `code_kernel` local y remoto | PENDIENTE | construir en sandbox | P X |
| Navegador | `browser_*` (CDP, Lightpanda, Camofox, nube, vision) | PENDIENTE | integrar MCP | E P |
| Computer use | `computer_use`, `desktop_ui`, `tools_config_cua` | PENDIENTE | construir con plan/apply | P |
| Busqueda web | `web`, `web_result_cache`, `x_search` | PENDIENTE | integrar + destilacion local | E M |
| Vision | `vision` | PENDIENTE | construir | L E |
| Imagen y video | `image_generation`, `video_generation`, `xai_video` | PENDIENTE | integrar | L E |
| Voz: TTS, transcripcion, palabra de activacion | `tts*`, `transcription*`, `voice_mode`, `wake_word` | PENDIENTE | construir, transcripcion local primero | E |
| Home Assistant y Spotify | `homeassistant`, `plugins/spotify` | PENDIENTE | integrar MCP | P |
| Busqueda de herramientas | `tool_search*` | PENDIENTE | construir | M |
| Seguridad de URL, rutas y amenazas | `url_safety`, `path_security`, `threat_patterns`, `osv_check` | PARCIAL: lista blanca de hosts, loopback, escape de URL | construir | E X |

### 4. MCP

| Capacidad | En Hermes | lymi | Via | Reglas |
|---|---|---|---|---|
| Cliente stdio | `mcp_config` | HECHO: probado contra un servidor MCP real, incluido el aislamiento de entorno | construir | L E P S |
| Cliente HTTP remoto | 64 manifiestos http | HECHO: probado contra un servidor MCP real por streamable HTTP | construir | L E S |
| OAuth | `mcp_oauth*`, `web_server_oauth` | PARCIAL: almacen troceado y retorno probados; sin login real | construir | S |
| OAuth por codigo de dispositivo | `mcp_oauth_device` | PARCIAL: RFC 8628 con descubrimiento, registro dinamico, slow_down y keyring, probado contra servidor simulado; falta uno real | construir | S |
| Importar catalogo | `mcp_catalog`, `optional-mcps` (66) | HECHO: probado con manifiestos reales | integrar | P S X |
| Seleccion de herramientas | `mcp_picker`, `tools_config_mcp` | HECHO: lista blanca validada al cargar | construir | P |
| Supervisor y reinicio de servidores | `mcp_death_supervisor` | HECHO: reinicio con espera exponencial y degradacion, probado matando un servidor real; nunca repite la llamada en curso | construir | P |
| Cache de esquemas | `mcp_schema_cache` | PENDIENTE | construir | M |
| Auditoria de servidores | `mcp_security` | PENDIENTE | construir | P |
| lymi como servidor MCP | (equivalente: `api_server`) | PENDIENTE | construir | L |

### 5. Mensajeria

| Capacidad | En Hermes | lymi | Via | Reglas |
|---|---|---|---|---|
| Contrato de plataforma | `gateway/platforms/base`, `ADDING_A_PLATFORM` | PENDIENTE | construir | E P |
| Telegram | `plugins/platforms/telegram`, `telegram_managed_bot` | PENDIENTE | construir | E S |
| Slack | `plugins/platforms/slack`, `slack_cli` | PENDIENTE (hoy: webhook saliente con un paso http) | construir | E S |
| Discord | `plugins/platforms/discord` | PENDIENTE | construir | E S |
| Email | `plugins/platforms/email` | PENDIENTE | construir | E S |
| WhatsApp | `plugins/platforms/whatsapp`, `whatsapp_cloud` | PENDIENTE | construir | E S |
| Signal, iMessage, Teams, Google Chat, Matrix, Mattermost, IRC, LINE, SMS, ntfy, SimpleX | `gateway/platforms`, `plugins/platforms` | PENDIENTE | construir sobre el contrato | E S |
| DingTalk, Feishu, WeCom, WeChat, QQ, Yuanbao, Buzz, Photon, Raft | `gateway/platforms`, `plugins/platforms` | PENDIENTE | construir sobre el contrato | E S |
| Servidor API compatible con OpenAI | `gateway/platforms/api_server*` | PENDIENTE | construir | L E S |
| Agente a agente (A2A) | `plugins/platforms/a2a` | PENDIENTE | construir | L E |
| Cola y libro de entregas | `delivery`, `delivery_ledger` | PENDIENTE | construir sobre el ledger | L |
| Emparejamiento de dispositivos | `pairing` | PENDIENTE | construir | S |

### 6. Automatizacion

| Capacidad | En Hermes | lymi | Via | Reglas |
|---|---|---|---|---|
| Workflows declarativos | `blueprints` (equivalente) | HECHO: motor, plan, validacion estatica, CLI | construir | L E P S X |
| Disparador por webhook entrante | `webhook`, `webhook_filters` | HECHO: servidor probado de punta a punta; firma con ventana, deduplicacion, tope de cuerpo, cupo y rechazo de efectos no preaprobados | construir | E P X |
| Programacion (cron) | `cron/` (21), `chronos-managed-cron-contract`, `cron-doctor-spec` | HECHO: cron de 5 campos con zonas, agenda persistente y ejecutor que corre workflows reales | construir | L |
| Blueprints y catalogo de automatizaciones | `blueprint_catalog`, `blueprint_cmd` | PENDIENTE | construir | P |
| Kanban de agentes | `kanban*` (~25 modulos), spec v1 | PENDIENTE | construir | L |
| Hooks | `hooks`, `builtin_hooks` | PENDIENTE | construir | P X |
| Latido y monitor | `heartbeat`, `cron/monitor` | PENDIENTE | construir | |
| Puente a n8n | `optional-mcps/n8n` | PARCIAL: el manifiesto se importa; sin prueba contra n8n | integrar | P |

### 7. Aprobaciones, secretos y seguridad

| Capacidad | En Hermes | lymi | Via | Reglas |
|---|---|---|---|---|
| Aprobacion de efectos | `approval*` (10 modulos), `write_approval` | PARCIAL: reglas por paso/destino/metodo, memoria "siempre para este destino" con vencimiento, aprobacion que vence, preaprobacion desatendida; falta aprobacion remota y por costo | construir | P |
| Gestion de secretos | `secrets_cli`, `onepassword_secrets_cli`, `credential_lifecycle` | PARCIAL: entorno + almacen del sistema para OAuth | construir 1Password y rotacion | S |
| Saneamiento de entrada | `input_sanitize` | PENDIENTE, incluye Unicode invisible y bidi (ECC) | construir | X |
| Auditoria y avisos de seguridad | `security_audit`, `security_advisories` | PENDIENTE | construir | P |
| Contenedores y limites de recursos | `container_boot`, `resource_limits`, `docker/` | PENDIENTE | construir | P |
| Auditoria de skills | `skills_guard`, `skills_ast_audit`, `skill_linter` | PENDIENTE | construir | P X |
| Guarda del tier local | no encontrado | HECHO: loopback verificado por DNS | construir | E |
| Gateway de egress con bloqueo y redaccion | no encontrado | PARCIAL: hash por llamada; faltan bloqueo y redaccion | construir | E S |

### 8. Memoria, sesiones y conocimiento

| Capacidad | En Hermes | lymi | Via | Reglas |
|---|---|---|---|---|
| Contrato de memoria y backends (Honcho, mem0, Supermemory, Hindsight, Holographic, OpenViking, RetainDB, ByteRover) | `plugins/memory` | PENDIENTE | construir contrato; backends como plugins | E S |
| Memoria en markdown compatible con Obsidian | no encontrado | PENDIENTE (decidido) | construir | E |
| Sesiones: busqueda, resumen, exportacion y recuperacion | `session_*`, `sessions_cmd` | PENDIENTE | construir | |
| Proyectos y perfiles | `projects_*`, `profile_*`, `docs/profile-routing` | PENDIENTE | construir | P |
| Curador | `curator` | PENDIENTE | construir | M |

### 9. Skills y plugins

| Capacidad | En Hermes | lymi | Via | Reglas |
|---|---|---|---|---|
| Skills incluidas (12 dominios) y opcionales (21) | `skills/`, `optional-skills/` | PENDIENTE | adoptar formato ECC + importar | P X |
| Hub de skills (GitHub, oficial, skills.sh, ClawHub) | `skills_hub*` | PENDIENTE | construir | P |
| Procedencia y uso de skills | `skill_provenance`, `skill_usage`, `skill_ledger` | PENDIENTE | construir sobre el ledger | L |
| Sistema de plugins | `plugins_*`, `plugin_*` (~15) | PENDIENTE | construir | P |

### 10. Interfaces

| Capacidad | En Hermes | lymi | Via | Reglas |
|---|---|---|---|---|
| CLI | `hermes_cli` | PARCIAL: `bench`, `ledger`, `setup`, `flow`, `integrations`, `schedule`, `hooks`, `serve` | construir | |
| TUI | `ui-tui`, `tui_gateway`, `curses_ui` | PENDIENTE | construir | |
| Web y panel | `web_server_*` (~15), `dashboard` | PENDIENTE | construir | L E |
| App de escritorio | `apps/desktop` | PENDIENTE: maqueta disenada | construir | L E |
| Temas | `skin_engine`, `skin_cmd` | PENDIENTE: editor de temas disenado sobre `theme.toml` | construir | |
| Integracion con editores (ACP) | `acp_adapter` | PENDIENTE | construir | P |
| Barra de estado y notificaciones | `cli_status_bar_mixin`, `terminal_notify` | PENDIENTE: ledger en la barra disenado | construir | L |
| Mascotas y logros | `pets`, `plugins/hermes-achievements` | PENDIENTE | construir | |

### 11. Operacion

| Capacidad | En Hermes | lymi | Via | Reglas |
|---|---|---|---|---|
| Diagnostico | `doctor_*` (8) | PARCIAL: `lymi setup` prueba proveedores de verdad | construir | |
| Actualizaciones | `update_cmd_*` (15), `update_receipt` | PENDIENTE | construir | P |
| Respaldo y migracion | `backup`, `migrate`, `config_migrations` | PENDIENTE | construir | S |
| Observabilidad | `plugins/observability`, `docs/observability` | PARCIAL: ledger por llamada; faltan trazas | construir | L |
| Registros y diagnostico | `logs`, `diagnostics_upload`, `dump` | PENDIENTE; nada se sube sin consentimiento | construir | E |
| Git worktrees | `worktree_cmd`, `worktree_ops`, `worktree_gc` | PENDIENTE | construir con el patron de orca | P |
| Servicio en segundo plano | `service_manager`, `relaunch` | PENDIENTE | construir | |
| Proxy | `proxy`, `proxy_cli` | PENDIENTE; base del gateway de egress | construir | E |
| Despliegue: Docker, Nix, instalador | `docker/`, `nix/`, `apps/bootstrap-installer` | PENDIENTE | construir | |
| Idiomas | `locales/` | PENDIENTE | construir | |

### 12. Medicion

| Capacidad | En Hermes | lymi | Via | Reglas |
|---|---|---|---|---|
| Banco de pruebas falsable con linea base publica | no encontrado | PARCIAL: funciona en modo demo; falta corrida real | construir | M |
| Recibo verificable y compartible | no encontrado | HECHO | construir | M |
| Curva de escalamiento por tamano de repositorio | no encontrado | PENDIENTE | construir | M |

## Oleadas

El orden sigue las dependencias: cada oleada necesita lo que construyo la
anterior.

1. **Integraciones y disparadores** *(casi cerrada)*. Hecho: MCP probado contra
   servidores reales, supervisor, webhook entrante, cron, aprobaciones con reglas,
   memoria y vencimiento, OAuth por dispositivo. Falta: probar OAuth (navegador y
   dispositivo) contra un servidor real, aprobacion remota y por costo.
2. **Agente.** Bucle con herramientas, archivos y terminal en sandbox, navegador
   y busqueda via MCP, subagentes en worktrees, compresion con presupuesto duro.
3. **Mensajeria.** Contrato de plataforma; Telegram, Slack, Discord, email y
   WhatsApp primero; API compatible con OpenAI; A2A.
4. **Conocimiento.** Contrato de memoria y backends, sesiones, hub de skills con
   esquemas de ECC, sistema de plugins.
5. **Interfaces.** TUI, web y panel, app de escritorio con temas, ACP, kanban,
   blueprints.
6. **Resto.** Voz, imagen, video y vision; Home Assistant y Spotify;
   actualizaciones, respaldo, despliegue e idiomas.
