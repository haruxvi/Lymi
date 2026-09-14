# Roadmap

Cada fase tiene un entregable y una **puerta medible**. Si la puerta no pasa, no
se avanza: se corrige la palanca o se descarta. Una fase sin puerta es una
opinion.

| Fase | Entregable | Puerta |
|---|---|---|
| **0** | Ledger + banco de pruebas + 3 tareas | El mismo experimento corrido dos veces da numeros reproducibles |
| **1** | Linea base publica (agente ReAct ingenuo) | Resuelve las 3 tareas; costo medido y publicado |
| **2** | Cache de prefijo estable | −30 a −50% de costo, misma tasa de exito |
| **3** | Tier local (Ollama 4B) + destilacion | Investigacion −70% sin perder calidad de citas |
| **4** | Retrieval simbolico (LSP / tree-sitter) | Repo grande −60%; **curva de escalamiento plana** |
| **5** | Router de modelos + subagentes + memoria | El router acierta ≥90%, medido |
| **6** | Gateway de egress + redaccion + auditoria | Log completo de que salio de la maquina |
| **7** | Policy engine + debate de agentes (opt-in) | El debate cambia el resultado con frecuencia medible |
| **8** | Ejecutor host + Docker + UI | Plan/apply con deshacer; sin operaciones destructivas sin confirmar |

## Las tres tareas del benchmark

Se reportan **por separado**. Un promedio unico esconde justo lo que importa.

1. **`snake`** -- escribir un juego Snake en Python. Proyecto minusculo: **no
   mide ahorro**, mide **correctitud**. Es la puerta que impide que "recortar
   contexto" degenere en "romper el agente".
2. **`research`** -- pregunta de investigacion con fuentes web. Aqui vive el
   mayor ahorro: el agente ingenuo vuelca paginas crudas al modelo caro.
3. **`repo`** -- una modificacion acotada sobre repositorios OSS de tamano
   creciente (~1k, ~10k, ~100k, ~1M lineas). **Esta es la prueba de
   escalamiento**: no produce un porcentaje, produce una curva.

## Decisiones tomadas

- **Sin LiteLLM.** La telemetria de cache es especifica de cada proveedor y es la
  metrica central de la Fase 2; una capa normalizadora la aplana justo donde hay
  que medir. Adaptadores nativos con SDK oficial.
- **Docker al final, no al principio.** En 16 GB de RAM, Docker Desktop compite
  por la memoria que necesita el modelo local. Se desarrolla nativo con `uv` y se
  contenedoriza cuando el sistema funciona.
- **Python 3.12**, no 3.14: los bindings de LSP y llama-cpp aun no traen wheels
  para 3.14.
- **Dos contratos de proveedor**, no uno. `LLMClient` (nivel mensaje, lymi arma
  el contexto) y `AgentBackend` (nivel tarea, harness externo). Unificarlos seria
  mentir sobre que controla el sistema.

## Workflows e integraciones

**Decision de alcance: no construimos conectores.** Escribir e integraciones tipo
n8n es un pozo sin fondo que hundiria el proyecto. lymi actua como **cliente MCP**
y hereda el ecosistema de conectores existente.

Encima de eso va un motor de workflows declarativo (YAML), donde **cada paso
declara su tier**:

```yaml
name: triage-de-leads
steps:
  - id: extraer
    tier: local          # gratis, en tu GPU
    prompt: "Extrae empresa, cargo y presupuesto de este correo"
  - id: clasificar
    tier: local
  - id: redactar-respuesta
    tier: remote         # solo aqui se paga
    when: "clasificar.score > 0.7"
```

En un workflow de 40 pasos, ~35 los ejecuta el modelo local. Ahi la tesis del
proyecto deja de ser teorica: el costo del workflow no crece con su longitud,
crece con cuantos pasos exigen razonamiento real.

## Rango de usuarios (restriccion de diseno)

El sistema debe servir desde un estudiante hasta un CEO de startup. Eso impone
dos requisitos no negociables:

- **Debe ser util con solo Ollama, sin ninguna API key.** Si el tier gratuito no
  resuelve tareas reales por si solo, el estudiante nunca entra.
- **El log de egress debe ser presentable a un tercero.** Para el CEO no es una
  curiosidad tecnica: es el argumento de cumplimiento frente a su cliente o su
  auditor.

Es el mismo sistema; cambia cual de las dos garantias le importa a cada perfil.

## Repositorios de referencia — veredicto

Auditado: licencia, estructura y que es reutilizable. No se ha leido la logica
interna de ninguno.

| Repo | Licencia | Veredicto |
|---|---|---|
| **serena** | MIT | **Usar.** 77 servidores de lenguaje via `solidlsp`. Es la palanca de retrieval simbolico, ya resuelta. Nunca reconstruir esto. |
| **ECC** | MIT | **Adoptar sus contratos.** Esquemas de plugin, memoria, procedencia, estado y hooks. Hablar su formato = heredar sus 292 skills. |
| **hermes-agent** | MIT | **Leer, no forkear.** Prior art de compresion de contexto, contabilidad y auth por suscripcion. |
| **orca** | MIT | **Estudiar el patron.** Aislamiento por git worktree para el control del PC. |
| **dionysus** | ninguna | Solo inspiracion. Sin licencia no se puede reutilizar codigo. |
| **JARVIS** | ninguna | **Descartado.** Su proposito (reconocimiento facial y perfiles de personas) queda fuera del alcance de este proyecto, y el tratamiento de datos biometricos exigiria un marco legal que lymi no pretende cubrir. Sin licencia: solo se toman ideas genericas (observabilidad de agentes, patron orquestador-abanico-sintesis). |

### Decisiones que se derivan

- **Integrar donde ya hay ecosistema; construir solo lo que nadie tiene.** Vale
  para conectores (MCP), retrieval (Serena) y plugins/skills (esquemas de ECC).
  Lo que no existe en ningun lado -- y por tanto es lo unico que hay que
  construir desde cero -- es el banco de pruebas falsable y el control de egress
  auditable.
- **El log de egress deberia hablar un esquema de procedencia existente**
  (`provenance.schema.json`) en vez de inventar el suyo.
- **Fase 6 gana un requisito:** sanitizar caracteres Unicode invisibles y de
  control bidireccional antes de que un documento llegue al modelo. Es inyeccion
  de prompt escondida en texto que el usuario no ve, y el gateway procesa
  documentos ajenos por definicion.
- **Leer entera la guia de seguridad de ECC antes de la Fase 8** (sandboxing,
  fronteras de aprobacion, kill switches, minima agencia).
