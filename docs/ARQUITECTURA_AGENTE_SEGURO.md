# Arquitectura del agente seguro: los tres riesgos del control del PC

Los agentes con control del PC arrastran tres riesgos, y por eso es comun
aislarlos en una maquina desechable. lymi no puede ser un asistente de escritorio
util hasta que los tres esten resueltos **en la maquina del usuario**.

Estado: **diseno**. Nada de esto esta implementado todavia salvo lo marcado.

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
2. **Ejecutor del host separado.** Proceso pequeno con una API RPC estrecha: una
   lista cerrada de operaciones (`leer`, `escribir`, `ejecutar`, `ui`), cada una
   con parametros validados. El modelo nunca obtiene un shell.
3. **Capacidades por ruta.** Lista blanca de directorios escribibles por perfil.
   Denegacion fija de rutas del sistema (`C:\Windows`, `Program Files`, registro,
   `%APPDATA%` ajeno, `.ssh`, gestores de claves) aunque la politica diga otra cosa.
4. **Diario de deshacer.** Antes de modificar o borrar, copia del original a
   `runs/diario/<corrida>/`. Borrar = mover al diario, nunca eliminar. Comando
   `lymi undo <corrida>`.
5. **Codigo en worktrees.** Cambios en repositorios van a un `git worktree`
   aislado (patron de orca); se integran solo tras aprobar el diff.
6. **Ejecucion no confiable en sandbox.** Codigo generado corre en un contenedor o
   Windows Sandbox sin red por defecto, con limites de CPU, memoria y tiempo.
7. **Interruptor de parada.** Tecla global y `lymi stop` que cancelan toda corrida
   en curso y revocan aprobaciones pendientes.
8. **Presupuestos.** Tope de acciones, archivos tocados y tokens por tarea; al
   excederse, se detiene y pregunta.

**Puerta:** una suite de pruebas "destructivas" (borrar una carpeta, sobrescribir
un archivo, `rm -rf`, editar el registro) donde cada caso termina bloqueado o
deshecho sin perdida.

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
