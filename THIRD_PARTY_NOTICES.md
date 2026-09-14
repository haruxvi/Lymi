# Avisos de terceros

lymi se distribuye bajo Apache-2.0. Este archivo registra todo codigo de terceros
incorporado al repositorio y la licencia que lo permite.

## Regla del proyecto

1. **Todo codigo nace con derechos de autor.** Un repositorio publico sin archivo
   de licencia es *todos los derechos reservados*: no se puede reutilizar su
   codigo, por accesible que sea.
2. **Solo se incorpora codigo con licencia permisiva** (MIT, BSD, Apache-2.0).
   Copyleft fuerte (GPL, AGPL) requiere decision explicita porque cambia la
   licencia de todo el proyecto.
3. **Toda incorporacion se anota abajo** con su origen, su commit y su licencia,
   y conserva el aviso de copyright original en los archivos afectados.
4. **Las ideas no se licencian, la expresion si.** Leer un proyecto para entender
   como resolvio un problema y escribir la propia implementacion es legitimo y no
   requiere aviso. Pegar sus archivos, si.

## Dependencias

Las dependencias declaradas en `pyproject.toml` se instalan desde PyPI y
conservan sus propias licencias; no se vendorizan aqui.

## Codigo incorporado

*(ninguno todavia)*

Formato de cada entrada:

```
### <nombre>
- Origen:    https://github.com/<owner>/<repo>
- Commit:    <sha>
- Licencia:  MIT
- Que se incorporo: <rutas dentro de lymi>
- Aviso de copyright original: <texto literal del LICENSE>
```

## Proyectos consultados sin incorporar codigo

Leidos para entender como resolvieron un problema. No contienen codigo suyo en
este repositorio, por lo que no requieren aviso; se listan por transparencia.

| Proyecto | Licencia | Que se aprendio |
|---|---|---|
| [serena](https://github.com/oraios/serena) | MIT | Retrieval simbolico via LSP. Candidato a incorporar (`solidlsp`) o a usar como servidor MCP. |
| [ECC](https://github.com/affaan-m/ECC) | MIT | Esquemas de plugin, memoria, procedencia y hooks. Sanitizacion de Unicode invisible y control bidireccional. |
| [hermes-agent](https://github.com/NousResearch/hermes-agent) | MIT | Compresion de contexto, contabilidad de consumo, autenticacion por suscripcion. |
| [orca](https://github.com/stablyai/orca) | MIT | Aislamiento de agentes por git worktree. |
| [dionysus](https://github.com/pewdiepie-archdaemon/dionysus) | sin licencia | Solo referencia estetica. Sin licencia no se reutiliza codigo. |
| [JARVIS](https://github.com/affaan-m/JARVIS) | sin licencia | **Descartado.** Su proposito (reconocimiento facial y perfiles de personas) queda fuera del alcance de este proyecto. |
| [free-claude-code](https://github.com/Alishahryar1/free-claude-code) | MIT | Respuestas locales a llamadas auxiliares del harness; fallback entre modelos. |
| [claude-mem](https://github.com/thedotmack/claude-mem) | Apache 2.0 (con NOTICE) | Compuerta de inyeccion por sesion, archivo y epoca; divulgacion progresiva. |
| [dsh-mneme](https://github.com/modusensus/dsh-mneme) | MIT | Recibos de decision, calor por tipo, espejo markdown con prioridad humana. |
| [memanto](https://github.com/moorcheh-ai/memanto) | MIT | Expiracion con motivo, supersesion, briefing minimo. |
| [zettelforge](https://github.com/ThreatRecall/zettelforge) | MIT | Defensa de memoria audit/block/quarantine; accion PII. |
| [memU](https://github.com/NevaMind-AI/memU) | Apache 2.0 | Memoria como wiki; destilacion de skills. |
| [zvec](https://github.com/alibaba/zvec) | Apache 2.0 | Candidato a recuperacion vectorial embebida. |
| [superpowers](https://github.com/obra/superpowers) | MIT | Reglas de verificacion y depuracion adoptadas. |
| [mcp-server-chart](https://github.com/antvis/mcp-server-chart) | MIT | Graficos via MCP; solo con servidor de render propio. |
| [dify](https://github.com/langgenius/dify) | Apache 2.0 modificada | Solo ideas: nodo de intervencion humana con vencimiento. |
| [Everywhere](https://github.com/Sylinko/Everywhere) | BSL 1.1 | Solo ideas: contexto de pantalla via arbol de accesibilidad. |

## Recursos de diseno

- **Fuentes** (Archivo, Archivo Black, JetBrains Mono, Noto Sans JP): SIL Open
  Font License 1.1. Se cargan desde Google Fonts; no se incluyen archivos de
  fuente en el repositorio.
- **Paletas de la comunidad** nombradas en `design/Temas.dc.html` (Catppuccin,
  Gruvbox, Tokyo Night, Rose Pine): solo valores de color hexadecimales, que no
  son objeto de derechos de autor; los nombres se usan para identificar el
  origen y no implican afiliacion.
- **Bundles generados** (`design/lymi-desktop.html`,
  `design/direcciones/direcciones-lymi.html`): contienen el runtime del
  visor de canvas (React, MIT, y codigo de la herramienta de diseno). Estan en
  `.gitignore`; se regeneran desde los `design/*.dc.html`, que son originales.

## Marcas

Hermes, Claude, Anthropic, Ollama, Qwen, Obsidian, n8n y demas nombres
se mencionan solo para describir compatibilidad o comparar. lymi no esta
afiliado a ninguno de ellos.

## Instalado fuera de este repositorio

- [obsidian-skills](https://github.com/kepano/obsidian-skills) (MIT): copiado al
  vault de Obsidian del usuario (`.claude/skills/`) con su licencia y el
  SHA de origen. No forma parte del codigo distribuido de lymi.
