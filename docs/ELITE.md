# Camino a elite: que es 100% en cada apartado

`PENDIENTES.md` dice que falta para que lymi este **operativo**. Este documento
dice que falta para que sea **bueno de verdad** en cada eje, con un criterio que
se pueda comprobar: una puerta, no una sensacion.

Dos reglas que valen para todo el documento:

1. **Un apartado esta al 100% cuando su puerta pasa**, no cuando "ya se siente
   bien". Si un eje no tiene puerta medible, la primera tarea es inventarsela.
2. **Mientras mas cerca del 100%, mas sube la vara.** Estos criterios son los de
   hoy; cuando se cumplan, se escriben los siguientes.

Orden sugerido al final del documento.

---

## 1. Cerebro (el modelo que razona)

Hoy: el cuello de botella. El local de 3B acierta 3/10 en el eval de codigo; el
remoto por suscripcion comparte cuota con el trabajo del usuario.

- [ ] Medir el remoto con `lymi agencia evaluar --remoto` y publicar la cifra.
- [ ] Recortar el prefijo fijo de `claude -p` (~19k tokens por llamada): probar
      que opciones evitan cargar prompt de sistema, herramientas y MCP, y medirlo.
- [ ] Probar una API por token (Haiku) como cerebro de agentes, con tope por
      corrida y costo real en el ledger.
- [ ] Router de tier medido: que cada tipo de paso elija local o remoto por
      evidencia, no por intuicion.
- [ ] Reserva de cuota: lymi se detiene antes de dejarte sin modelo para ti.

**Puerta:** ≥90% de aciertos en el eval de codigo (10 preguntas) con costo por
tarea conocido y dentro del tope que fije el usuario.

## 2. Seguridad y auditoria

Hoy lo mas fuerte del proyecto: ejecutor sin shell, capacidades por ruta, diario
de deshacer, pasarela de egress, parada, aprobaciones, todo en el ledger.

- [ ] Sandbox del sistema operativo bajo el ejecutor (Windows Sandbox o
      contenedor): que la frontera la ponga el kernel, no solo nuestra lista.
- [ ] Tecla global de parada (funciona aunque la terminal no tenga el foco).
- [ ] Ledger encadenado por hash: detectar si alguien edito el historial.
- [ ] Exportar una auditoria presentable (PDF/HTML) de un periodo.
- [ ] Permisos por sesion: "hoy puede escribir en este proyecto y nada mas".

**Puerta:** la suite destructiva pasa tambien con el sandbox activo, y un intento
de alterar el ledger se detecta automaticamente.

## 3. Motor de agentes

Hoy: departamentos, delegacion sincrona y paralela, ayudantes, topes, citas
verificadas. Falta verlo y dirigirlo.

- [ ] Arbol de tareas en vivo en `lymi ui`, con aprobar y detener desde ahi.
- [ ] `foreach` en workflows (con tope de iteraciones y presupuesto compartido).
- [ ] Lienzo tipo n8n sobre el YAML, ida y vuelta sin perder comentarios.
- [ ] Reanudar una corrida interrumpida (hoy se cancela el arbol y se pierde).
- [ ] Evaluacion continua: el eval corre en CI y avisa si un cambio empeora.

**Puerta:** una tarea real de varios pasos se sigue, se aprueba y se corrige
desde la app sin tocar la terminal.

## 4. Actuar en el PC

Hoy: seis operaciones cerradas sobre archivos y comandos de lista blanca, con
diario y deshacer.

- [ ] Ventanas y aplicaciones por **arbol de accesibilidad**, no por capturas ni
      por posiciones de pantalla: leer lo que hay, pulsar por nombre de control.
- [ ] Portapapeles como entrada y salida (con etiquetas de sensibilidad).
- [ ] Automatizaciones de escritorio con vista previa y deshacer.
- [ ] Presupuesto de acciones por corrida, no solo de archivos.

**Puerta:** completar una tarea real en una app de escritorio con aprobacion por
accion y poder deshacer todo lo reversible.

## 5. Web

Hoy: pagina a markdown, mapa de sitio, investigacion con citas verificadas,
guardia SSRF.

- [ ] Navegador propio por CDP contra el Chrome/Edge instalado, con **perfil
      temporal aislado** (sin tus cookies ni tus sesiones).
- [ ] Formularios y descargas con aprobacion explicita.
- [ ] Cache de paginas por corrida y entre corridas, con ahorro medido.
- [ ] Buscador propio probado contra un SearXNG real.

**Puerta:** leer y operar una pagina que hoy falla (JavaScript) sin usar tu
sesion iniciada, y medir cuanto contexto se ahorro.

## 6. Memoria

Hoy: afirmaciones de agentes, hechos promovidos por una persona, busqueda lexica
con `ruta:linea` citable.

- [ ] Busqueda por significado (embeddings locales) sin perder la cita.
- [ ] Diario de sesion automatico: que aprendio lymi al cerrar cada corrida.
- [ ] Decaimiento y olvido con motivo (nada desaparece en silencio).
- [ ] Espejo bidireccional con Obsidian: si editas la nota, gana tu version.
- [ ] Deteccion de contradicciones entre hechos.

**Puerta:** una sesion nueva responde correctamente preguntas sobre decisiones de
hace semanas, citando la nota exacta.

## 7. Proactividad

Hoy: agenda, webhooks y el resumen diario, verificados de punta a punta.

- [ ] `lymi serve` arranca con el sistema (tarea programada de Windows).
- [ ] Avisos al celular cuando algo termina o requiere tu decision.
- [ ] Disparadores por evento: correo nuevo importante, archivo que aparece,
      commit que falla.
- [ ] "No molestar": ventanas horarias y silencio configurable.
- [ ] Cola de decisiones pendientes con vencimiento (lo que espera por ti).

**Puerta:** durante una semana, lymi produce algo util sin que se lo pidas y sin
molestarte cuando no corresponde.

## 8. Integraciones diarias

Hoy: correo local de Thunderbird (solo lectura, con borradores).

- [ ] Calendario: eventos del dia en el resumen.
- [ ] Tareas y notas (Obsidian primero; Notion despues, de solo lectura).
- [ ] Mensajeria (WhatsApp/Telegram) de solo lectura y con borradores.
- [ ] Archivos y descargas: ordenar, renombrar y archivar con deshacer.
- [ ] Cada integracion con su prueba contra el servicio real.

**Puerta:** el informe de la manana junta correo, calendario y tareas sin que
tengas que abrir nada.

## 9. Voz

Hoy: 0%.

- [ ] Dictado local con `whisper.cpp` (modelo elegido segun tu hardware y
      **siempre declarado**, nunca cambiado en silencio).
- [ ] Respuesta hablada (primero con las voces que ya trae el sistema).
- [ ] Atajo global para hablar; nada de microfono siempre abierto salvo que tu
      lo actives a proposito.
- [ ] Transcripciones tratadas como texto sensible (etiquetas y pasarela).

**Puerta:** una orden hablada completa una tarea real de punta a punta sin que el
audio salga de la maquina.

## 10. Hardware y entorno

El eje nuevo: si no controla el mundo fisico, no es un Jarvis. Todo local-first:
sin nubes de fabricantes salvo que lo elijas.

- [ ] **Puente de casa**: Home Assistant local (o MQTT directo) como unico punto
      de contacto. lymi no habla con cada marca, habla con el puente.
- [ ] **Luces, enchufes y sensores** por Zigbee/Matter/ESPHome; estado y control.
- [ ] **Impresora 3D**: Klipper/Moonraker u OctoPrint. Leer estado, temperaturas
      y progreso; iniciar, pausar y **cancelar** con aprobacion.
- [ ] **Impresora de papel**: imprimir un documento con vista previa y tope de
      paginas.
- [ ] **Camaras locales**: ver una instantanea bajo peticion; nunca grabacion
      continua ni analisis en la nube.
- [ ] **Audio del entorno**: altavoces para avisos hablados.

Reglas propias de este eje, que no existen en lo digital:

- **Un efecto fisico siempre pide aprobacion.** No hay "preaprobado" por defecto:
  un archivo se deshace, un carrete quemado no.
- **Topes duros por dispositivo**: temperatura maxima, paginas por trabajo,
  horario permitido (nada de encender la impresora a las 3 AM).
- **La parada apaga.** `lymi stop` debe cortar trabajos en curso y dejar los
  dispositivos en estado seguro.
- **La red local se declara**: la guardia de red bloquea direcciones privadas por
  diseno; cada puente se permite por host explicito, como `allow_hosts` en los
  pasos HTTP, y queda en el ledger.
- **Sin telemetria del fabricante**: si un dispositivo exige nube, se documenta
  como tal y se decide aparte.

**Puerta:** una orden ("apaga las luces del taller y pausa la impresion") se
ejecuta con aprobacion, queda en el ledger y `lymi stop` la revierte o la detiene
dejando todo seguro.

## 10b. Vista (camara)

Que pueda **mirar** y ayudar con lo que tienes delante: leer una etiqueta, decir
si una pieza quedo bien montada, comparar un montaje con su plano, vigilar una
impresion 3D. Sin esto, "ver" queda solo en la pantalla.

- [ ] Instantanea bajo peticion desde una camara (USB o de red local).
- [ ] Modelo de vision **local** primero (Ollama ya sirve modelos con vision);
      el remoto solo si tu lo pides, porque una foto no se puede redactar.
- [ ] Preguntar sobre lo que se ve ("¿que dice esta etiqueta?", "¿esta derecha?").
- [ ] Vigilancia puntual con condicion de corte ("avisame si la impresion falla",
      con tope de tiempo y de fotos).
- [ ] Las imagenes se tratan como dato sensible: etiqueta `nunca-sale` por defecto
      y cada envio a un modelo remoto pide aprobacion, foto por foto.

Reglas propias:

- **Nada de grabacion continua.** Una foto se toma cuando tu lo pides o cuando lo
  pide una tarea que aprobaste, y queda en el ledger con su motivo.
- **La camara tiene interruptor.** `lymi stop` la apaga; si el sistema operativo
  muestra el indicador de camara, que se vea cuando lymi la usa.
- **Una foto no se puede redactar.** La pasarela puede tapar un correo o una
  clave en un texto; en una imagen no. Por eso el tier remoto es opt-in explicito.

**Puerta:** responder correctamente tres preguntas sobre objetos reales frente a
la camara, con el modelo local, y que cada captura aparezca en el ledger.

## 11. Interfaz

Hoy: app local con ledger, proveedores, workflows y egress.

- [ ] Agencia, correo y memoria en la app.
- [ ] Cola de aprobaciones con vencimiento y contexto.
- [ ] Acceso desde el celular (PWA en tu red, con el mismo token).
- [ ] Accesibilidad: teclado completo y lectores de pantalla.

**Puerta:** un dia entero de uso sin abrir la terminal.

## 12. Distribucion

- [ ] Instalador para Windows, macOS y Linux.
- [ ] Primer arranque guiado: detecta hardware, propone modelos, prueba todo.
- [ ] Actualizacion sin romper el ledger ni la memoria.
- [ ] Manual para los tres caminos: estudiante (solo local), suscripcion, API.

**Puerta:** alguien que no programa lo instala y consigue su primer resultado
util en menos de quince minutos.

## 13. Medicion y calidad

- [ ] Publicar la curva de escalamiento con el recibo reproducible.
- [ ] CI con las pruebas destructivas y el eval de agentes.
- [ ] `--repeticiones N` con mediana en el bench.
- [ ] Cobertura por modulo y presupuesto de rendimiento.

**Puerta:** cualquiera puede reproducir las cifras del README en su maquina.

---

## Orden sugerido

1. **Cerebro** (barato de medir, desbloquea todo lo demas).
2. **Voz** (lo que hace que se sienta un Jarvis; riesgo bajo, todo local).
3. **Proactividad** (arranque con el sistema y avisos: ya casi esta).
4. **Calendario y tareas** (completan el informe de la manana).
5. **Interfaz** (verlo trabajar; la agencia ya existe).
6. **Hardware y entorno** (empezar por luces con Home Assistant: lectura primero,
   control despues).
7. **Navegador propio** y **control de ventanas** (lo mas caro).
8. **Sandbox del sistema** y **distribucion** (antes de que lo use alguien mas).
