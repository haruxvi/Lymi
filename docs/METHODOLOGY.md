# Metodologia: como lymi evita ser humo

Este documento es un contrato. Si lymi deja de cumplirlo, la afirmacion central
del proyecto es falsa y hay que decirlo, no matizarlo.

## 1. La afirmacion

No afirmamos "ahorra un 80% de tokens". Esa frase no es falsable: quien la dice
elige la linea base que le conviene, y nadie puede desmentirla.

Afirmamos esto:

> **Los tokens remotos consumidos por una tarea son funcion de la complejidad de
> la tarea, no del tamano del proyecto.**

Un agente ingenuo es `O(N)` sobre el tamano del repositorio: mientras mas grande,
mas lee y mas paga. lymi debe ser `O(k)`, donde `k` es el tamano de la porcion
relevante, y `k` no depende de `N`.

## 2. Como se falsa

La prueba de escalamiento: **la misma tarea, sobre repositorios de tamano
creciente** (~1k, ~10k, ~100k, ~1M lineas), midiendo tokens remotos por tarea.

- Curva plana -> la afirmacion se sostiene.
- Curva creciente -> la afirmacion es falsa. Se reporta como falsa.

El grafico se publica con cada version. Un porcentaje se puede elegir; una curva
no. Cualquiera puede correr el benchmark y contradecirnos: ese es el punto.

## 3. Los mecanismos que producen la curva plana

No es magia. Son cuatro decisiones estructurales:

1. **El indice nunca entra al contexto.** El mapa del proyecto (simbolos,
   referencias, resumenes) vive en SQLite y en el LSP. El modelo lo *consulta*
   mediante herramientas; nunca lo recibe completo. Volcar el grafo al prompt
   devuelve el sistema a `O(N)` -- es el modo de fallo tipico del "segundo
   cerebro" con grafo bonito.
2. **El retrieval devuelve simbolos, no archivos.** La funcion pedida y sus
   referencias directas, no el archivo de 900 lineas que la contiene.
3. **Resumenes jerarquicos calculados una vez** por el tier local, persistidos e
   invalidados por hash de contenido. El tamano del repo encarece la
   *indexacion* (local, sin costo monetario), no la tarea.
4. **Presupuesto de contexto duro.** El agente opera con un techo fijo de tokens.
   Para incorporar contexto nuevo debe desalojar contexto viejo. Esto fuerza el
   comportamiento acotado por construccion, no por esperanza.

## 4. Los limites que declaramos

Hay tareas genuinamente `O(N)`: renombrar en todo el codigo, auditar cada query,
describir la arquitectura completa. Tocan todo por definicion.

Para esas, el ahorro viene de que **el barrido lo ejecuta el tier local** y solo
los hallazgos escalan al modelo remoto. Los tokens remotos crecen con la cantidad
de *hallazgos*, no con el tamano del repositorio -- pero crecen. Se reportan en
una categoria separada y no se promedian con las tareas localizadas.

## 5. Reglas de medicion

- **Toda** llamada a un modelo queda en el ledger. Una llamada sin registrar
  invalida la corrida completa.
- **Calidad y costo se reportan juntos, siempre.** Ahorrar tokens fallando la
  tarea no es ahorro. Toda tarea tiene una puerta de correctitud objetiva.
- **Los modos de facturacion no se mezclan.** `api` (dolares reales),
  `subscription` (cuota fija: se mide en tokens, no en dolares) y `local` (sin
  costo monetario) se reportan por separado. Sumarlos produciria un numero sin
  significado.
- **Nunca se inventa una tarifa.** Modelo sin tarifa conocida -> costo `NULL` y
  el reporte declara cuantas llamadas quedaron sin tarificar.
- **La linea base se publica.** Es codigo del repositorio, ejecutable por
  cualquiera. Comparar contra una linea base secreta es la definicion de humo.

## 6. Lo que NO afirmamos

- Que sea "local" cuando usa una API remota. Si el dato salio de la maquina,
  salio. El log de egress lo registra.
- Que el debate entre agentes ahorre tokens. Es un multiplicador de costo; entra
  solo cuando la medicion demuestra que cambia el resultado.
- Que los subagentes reduzcan el consumo total. Reducen el del hilo principal;
  el total puede subir. Se mide de punta a punta.
