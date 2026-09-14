# Contexto, proposito y vision de lymi

Documento de referencia. Si una sesion nueva solo pudiera leer un archivo, seria
este.

## Proposito

lymi es un orquestador de agentes **local-first** que hace verificable lo que el
resto del ecosistema solo afirma:

- **Cuanto gasta.** Toda llamada queda en un ledger con tokens, costo y modo de
  facturacion. El ahorro se mide contra una linea base publica, ejecutable por
  cualquiera.
- **Que saca de tu maquina.** Todo egress queda registrado por destino y hash del
  payload, nunca el contenido.
- **Que puede romper.** Toda accion con efectos se aprueba, se acota y se puede
  deshacer.

## Por que existe

Tres problemas frecuentes en el ecosistema de agentes:

1. **Agentes que queman tokens sin medir nada** ni publicar contra que comparan.
2. **"Segundos cerebros"** con grafos bonitos que, en proyectos grandes, gastan
   mas porque vuelcan el grafo al contexto.
3. **"Vaults locales" que no lo son**: si el modelo es remoto, cada documento pasa
   por la API del proveedor.

Y un cuarto, el que motiva la vision: los **agentes con control del PC** suelen
aislarse en una maquina desechable porque arrastran tres riesgos:

- pueden **romper el sistema**,
- sufren **amnesia** entre sesiones,
- y **los datos personales pasan por la API** del proveedor.

Resolver esos tres es el paso previo a la vision. Ver `ARQUITECTURA_AGENTE_SEGURO.md`.

## Vision

Un **Jarvis anti-humo**: asistente conectado a todas las funcionalidades del PC y
del programa, que

- funciona de verdad y lo demuestra con numeros reproducibles,
- no es un quemadero de tokens (el volumen pesado corre gratis en la GPU local),
- no rompe la maquina (sandbox, plan/apply, deshacer),
- recuerda (memoria persistente en markdown compatible con Obsidian),
- y no filtra datos personales (tiering de sensibilidad + gateway de egress).

Camino: primero el instrumento (medicion y control), despues las funcionalidades
encima. Paridad completa con Hermes Agent, cada funcionalidad mejorada con las
reglas L/E/P/S/X/M de `PARIDAD_HERMES.md`.

## La afirmacion central (y como se falsa)

> Los tokens remotos por tarea dependen de la complejidad de la tarea, no del
> tamano del proyecto.

Se falsa con una curva: la misma tarea sobre repos de 1k, 10k, 100k y 1M lineas.
Plana = se sostiene. Creciente = es falsa y se reporta. Detalle en
`METHODOLOGY.md`.

Mecanismos: el indice nunca entra al contexto; retrieval de simbolos, no de
archivos; destilacion en el modelo local; presupuesto de contexto duro.

## Decisiones tomadas (no re-discutir sin motivo nuevo)

| Decision | Motivo |
|---|---|
| Paridad total con Hermes + ecosistema, no un producto recortado | Decision explicita del usuario |
| Sin LiteLLM; adaptadores nativos | La telemetria de cache es por proveedor |
| Python 3.12 via `uv` | Wheels de LSP/llama-cpp no existen para 3.14 |
| Docker al final | En 16 GB compite con el modelo local |
| Dos contratos: `LLMClient` (lymi arma el contexto) y `AgentBackend` (harness externo) | No mentir sobre que controla el sistema |
| Suscripcion de Claude Code como proveedor via `claude -p` con herramientas apagadas | Uso sin API key. El modo (suscripcion o api) lo decide el entorno: `total_cost_usd` trae valor tambien con suscripcion |
| MCP para conectores, no escribirlos | n8n tardo anos; heredar el ecosistema |
| Memoria = markdown plano con wikilinks | Compatible con Obsidian/Logseq sin competirles |
| Grafo = mapa de costos del indice real, no decorativo | El grafo decorativo es justo el humo criticado |
| Recibo compartible con ids de corrida y comando de reproduccion | "Flexeable" y verificable a la vez |
| JARVIS (affaan-m) descartado | Su proposito (reconocimiento facial y perfiles de personas) queda fuera del alcance; ademas no tiene licencia |

## Entorno de referencia

- Las mediciones se hacen en un portatil con GPU de **4 GB de VRAM** y 16 GB de RAM.
- Modelo local por defecto: `qwen2.5:3b` (cabe entero en 4 GB, ~0.4 s por resumen
  corto). `qwen3:4b` no cabe entero (~13 tok/s) y razona cientos de tokens antes
  de responder: no sirve para el tier local.
- Rutas, cuentas y detalles de la maquina del desarrollador: `CLAUDE.local.md`
  (no versionado).

## Diseno

Artefactos publicados:

- App (7 pantallas en risografia): https://claude.ai/code/artifact/18b72374-b1d4-4af5-b5e9-79d2959f6747
- Sitio (ya en risografia, 2026-09-13): https://claude.ai/code/artifact/fcd94edf-813a-413e-89f0-399cf292f55f
- Direcciones + punto medio elegido: https://claude.ai/code/artifact/16325a69-898b-435f-b888-7c61e10fa496

**Direccion elegida: risografia** (punto medio entre "otaku/Y2K" y "fanzine"),
fuente de verdad en `design/direcciones/Main.dc.html`:

- Papel oscuro violeta `#191324`, rosa fluor `#ff48a0`, menta `#5ef2a8`, crema `#f5eee0`.
- Archivo Black (display), Noto Sans JP (katakana ライミ), JetBrains Mono (datos).
- Trama de puntos en vez de degradados, desregistro de segunda tinta, grano de
  papel, cinta adhesiva, sello + sticker, elementos levemente rotados.
- Sin efectos de scroll. Todo visible en reposo.
- El usuario quiere temas personalizables estilo "rice" de Arch (editor de temas
  sobre `~/.config/lymi/theme.toml`).
- Semantica de color: local/gratis vs remoto/se paga vs bloqueado.
