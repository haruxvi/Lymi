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

### Hilos abiertos al cierre

- Bloqueante del usuario: primer commit (configurar correo noreply antes).
- Repetir `lymi bench snake` real con calentamiento cuando la suscripcion se restablezca.
- Primera medicion real.
- Editor de temas funcional sobre `theme.toml`.
