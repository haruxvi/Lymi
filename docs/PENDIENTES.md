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
- [ ] Quitar el sesgo de orden: calentar la cache del proveedor antes de ambas
      corridas (llamada descartada y registrada aparte) o alternar el orden en
      repeticiones. Hoy el recibo solo se niega a anunciar.
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
- [ ] Comandos para listar y olvidar decisiones recordadas.
- [ ] Probar OAuth por dispositivo contra un servidor de autorizacion real.
- [ ] `lymi integrations login` probado contra un servidor OAuth real.
- [ ] Probar el puente de n8n del catalogo contra una instancia real.

## 3. Resolver los tres riesgos del control del PC

Ver `ARQUITECTURA_AGENTE_SEGURO.md`.

- [ ] Saneamiento de Unicode invisible y bidi en toda entrada ajena.
- [ ] Etiquetas de sensibilidad y bloqueo en el gateway de egress.
- [ ] Redaccion reversible de secretos y PII.
- [ ] Memoria markdown (compatible Obsidian) + diario de sesion + recuperacion acotada.
- [ ] Ejecutor del host con RPC cerrada, capacidades por ruta, diario de deshacer.
- [ ] Sandbox para codigo generado; worktrees para cambios en repos.
- [ ] Interruptor de parada y presupuestos por tarea.

## 4. Oleada 2 — agente

- [ ] Bucle de agente con herramientas (sobre MCP y el ejecutor del host).
- [ ] Retrieval simbolico (Serena/`solidlsp`) + curva de escalamiento plana.
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
- [ ] Graficos via mcp-server-chart solo con servidor de render propio.

## 5. Oleadas 3-6

Mensajeria, conocimiento, interfaces y el resto: ver la matriz de
`PARIDAD_HERMES.md` (98 capacidades, 9 hechas, 15 parciales, 74 pendientes).

## 6. Diseno

- [x] Aplicar la direccion risografia al sitio (`design/sitio-lymi.html`, publicado).
- [x] Aplicar la risografia a las 7 pantallas de la app (`design/*.dc.html`,
      canvas republicado en la misma URL).
- [ ] Editor de temas funcional sobre `~/.config/lymi/theme.toml`.
- [ ] Lienzo de nodos estilo n8n sobre el YAML, ida y vuelta sin perder
      comentarios: posiciones en `meta.canvas`, paleta arrastrable, rama si/no.
      El YAML sigue siendo la fuente de verdad. Diseno hecho (`Workflow.dc.html`).

## 7. Distribucion

- [ ] Docker / instalador para Windows, macOS y Linux.
- [ ] README de usuario final con los tres caminos: estudiante (solo local),
      suscripcion, API key.
