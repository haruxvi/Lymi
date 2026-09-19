# Pendientes para que lymi este operativo

Ordenado por dependencia: cada bloque necesita el anterior. Marca `[x]` al
terminar y anota el cambio en `BITACORA.md`. Una tarea solo se marca con prueba.

## 0. Bloqueantes del usuario (nadie mas puede hacerlos)

- [ ] **Primer commit de git.** Lo hace el usuario (no hacer commits). Auditoria
      de licencias hecha el 2026-09-13: LICENSE Apache-2.0 agregado, dependencias
      permisivas, bundles generados en `.gitignore`.
- [ ] `claude auth login` (o `claude` → `/login`). Sin esto no hay medicion real
      por suscripcion. Verificar con `claude auth status`.
- [x] Ollama instalado (2026-09-13).
- [x] Modelo local descargado. Por defecto `qwen2.5:3b` (medido: 0.4 s y 100%
      GPU en 4 GB de VRAM; `qwen3:4b` razona 700 tokens y tarda 64 s).
- [ ] Verificar con `uv run lymi setup`: todo en verde.

## 1. Primera medicion real (lo que convierte el proyecto en verdad)

- [x] `lymi bench snake` sin `--demo` contra suscripcion + Ollama (2026-09-13).
      Destapo seis defectos de contabilidad, corregidos (ver BITACORA).
- [x] Calentamiento de cache antes de medir (`--calentar`, activo por defecto;
      corrida aparte `calentamiento` en el ledger). Falta confirmarlo en una
      corrida real: si la cache heredada vuelve a aparecer, alternar el orden.
      Intento del 2026-09-14: la linea base paso con calentamiento, pero la
      suscripcion llego a su limite de sesion a mitad de lymi. Repetir.
- [ ] `--repeticiones N` con mediana e intervalo: una corrida no es evidencia.
- [ ] Medir el costo fijo del harness: `claude -p` arrastra ~28k tokens de
      prefijo por llamada. Para llamadas chicas puede convenir la API directa.
- [ ] Tarea `research` con fuentes reales y destilacion local.
- [ ] Tarea `repo` sobre 3-4 repos OSS de tamano creciente; publicar la curva.
- [ ] Publicar el primer recibo real.

## 2. Oleada 1 — integraciones y disparadores (en curso)

- [x] Supervisor de servidores MCP: reinicio con espera exponencial, degradacion,
      sin repetir la llamada en curso. (`flows/nodes.py`, `tests/test_supervisor_mcp.py`)
- [x] OAuth por codigo de dispositivo (RFC 8628): `lymi integrations login --dispositivo`.
      (`flows/oauth_dispositivo.py`, probado contra servidor simulado)
- [x] Aprobaciones: reglas por paso/destino/metodo (`--politica`), memoria "siempre
      para este destino" con vencimiento, aprobacion que vence (`--vencimiento`).
      (`flows/aprobaciones.py`)
- [ ] Aprobacion remota (ej. mensaje con boton) — depende de la mensajeria (oleada 3).
- [ ] Aprobacion por umbral de costo estimado del paso.
- [x] Comandos para listar y olvidar decisiones recordadas
      (`lymi flow approvals list|forget`).
- [ ] Probar OAuth por dispositivo contra un servidor de autorizacion real.
- [ ] `lymi integrations login` probado contra un servidor OAuth real.
- [ ] Probar el puente de n8n del catalogo contra una instancia real.

## 3. Resolver los tres riesgos del control del PC

Ver `ARQUITECTURA_AGENTE_SEGURO.md`.

- [x] Saneamiento de Unicode invisible y bidi en toda entrada ajena: entradas de
      workflows, salidas de herramientas y HTTP, y todo mensaje a un modelo
      (`privacidad/unicode.py`).
- [x] Etiquetas de sensibilidad y bloqueo en el gateway de egress: niveles por
      ruta con piso fijo (`privacidad/etiquetas.py`, `sensibilidad.yml`); el texto
      literal `nunca-sale` no llega a remoto, MCP ni HTTP; claves privadas bloquean.
- [x] Redaccion reversible de secretos y PII antes de salir, rehidratada al volver,
      contada en el ledger (`privacidad/redaccion.py`, columna `redacciones`).
- [ ] Etiquetas en la interfaz y en entradas que no vienen de archivo (hoy solo
      `flow run -i x=@archivo`).
- [ ] Memoria markdown (compatible Obsidian) + diario de sesion + recuperacion acotada.
- [x] Ejecutor del host con operaciones cerradas (leer, listar, escribir, mover,
      borrar, ejecutar), capacidades por ruta y diario de deshacer (`ejecutor/`,
      paso `pc` en workflows, `lymi undo <corrida>`, `ejecutor.example.yml`).
      Nunca hay shell: los interpretes y los .bat/.cmd se rechazan, el comando
      corre con `shell=False` y sin las variables de entorno de lymi. Vetado
      siempre: sistema operativo, credenciales del usuario, `runs/` y `.git`.
      41 pruebas destructivas en `tests/test_ejecutor.py` y `tests/test_pc_flujo.py`.
- [ ] Sandbox para codigo generado; worktrees para cambios en repos.
- [x] Interruptor de parada (`lymi stop|resume`, boton en la app que ademas
      revoca aprobaciones pendientes) y presupuestos por tarea
      (`flow run --max-tokens-remotos --max-llamadas`) (`control.py`).
- [x] Presupuesto de archivos tocados por corrida (`max_archivos` del perfil).
- [ ] Tecla global de parada.
- [ ] Sandbox del sistema operativo por debajo del ejecutor (hoy la frontera es
      la lista blanca, no el kernel).

## 3b. Capa web propia (sin servicios de terceros)

Construida a partir de lo que hacen bien Firecrawl (pagina a markdown, mapa de
sitio) y los buscadores con respuesta tipo Perplexity, con codigo propio y las
garantias de lymi. Ver `src/lymi/web/`.

- [x] Pagina a markdown limpio: se queda con `main`/`article`, descarta menus,
      pies, formularios, scripts y **todo lo que el navegador no muestra**
      (`hidden`, `aria-hidden`, `display:none`, letra de tamano cero), que es la
      via barata de inyectar instrucciones. (`web/markdown.py`)
- [x] Guardia de red contra SSRF: cada salto resuelve el nombre, exige que todas
      sus direcciones sean publicas y conecta a la IP ya comprobada (el nombre
      viaja en `Host` y en SNI, asi el certificado se sigue validando). Las
      redirecciones se siguen a mano repitiendo la comprobacion. (`web/red.py`)
- [x] La URL y la consulta son egress: si llevan un secreto o un dato personal,
      no salen; cada peticion queda en el ledger.
- [x] robots.txt respetado, tope de bytes, solo tipos de texto, aviso cuando la
      pagina intenta dar ordenes a un modelo.
- [x] Mapa de sitio (sitemap + enlaces, mismo host) y busqueda con el buscador
      del usuario (SearXNG local via `LYMI_BUSCADOR_URL`).
- [x] `investigar`: elige los pasajes en local con BM25 (no manda la pagina
      entera) y **verifica cada cita textual contra su fuente**; las inventadas y
      las referencias a fuentes inexistentes se reportan. (`web/investigar.py`)
- [x] Paso `web` en workflows y comandos `lymi web leer|mapear|buscar|investigar`.
- [ ] Probar `buscar` contra una instancia real de SearXNG del usuario.
- [ ] Navegador propio para lo que no se puede leer con HTTP (paginas que se
      arman con JavaScript, formularios): driver CDP contra el Edge/Chrome ya
      instalado, con perfil temporal aislado (sin las cookies del usuario),
      lista blanca de dominios, acciones cerradas (navegar, leer, clic por
      referencia de accesibilidad, escribir, captura) y aprobacion para cada
      envio. Idea tomada de Playwright; implementacion propia.
- [ ] Cache local de paginas por corrida (hoy cada lectura vuelve a pedir).

## 4. Oleada 2 — agente

- [ ] Bucle de agente con herramientas (sobre MCP y el ejecutor del host).
- [x] Mapa de codigo propio (`src/lymi/codigo/`, `lymi codigo ...`, paso `codigo`,
      servidor MCP `lymi codigo servir`): esqueleto, fragmento, buscar, llamadores,
      impacto y mapa. Fresco antes de cada consulta, sin re-analizar lo que no
      cambio, sin indexar lo `nunca-sale`. Llamadas confirmadas por importacion; los
      homonimos se reportan aparte. Medido sobre lymi: esqueletos 82% menos bytes
      que los archivos; un fragmento, 95% menos que el archivo que lo contiene.
- [ ] Medir el mapa en el bench (tarea `repo`): agente con y sin mapa, con puerta
      de correccion (palabras obligatorias o pruebas) para que una respuesta rapida
      y equivocada no gane. Idea de metodo tomada de Graft.
- [ ] Analisis exacto para mas lenguajes (hoy solo Python; JS/TS, Go y Rust son
      aproximados y lo dicen). Candidato: tree-sitter (MIT).
- [ ] Retrieval simbolico con tipos (Serena/`solidlsp`) + curva de escalamiento plana.
- [ ] Compresion de contexto con presupuesto duro.
- [ ] Subagentes en worktrees; router de modelos medido.

## 4b. Palancas de ahorro y memoria halladas en referencias

Ver `REFERENCIAS.md`. Cada una se mide en el ledger antes de declararla util.

- [ ] Interceptor de llamadas auxiliares del harness respondidas en local
      (cuota, titulo, prefijo de comando, sugerencias, rutas), registradas como
      tokens evitados. Origen: free-claude-code.
- [ ] Compuerta de deduplicacion (sesion, archivo, epoca) en la recuperacion de
      contexto. Origen: claude-mem.
- [ ] Recibos de decision reproducibles para toda consolidacion de memoria.
      Origen: dsh-mneme.
- [ ] Calor con decaimiento por tipo de recuerdo; espejo markdown al vault con
      prioridad a la edicion humana. Origen: dsh-mneme.
- [ ] Expiracion con motivo y supersesion en vez de sobrescritura. Origen: memanto.
- [ ] Defensa de memoria (audit / block / quarantine) y accion PII en el gateway.
      Origen: zettelforge.
- [ ] Contexto de pantalla via arbol de accesibilidad, no capturas. Idea de
      Everywhere (BSL: implementacion propia).
- [ ] Evaluar RTK sobre la salida de herramientas y zvec como indice local.
- [ ] Registrar la cuantizacion del modelo local (Ollama `/api/show`) en el ledger y
      el recibo: comparar contra un modelo sin decir su precision es humo. Principio
      tomado de colibri: nunca cambiar la precision en silencio.
- [ ] Roles de agente importables desde markdown con frontmatter (formato de
      agency-agents), con su costo en tokens visible en `flow plan` y medidos en el
      bench antes de recomendarlos: una personalidad larga cuesta tokens en cada llamada.
- [ ] Graficos via mcp-server-chart solo con servidor de render propio.

## 5. Oleadas 3-6

Mensajeria, conocimiento, interfaces y el resto: ver la matriz de
`PARIDAD_HERMES.md` (98 capacidades, 9 hechas, 15 parciales, 74 pendientes).

## 6. Diseno

- [x] Aplicar la direccion risografia al sitio (`design/sitio-lymi.html`, publicado).
- [x] Aplicar la risografia a las 7 pantallas de la app (`design/*.dc.html`,
      canvas republicado en la misma URL).
- [x] App navegable `lymi ui` sobre datos reales: inicio, proveedores, medir,
      corridas y detalle, workflows (plan, entradas, correr, aprobar desde el
      navegador), egress y apariencia.
- [x] Editor de temas funcional sobre `~/.config/lymi/theme.toml` (en la app).
- [ ] App: pantallas que aun son maqueta (mapa de costos, lienzo de nodos,
      sesion de agente) llegan cuando exista lo que muestran.
- [ ] App: fuentes de la risografia empaquetadas localmente (hoy usa las del
      sistema para no pedir nada a internet).
- [ ] Pasos de repeticion en workflows (`foreach` sobre una lista, con tope de
      iteraciones y presupuesto compartido): hoy un mapa de sitio se recorre
      dentro del nodo, no en el workflow.
- [ ] Lienzo de nodos estilo n8n sobre el YAML, ida y vuelta sin perder
      comentarios: posiciones en `meta.canvas`, paleta arrastrable, rama si/no.
      El YAML sigue siendo la fuente de verdad. Diseno hecho (`Workflow.dc.html`).

## 7. Distribucion

- [ ] Docker / instalador para Windows, macOS y Linux.
- [ ] README de usuario final con los tres caminos: estudiante (solo local),
      suscripcion, API key.
