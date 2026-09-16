# Arquitectura del agente seguro: los tres riesgos del control del PC

Los agentes con control del PC arrastran tres riesgos, y por eso es comun
aislarlos en una maquina desechable. lymi no puede ser un asistente de escritorio
util hasta que los tres esten resueltos **en la maquina del usuario**.

Estado al 2026-09-14:

- **Fallo 3, capas 3-5: implementado.** Pasarela en `bench/runner.Recorder`:
  saneamiento de Unicode, redaccion reversible, bloqueo de claves privadas y de
  contenido `nunca-sale`, egress registrado con el hash de lo que de verdad salio.
  Etiquetas por ruta en `privacidad/etiquetas.py`. Falta la capa 6 (retencion).
- **Fallo 1, capas 1, 7 y 8: parcial.** Plan/apply en workflows; parada por archivo
  (`lymi stop`) y presupuestos de tokens y llamadas. Faltan ejecutor, diario de
  deshacer, capacidades por ruta, worktrees y sandbox.
- **Fallo 2: pendiente.**

---

## Fallo 1: rompe el sistema

**Causa:** el agente ejecuta comandos y edita archivos con los permisos del
usuario, sin frontera, sin vista previa y sin forma de volver atras.

**Principio:** el agente nunca actua sobre el sistema directamente. Propone; un
ejecutor acotado aplica; todo se puede deshacer.

### Capas

1. **Plan / apply.** Cada accion con efectos se describe primero como plan
   (archivos, comandos, destino). El usuario o una politica lo aprueba. Ya existe
   para workflows: pasos con efectos piden aprobacion y no se reintentan.
2. **Ejecutor del host separado.** [hecho: `src/lymi/ejecutor/`] Lista cerrada de
   seis operaciones (`leer`, `listar`, `escribir`, `mover`, `borrar`, `ejecutar`),
   cada una con parametros validados. El modelo nunca obtiene un shell: los
   interpretes (cmd, powershell, bash, wsl...) y los `.bat`/`.cmd` se rechazan al
   cargar el perfil o al ejecutar, el proceso corre con `shell=False`, sin stdin y
   con un entorno minimo (las claves de API de lymi no le llegan).
3. **Capacidades por ruta.** [hecho: `ejecutor/capacidades.py`, `ejecutor.example.yml`]
   Lista blanca de directorios legibles y escribibles por perfil; por defecto solo
   `./salidas`. Denegacion fija de rutas del sistema (`C:\Windows`, `Program Files`,
   `%APPDATA%\Microsoft`, `.ssh`, `.aws`, `.gnupg`...) y tambien de `runs/` y `.git`:
   el agente no reescribe su propia auditoria. Las rutas se resuelven antes de
   juzgarlas (un enlace simbolico se juzga por su destino) y se rechazan las formas
   que esquivan una comparacion de prefijos: rutas de red (UNC), flujos alternativos
   de NTFS (`archivo:oculto`) y nombres de dispositivo (`CON`, `NUL`).
4. **Diario de deshacer.** [hecho: `ejecutor/diario.py`] Antes de modificar o
   borrar, copia del original a `runs/diario/<corrida>/`. Borrar = mover al diario,
   nunca eliminar; lo que se quita al deshacer tambien se guarda. `lymi undo
   <corrida>` revierte en orden inverso y no se puede aplicar dos veces. Un comando
   no se deshace, pero queda anotado con su codigo de salida.
5. **Codigo en worktrees.** Cambios en repositorios van a un `git worktree`
   aislado (patron de orca); se integran solo tras aprobar el diff.
6. **Ejecucion no confiable en sandbox.** Codigo generado corre en un contenedor o
   Windows Sandbox sin red por defecto, con limites de CPU, memoria y tiempo.
7. **Interruptor de parada.** Tecla global y `lymi stop` que cancelan toda corrida
   en curso y revocan aprobaciones pendientes.
8. **Presupuestos.** [hecho] Tope de tokens y llamadas (`control.Presupuesto`) y
   de archivos distintos tocados por corrida (`max_archivos` del perfil).

**Puerta:** una suite de pruebas "destructivas" (borrar una carpeta, sobrescribir
un archivo, `rm -rf`, editar el registro) donde cada caso termina bloqueado o
deshecho sin perdida. **Cumplida** en `tests/test_ejecutor.py` y
`tests/test_pc_flujo.py`: escribir en `C:\Windows` o en `~/.ssh` con el perfil mas
permisivo posible, salir de la carpeta con `..`, seguir un enlace hacia afuera,
pedir un shell, correr un `.cmd`, y sobrescribir/borrar/mover con `lymi undo`
devolviendo cada byte. Falta la capa de sandbox del sistema operativo (punto 6):
hoy la frontera es la lista blanca, no el kernel.

---

## Fallo 2: amnesia

**Causa:** la memoria vive dentro de la ventana de contexto. Al compactar o abrir
otra sesion, se pierde.

**Principio:** el estado vive fuera del modelo, en archivos que sobreviven a
cualquier sesion y que una persona puede leer y corregir.

### Capas

1. **Memoria en markdown plano** con wikilinks y frontmatter, en una carpeta que
   Obsidian o Logseq abren sin conversion. Patron LLM Wiki: fuentes crudas
   inmutables, wiki mantenido por el agente, `index.md` y `log.md`.
2. **Escritura por el modelo local.** Resumir y archivar recuerdos corre gratis en
   la GPU; al modelo caro solo llega lo recuperado.
3. **Recuperacion acotada.** Se consulta el indice y se traen las paginas
   relevantes dentro de un presupuesto fijo; la memoria nunca se vuelca entera.
4. **Diario de sesion.** Cada sesion anota decisiones, estado de hilos y proximo
   paso. Una sesion nueva lo lee primero (este repositorio ya lo hace a mano:
   `CLAUDE.md` → `CONTEXTO.md` → `PENDIENTES.md` → `BITACORA.md`).
5. **Procedencia.** Cada recuerdo apunta a su fuente y fecha; los contradictorios
   se marcan en vez de sobrescribirse.

**Puerta:** tras borrar el contexto, el agente responde correctamente preguntas
sobre decisiones de sesiones anteriores, citando la pagina.

---

## Fallo 3: tus datos los lee la API

**Causa:** con un modelo remoto, todo lo que entra al contexto viaja al proveedor.
"Local" es solo el disco.

**Principio:** decidir por dato, antes de que salga, si puede salir.

### Capas

1. **Etiquetas de sensibilidad** por carpeta y archivo: `publico`, `interno`,
   `confidencial`, `nunca-sale`. Por defecto, lo personal es `confidencial`.
2. **El modelo local lee lo sensible.** Lo confidencial se procesa en la GPU; al
   remoto solo llega un extracto destilado y redactado, o nada.
3. **Gateway de egress unico.** Un solo proceso habla con proveedores y
   integraciones. Aplica politica por destino, bloquea `nunca-sale`, y registra
   destino y hash. Ya existe el registro por hash; faltan bloqueo y redaccion.
4. **Redaccion reversible.** Secretos, PII e identificadores se reemplazan por
   marcadores antes de salir y se rehidratan al volver.
5. **Saneamiento de entrada.** Quitar Unicode invisible y control bidireccional
   (inyeccion escondida, hallazgo de ECC) antes de que un documento llegue al modelo.
6. **Retencion minima.** Preferir proveedores con retencion cero para lo `interno`;
   decir con claridad que retencion cero no es lo mismo que local.

**Puerta:** un informe de egress de una semana donde ningun archivo `confidencial`
aparece como enviado, verificable por hash.

---

## Orden de construccion

1. Saneamiento de entrada + etiquetas + bloqueo en el gateway (fallo 3, reutiliza
   el ledger existente).
2. Memoria markdown + diario de sesion + recuperacion acotada (fallo 2).
3. Ejecutor del host + diario de deshacer + capacidades por ruta (fallo 1).
4. Sandbox y worktrees.
5. Recien entonces: control del PC y el Jarvis.
