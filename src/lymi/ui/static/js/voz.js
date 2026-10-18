// Voz: dictar con el microfono (whisper.cpp en tu maquina) y escuchar las respuestas
// con la voz del sistema. El audio se convierte a WAV de 16 kHz aqui mismo y solo
// viaja a lymi en 127.0.0.1; se borra apenas se transcribe.

import { TOKEN, api, aviso, guardado, guardar, h, icono } from './base.js';

const MAX_SEGUNDOS = 120;
let estadoCache = null;

export async function estadoVoz(refrescar = false) {
  if (!estadoCache || refrescar) {
    try { estadoCache = await api('voz'); } catch { estadoCache = { dictado: { disponible: false, motivo: 'sin conexión' }, lectura: { disponible: false } }; }
  }
  return estadoCache;
}

function wav(muestras, tasaOrigen) {
  // Reduce a 16 kHz mono (lo que pide whisper) y escribe PCM de 16 bits.
  const tasa = 16000;
  const factor = tasaOrigen / tasa;
  const largo = Math.floor(muestras.length / factor);
  const datos = new DataView(new ArrayBuffer(44 + largo * 2));
  const texto = (pos, s) => { for (let i = 0; i < s.length; i += 1) datos.setUint8(pos + i, s.charCodeAt(i)); };
  texto(0, 'RIFF'); datos.setUint32(4, 36 + largo * 2, true); texto(8, 'WAVE'); texto(12, 'fmt ');
  datos.setUint32(16, 16, true); datos.setUint16(20, 1, true); datos.setUint16(22, 1, true);
  datos.setUint32(24, tasa, true); datos.setUint32(28, tasa * 2, true); datos.setUint16(32, 2, true); datos.setUint16(34, 16, true);
  texto(36, 'data'); datos.setUint32(40, largo * 2, true);
  for (let i = 0; i < largo; i += 1) {
    const inicio = Math.floor(i * factor);
    const fin = Math.min(Math.floor((i + 1) * factor), muestras.length);
    let suma = 0;
    for (let j = inicio; j < fin; j += 1) suma += muestras[j];
    const v = Math.max(-1, Math.min(1, suma / Math.max(1, fin - inicio)));
    datos.setInt16(44 + i * 2, v < 0 ? v * 0x8000 : v * 0x7fff, true);
  }
  return new Blob([datos], { type: 'audio/wav' });
}

// Boton de microfono para un textarea: clic para grabar, clic para terminar.
export function botonMicrofono(area, mensaje) {
  const boton = h('button', { type: 'button', class: 'boton icono-solo fantasma', title: 'Dictar (whisper.cpp, en tu equipo)', 'aria-label': 'Dictar' }, icono('microfono'));
  let grabacion = null;

  async function empezar() {
    const e = await estadoVoz(true);
    if (!e.dictado.disponible) {
      mensaje.replaceChildren(aviso(`${e.dictado.motivo.charAt(0).toUpperCase()}${e.dictado.motivo.slice(1)}. Para esta máquina (${e.dictado.memoria_gb} GB) conviene ${e.dictado.sugerido}.`, 'info'));
      return;
    }
    let flujo;
    try {
      flujo = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
    } catch (err) {
      mensaje.replaceChildren(aviso(`No se pudo usar el micrófono: ${err.message}`, 'error'));
      return;
    }
    const contexto = new AudioContext();
    const fuente = contexto.createMediaStreamSource(flujo);
    const proceso = contexto.createScriptProcessor(4096, 1, 1);
    const trozos = [];
    proceso.onaudioprocess = (ev) => trozos.push(new Float32Array(ev.inputBuffer.getChannelData(0)));
    fuente.connect(proceso);
    proceso.connect(contexto.destination);
    const inicio = Date.now();
    const reloj = setInterval(() => {
      const s = Math.round((Date.now() - inicio) / 1000);
      boton.title = `Grabando ${s} s: clic para terminar`;
      boton.dataset.segundos = String(s);
      if (s >= MAX_SEGUNDOS) terminar();
    }, 500);
    grabacion = { flujo, contexto, proceso, fuente, trozos, reloj };
    boton.classList.add('grabando');
    boton.setAttribute('aria-label', 'Terminar el dictado');
    mensaje.replaceChildren(h('div', { class: 'aviso info' }, icono('microfono'), 'Grabando. Clic otra vez para terminar. El audio no sale de tu equipo.'));
  }

  async function terminar() {
    const g = grabacion;
    if (!g) return;
    grabacion = null;
    clearInterval(g.reloj);
    g.proceso.disconnect(); g.fuente.disconnect();
    g.flujo.getTracks().forEach((t) => t.stop());
    const tasa = g.contexto.sampleRate;
    await g.contexto.close();
    boton.classList.remove('grabando');
    boton.setAttribute('aria-label', 'Dictar');
    const total = g.trozos.reduce((n, t) => n + t.length, 0);
    const muestras = new Float32Array(total);
    let pos = 0;
    for (const t of g.trozos) { muestras.set(t, pos); pos += t.length; }
    mensaje.replaceChildren(h('div', { class: 'aviso info' }, 'Transcribiendo en tu equipo…'));
    boton.disabled = true;
    try {
      const respuesta = await fetch('/api/voz/transcribir?idioma=es', {
        method: 'POST', headers: { 'X-Lymi-Token': TOKEN, 'Content-Type': 'audio/wav' }, body: wav(muestras, tasa),
      });
      const r = await respuesta.json();
      if (!respuesta.ok) throw new Error(r.error || `error ${respuesta.status}`);
      const antes = area.value && !area.value.endsWith(' ') ? `${area.value} ` : area.value;
      area.value = `${antes}${r.texto}`.trim();
      area.dispatchEvent(new Event('input'));
      area.focus();
      mensaje.replaceChildren(h('div', { class: 'chico tenue' }, `Dictado con whisper ${r.modelo} en ${r.segundos} s, sin salir de tu equipo.`));
    } catch (err) {
      mensaje.replaceChildren(aviso(err.message, 'error'));
    } finally {
      boton.disabled = false;
    }
  }

  boton.addEventListener('click', () => (grabacion ? terminar() : empezar()));
  return boton;
}

export async function leer(texto) {
  await api('voz/hablar', { metodo: 'POST', cuerpo: { texto } });
}

export async function callar() {
  await api('voz/callar', { metodo: 'POST', cuerpo: {} });
}

export const leerRespuestas = () => guardado('voz:leer', false);

export function interruptorLectura() {
  const casilla = h('input', { type: 'checkbox', checked: leerRespuestas() ? true : null });
  casilla.addEventListener('change', () => { guardar('voz:leer', casilla.checked); if (!casilla.checked) callar(); });
  return h('label', { class: 'casilla chico', title: 'Leer las respuestas con la voz del sistema' }, casilla, icono('altavoz'), 'Leer en voz alta');
}
