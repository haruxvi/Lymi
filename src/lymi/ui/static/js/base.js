// Piezas compartidas de la interfaz. Sin dependencias ni red: todo sale de la API local.
//
// Regla de seguridad: ningun dato entra al DOM como HTML. Todo pasa por h(), que crea
// nodos de texto; ni un asunto de correo ni la respuesta de un modelo pueden inyectar
// marcado. El markdown de las respuestas se convierte a nodos, nunca a innerHTML.

export const TOKEN = document.querySelector('meta[name="lymi-token"]')?.content ?? '';
export const ACTIVOS = new Set(['en_curso', 'esperando']);

// ------------------------------------------------------------------ nodos

export function h(tag, attrs, ...hijos) {
  const el = document.createElement(tag);
  for (const [clave, valor] of Object.entries(attrs || {})) {
    if (valor === null || valor === undefined || valor === false) continue;
    if (clave === 'class') el.className = valor;
    else if (clave === 'style') Object.assign(el.style, valor);
    else if (clave === 'dataset') Object.assign(el.dataset, valor);
    else if (clave.startsWith('on') && typeof valor === 'function') el.addEventListener(clave.slice(2), valor);
    else if (clave === 'value') el.value = valor;
    else el.setAttribute(clave, valor === true ? '' : String(valor));
  }
  for (const hijo of nodos(hijos)) el.append(hijo instanceof Node ? hijo : document.createTextNode(String(hijo)));
  return el;
}

export function nodos(...valores) {
  return valores.flat(Infinity).filter((v) => v !== null && v !== undefined && v !== false);
}

const SVG = 'http://www.w3.org/2000/svg';

// Iconos propios, trazos simples de 24x24.
const TRAZOS = {
  hoy: ['M12 4v2', 'M12 18v2', 'M4 12h2', 'M18 12h2', 'M6.3 6.3l1.4 1.4', 'M16.3 16.3l1.4 1.4', 'M6.3 17.7l1.4-1.4', 'M16.3 7.7l1.4-1.4', 'C12 12 4'],
  chat: ['M5 5h14a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1h-8l-4 3v-3H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1z'],
  correo: ['M4 6h16v12H4z', 'M4 7l8 6 8-6'],
  calendario: ['M5 6h14v13H5z', 'M5 10h14', 'M9 4v4', 'M15 4v4'],
  agencia: ['C9 8 3', 'M3.5 19a5.5 5.5 0 0 1 11 0', 'C17 9 2.5', 'M15.5 14.2A4.5 4.5 0 0 1 21 19'],
  memoria: ['M6 4h12v16l-6-4-6 4z'],
  workflows: ['M4 6h5v4H4z', 'M15 14h5v4h-5z', 'M9 8h3a2 2 0 0 1 2 2v4a2 2 0 0 0 2 2'],
  reloj: ['C12 12 8', 'M12 8v4l3 2'],
  codigo: ['M9 7l-5 5 5 5', 'M15 7l5 5-5 5'],
  web: ['C12 12 8', 'M4 12h16', 'M12 4c3 3 3 13 0 16', 'M12 4c-3 3-3 13 0 16'],
  equipo: ['M4 5h16v11H4z', 'M9 20h6', 'M12 16v4'],
  corridas: ['M8 6h12', 'M8 12h12', 'M8 18h12', 'M4 6h.01', 'M4 12h.01', 'M4 18h.01'],
  salida: ['M14 4h6v6', 'M20 4l-9 9', 'M18 14v5H5V6h5'],
  medir: ['M4 18a8 8 0 1 1 16 0', 'M12 18l4-6'],
  chip: ['M7 7h10v10H7z', 'M10 4v3', 'M14 4v3', 'M10 17v3', 'M14 17v3', 'M4 10h3', 'M4 14h3', 'M17 10h3', 'M17 14h3'],
  paleta: ['M12 4a8 8 0 1 0 0 16c1 0 1.5-.8 1.2-1.7-.4-1 .3-2.3 1.5-2.3H17a3 3 0 0 0 3-3c0-5-3.6-9-8-9z', 'C8 10 1', 'C12 8 1', 'C16 10 1'],
  enviar: ['M12 19V5', 'M6 11l6-6 6 6'],
  mas: ['M12 5v14', 'M5 12h14'],
  basura: ['M5 7h14', 'M10 7V5h4v2', 'M7 7l1 12h8l1-12'],
  check: ['M5 12l4 4 10-10'],
  cruz: ['M6 6l12 12', 'M18 6L6 18'],
  alerta: ['M12 4l9 16H3z', 'M12 10v4', 'M12 17h.01'],
  play: ['M8 5l11 7-11 7z'],
  guardar: ['M5 4h11l3 3v13H5z', 'M8 4v5h7V4', 'M8 20v-6h8v6'],
  deshacer: ['M9 7L4 12l5 5', 'M4 12h10a5 5 0 0 1 0 10h-3'],
  lupa: ['C11 11 6', 'M20 20l-4.5-4.5'],
  archivo: ['M7 4h7l4 4v12H7z', 'M14 4v4h4'],
  rayo: ['M13 3L5 14h6l-1 7 8-11h-6z'],
  pausa: ['M9 6v12', 'M15 6v12'],
  modelo: ['M12 3l8 4.5v9L12 21l-8-4.5v-9z', 'M12 12l8-4.5', 'M12 12v9', 'M12 12L4 7.5'],
  red: ['C6 12 2', 'C18 6 2', 'C18 18 2', 'M8 11l8-4', 'M8 13l8 4'],
  pc: ['M4 5h16v11H4z', 'M9 20h6', 'M12 16v4'],
  logica: ['M6 4v16', 'M6 8h8l4 4-4 4H6'],
  ojo: ['M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z', 'C12 12 3'],
  ajustes: ['C12 12 3', 'M12 3v3', 'M12 18v3', 'M3 12h3', 'M18 12h3', 'M5.6 5.6l2.1 2.1', 'M16.3 16.3l2.1 2.1', 'M5.6 18.4l2.1-2.1', 'M16.3 7.7l2.1-2.1'],
  escudo: ['M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z'],
  zoommas: ['C11 11 6', 'M20 20l-4.5-4.5', 'M11 8v6', 'M8 11h6'],
  zoommenos: ['C11 11 6', 'M20 20l-4.5-4.5', 'M8 11h6'],
  centrar: ['M4 9V4h5', 'M15 4h5v5', 'M20 15v5h-5', 'M9 20H4v-5'],
  microfono: ['M9 5a3 3 0 0 1 6 0v6a3 3 0 0 1-6 0z', 'M5 11a7 7 0 0 0 14 0', 'M12 18v3'],
  altavoz: ['M4 9h4l5-4v14l-5-4H4z', 'M16 9a4 4 0 0 1 0 6', 'M18.5 6.5a7.5 7.5 0 0 1 0 11'],
};

export function icono(nombre, clase = 'icono') {
  const svg = document.createElementNS(SVG, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', '1.8');
  svg.setAttribute('stroke-linecap', 'round');
  svg.setAttribute('stroke-linejoin', 'round');
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('class', clase);
  for (const trazo of TRAZOS[nombre] || []) {
    if (trazo.startsWith('C')) {
      const [cx, cy, r] = trazo.slice(1).trim().split(' ');
      const c = document.createElementNS(SVG, 'circle');
      c.setAttribute('cx', cx); c.setAttribute('cy', cy); c.setAttribute('r', r);
      svg.append(c);
    } else {
      const p = document.createElementNS(SVG, 'path');
      p.setAttribute('d', trazo);
      svg.append(p);
    }
  }
  return svg;
}

export function svg(tag, attrs = {}) {
  const el = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, String(v));
  return el;
}

// ------------------------------------------------------------------ api

export async function api(ruta, { metodo = 'GET', cuerpo } = {}) {
  const cabeceras = { 'X-Lymi-Token': TOKEN };
  if (cuerpo !== undefined) cabeceras['Content-Type'] = 'application/json';
  const respuesta = await fetch(`/api/${ruta}`, {
    method: metodo, headers: cabeceras, cache: 'no-store',
    body: cuerpo === undefined ? undefined : JSON.stringify(cuerpo),
  });
  let datos = null;
  try { datos = await respuesta.json(); } catch { /* sin JSON: el mensaje usa el codigo */ }
  if (!respuesta.ok) throw new Error(datos?.error || `error ${respuesta.status}`);
  return datos;
}

export const qs = (params) => new URLSearchParams(Object.entries(params).filter(([, v]) => v !== null && v !== undefined && v !== '')).toString();

export function guardado(clave, defecto) {
  try { const v = localStorage.getItem(`lymi:${clave}`); return v === null ? defecto : JSON.parse(v); } catch { return defecto; }
}
export function guardar(clave, valor) {
  try { localStorage.setItem(`lymi:${clave}`, JSON.stringify(valor)); } catch { /* sin almacenamiento: no pasa nada */ }
}

// ------------------------------------------------------------------ formato

export const fmt = {
  tok(n) {
    const v = Number(n || 0);
    if (v >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
    if (v >= 1e3) return `${(v / 1e3).toFixed(1)}k`;
    return String(v);
  },
  entero: (n) => Number(n || 0).toLocaleString('es'),
  costo(v, billing) {
    if (v === null || v === undefined) return billing === 'subscription' ? 'suscripción' : '—';
    return v < 1 ? `$${v.toFixed(4)}` : `$${v.toFixed(2)}`;
  },
  fecha(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? iso : d.toLocaleString('es', { dateStyle: 'short', timeStyle: 'short' });
  },
  hora(iso) {
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? '' : d.toLocaleTimeString('es', { hour: '2-digit', minute: '2-digit' });
  },
  cuando(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    const hoy = new Date();
    const mismoDia = d.toDateString() === hoy.toDateString();
    if (mismoDia) return d.toLocaleTimeString('es', { hour: '2-digit', minute: '2-digit' });
    const ayer = new Date(hoy); ayer.setDate(hoy.getDate() - 1);
    if (d.toDateString() === ayer.toDateString()) return 'ayer';
    return d.toLocaleDateString('es', { day: 'numeric', month: 'short' });
  },
  relativo(iso) {
    if (!iso) return '';
    const s = (Date.now() - new Date(iso).getTime()) / 1000;
    if (s < 60) return 'recién';
    if (s < 3600) return `hace ${Math.round(s / 60)} min`;
    if (s < 86400) return `hace ${Math.round(s / 3600)} h`;
    return `hace ${Math.round(s / 86400)} d`;
  },
  dia(iso) {
    const d = new Date(iso);
    return d.toLocaleDateString('es', { weekday: 'long', day: 'numeric', month: 'long' });
  },
  bytes(b) {
    if (b === null || b === undefined) return '—';
    if (b >= 1073741824) return `${(b / 1073741824).toFixed(1)} GB`;
    if (b >= 1048576) return `${(b / 1048576).toFixed(1)} MB`;
    if (b >= 1024) return `${(b / 1024).toFixed(1)} KB`;
    return `${b} B`;
  },
  hash: (s) => (s ? `${s.slice(0, 12)}…` : '—'),
  ms(v) {
    if (v === null || v === undefined) return '—';
    return v >= 1000 ? `${(v / 1000).toFixed(1)} s` : `${v} ms`;
  },
};

// ------------------------------------------------------------------ piezas

const ESTADOS = {
  ok: 'listo', passed: 'pasó', failed: 'falló', fallo: 'falló', error: 'error', en_curso: 'en curso',
  esperando: 'espera tu decisión', rechazado: 'rechazado', omitido: 'omitido', hecha: 'hecha', fallida: 'fallida',
  cancelada: 'cancelada', trabajando: 'trabajando', pendiente: 'pendiente', running: 'en curso', falta: 'falta',
};
export const estado = (valor) => h('span', { class: `estado ${valor}` }, ESTADOS[valor] || String(valor).replace('_', ' '));
export const pill = (texto, clase = '') => h('span', { class: `pill ${clase}` }, texto);
export const aviso = (texto, clase = '') => h('div', { class: `aviso ${clase}`, role: clase === 'error' ? 'alert' : null }, texto);
export const vacio = (nombreIcono, ...texto) => h('div', { class: 'vacio' }, nombreIcono ? icono(nombreIcono) : null, h('div', {}, ...texto));
export const cargando = (texto = 'Cargando…') => h('p', { class: 'cargando' }, texto);

export function cabecera(titulo, sub, ...extra) {
  return h('header', { class: 'cabecera' },
    h('div', {}, h('h1', { class: 'titulo' }, titulo), sub ? h('p', { class: 'sub' }, sub) : null),
    ...extra);
}

export const seccion = (titulo, ayuda, ...extra) => h('h2', { class: 'seccion' }, titulo,
  ayuda ? h('span', { class: 'ayuda' }, ayuda) : null, ...extra);

export function cifra(rotulo, valor, clase = '', nota = null) {
  return h('div', { class: 'tarjeta' },
    h('div', { class: 'cifra-rotulo' }, rotulo),
    h('div', { class: `cifra ${clase}` }, valor),
    nota ? h('div', { class: 'cifra-nota' }, nota) : null);
}

export function tabla(columnas, filas) {
  return h('div', { class: 'tabla-marco' },
    h('table', { class: 'tabla' },
      h('thead', {}, h('tr', {}, columnas.map(([titulo, clase]) => h('th', { class: clase || null, scope: 'col' }, titulo)))),
      h('tbody', {}, filas)));
}

export function filaClicable(destino, ...celdas) {
  const ir = () => { if (typeof destino === 'function') destino(); else location.hash = destino; };
  return h('tr', { class: 'clicable', tabindex: '0', onclick: ir, onkeydown: (e) => { if (e.key === 'Enter') ir(); } }, ...celdas);
}

export function segmentado(opciones, actual, alCambiar) {
  const botones = opciones.map(([valor, texto]) => h('button', {
    type: 'button', class: valor === actual ? 'activo' : null, 'aria-pressed': String(valor === actual),
    onclick: () => {
      botones.forEach((b) => { b.classList.remove('activo'); b.setAttribute('aria-pressed', 'false'); });
      boton(valor).classList.add('activo');
      boton(valor).setAttribute('aria-pressed', 'true');
      alCambiar(valor);
    },
  }, texto));
  const boton = (valor) => botones[opciones.findIndex(([v]) => v === valor)];
  return h('div', { class: 'segmentado', role: 'group' }, botones);
}

export function chips(opciones, actual, alCambiar) {
  const lista = opciones.map(([valor, texto]) => h('button', {
    type: 'button', class: `chip${valor === actual ? ' activo' : ''}`,
    onclick: (e) => { lista.forEach((c) => c.classList.remove('activo')); e.currentTarget.classList.add('activo'); alCambiar(valor); },
  }, texto));
  return h('div', { class: 'chips' }, lista);
}

export function select(opciones, actual, attrs = {}) {
  return h('select', { class: 'entrada', ...attrs },
    opciones.map(([valor, texto]) => h('option', { value: valor, selected: valor === actual ? true : null }, texto)));
}

export function boton(texto, onclick, clase = '', nombreIcono = null, attrs = {}) {
  return h('button', { type: 'button', class: `boton ${clase}`, onclick, ...attrs }, nombreIcono ? icono(nombreIcono) : null, texto);
}

export function totales(t) {
  if (!t) return null;
  return h('div', { class: 'totales' },
    h('span', { class: 'local' }, 'local ', h('b', {}, fmt.tok(t.local_tokens)), ' tok'),
    h('span', { class: 'remoto' }, 'remoto ', h('b', {}, fmt.tok(t.remote_tokens)), ' tok'),
    h('span', {}, 'costo ', h('b', {}, fmt.costo(t.cost_usd, t.billing_mode))),
    h('span', {}, 'salieron ', h('b', {}, t.egress_calls ?? 0), ' llamadas'));
}

export function tierPill(tier) {
  if (tier === 'remote' || tier === 'remoto') return pill('remoto · se paga', 'remoto');
  if (tier === 'local') return pill('local · gratis', 'local');
  return pill(tier);
}

export function costoPill(costo) {
  if (costo === 'gratis') return pill('gratis', 'local');
  if (costo === 'tokens remotos') return pill('tokens remotos', 'remoto');
  return pill(costo, 'acento');
}

// ------------------------------------------------------------------ markdown seguro

function enLinea(texto) {
  // **negrita**, `codigo`, [texto](url) y URLs sueltas. Solo http(s): nada de javascript:.
  const partes = [];
  const patron = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\((https?:\/\/[^)\s]+)\)|https?:\/\/[^\s)]+)/g;
  let ultimo = 0;
  for (const m of texto.matchAll(patron)) {
    if (m.index > ultimo) partes.push(texto.slice(ultimo, m.index));
    const t = m[0];
    if (t.startsWith('**')) partes.push(h('strong', {}, t.slice(2, -2)));
    else if (t.startsWith('`')) partes.push(h('code', {}, t.slice(1, -1)));
    else if (t.startsWith('[')) partes.push(h('a', { href: m[2], target: '_blank', rel: 'noopener noreferrer' }, t.slice(1, t.indexOf(']'))));
    else partes.push(h('a', { href: t, target: '_blank', rel: 'noopener noreferrer' }, t));
    ultimo = m.index + t.length;
  }
  if (ultimo < texto.length) partes.push(texto.slice(ultimo));
  return partes;
}

export function md(texto) {
  const raiz = h('div', { class: 'texto-md' });
  const lineas = String(texto || '').replace(/\r\n/g, '\n').split('\n');
  let i = 0;
  while (i < lineas.length) {
    const linea = lineas[i];
    if (linea.startsWith('```')) {
      const codigo = [];
      i += 1;
      while (i < lineas.length && !lineas[i].startsWith('```')) { codigo.push(lineas[i]); i += 1; }
      raiz.append(h('pre', {}, h('code', {}, codigo.join('\n'))));
      i += 1;
      continue;
    }
    const titulo = linea.match(/^(#{1,4})\s+(.*)$/);
    if (titulo) { raiz.append(h(`h${Math.min(titulo[1].length + 1, 4)}`, {}, enLinea(titulo[2]))); i += 1; continue; }
    if (/^\s*([-*]|\d+[.)])\s+/.test(linea)) {
      const ordenada = /^\s*\d/.test(linea);
      const lista = h(ordenada ? 'ol' : 'ul', {});
      while (i < lineas.length && /^\s*([-*]|\d+[.)])\s+/.test(lineas[i])) {
        lista.append(h('li', {}, enLinea(lineas[i].replace(/^\s*([-*]|\d+[.)])\s+/, ''))));
        i += 1;
      }
      raiz.append(lista);
      continue;
    }
    if (linea.startsWith('>')) {
      const cita = [];
      while (i < lineas.length && lineas[i].startsWith('>')) { cita.push(lineas[i].replace(/^>\s?/, '')); i += 1; }
      raiz.append(h('blockquote', {}, enLinea(cita.join(' '))));
      continue;
    }
    if (!linea.trim()) { i += 1; continue; }
    const parrafo = [];
    while (i < lineas.length && lineas[i].trim() && !/^(#{1,4}\s|```|>|\s*([-*]|\d+[.)])\s+)/.test(lineas[i])) {
      parrafo.push(lineas[i]); i += 1;
    }
    raiz.append(h('p', {}, enLinea(parrafo.join('\n'))));
  }
  return raiz;
}

// ------------------------------------------------------------------ trabajos y aprobaciones

export function tarjetaAprobacion(trabajo, alDecidir) {
  const p = trabajo.pendiente;
  const mensaje = h('div', { 'aria-live': 'assertive' });
  const botones = [];
  const decidir = async (decision) => {
    botones.forEach((b) => { b.disabled = true; });
    try {
      await api(`trabajos/${trabajo.id}/aprobacion`, { metodo: 'POST', cuerpo: { decision } });
    } catch (err) {
      mensaje.replaceChildren(aviso(err.message, 'error'));
    }
    alDecidir?.();
  };
  botones.push(
    boton('Aprobar', () => decidir('aprobar'), 'primario', 'check'),
    boton('Siempre para este destino', () => decidir('siempre')),
    boton('Rechazar', () => decidir('rechazar'), 'peligro', 'cruz'));
  return h('div', { class: 'aprobacion', role: 'alertdialog', 'aria-label': `Aprobar ${p.paso}` },
    h('div', { class: 'aprobacion-titulo' }, icono('alerta'), `${p.paso} quiere actuar`),
    h('p', { class: 'chico suave' },
      `Destino: ${p.destino}${p.metodo ? ` · ${p.metodo}` : ''}. Si nadie responde en ${Math.round(p.vence_en_s / 60)} min, cuenta como rechazo.`),
    h('pre', { class: 'bloque-codigo' }, p.vista),
    h('div', { class: 'acciones' }, botones),
    mensaje);
}

// Sigue un trabajo: llama a `dibujar(trabajo)` cada vez que cambia y lo da por terminado
// cuando deja de estar activo. Devuelve una funcion para dejar de seguirlo.
export function seguir(id, dibujar, { cada = 1000 } = {}) {
  let firma = '';
  let temporizador = null;
  let vivo = true;
  async function paso() {
    if (!vivo) return;
    let trabajo;
    try {
      trabajo = await api(`trabajos/${id}`);
    } catch (err) {
      dibujar(null, err);
      return;
    }
    const nueva = JSON.stringify(trabajo);
    if (nueva !== firma) { firma = nueva; dibujar(trabajo); }
    if (vivo && ACTIVOS.has(trabajo.estado)) temporizador = setTimeout(paso, cada);
  }
  paso();
  return () => { vivo = false; clearTimeout(temporizador); };
}

// Un panel que muestra un trabajo en curso: estado, aprobacion si la pide, eventos y,
// al terminar, lo que devuelva `resultado(trabajo)`.
export function panelTrabajo(id, resultado, { titulo = null, alTerminar = null } = {}) {
  const raiz = h('div', { class: 'panel-trabajo' }, cargando('Arrancando…'));
  let avisado = false;
  const parar = seguir(id, (t, err) => {
    if (err) { raiz.replaceChildren(aviso(err.message, 'error')); return; }
    const activo = ACTIVOS.has(t.estado);
    raiz.replaceChildren(...nodos(
      h('div', { class: 'fila' }, h('b', {}, titulo || t.titulo), estado(t.estado),
        h('a', { class: 'derecha chico', href: `#/trabajos/${t.id}` }, 'detalle')),
      t.pendiente ? tarjetaAprobacion(t) : null,
      !activo && t.resultado?.tipo === 'error' ? aviso(t.resultado.detalle, 'error') : null,
      !activo && t.resultado && t.resultado.tipo !== 'error' ? resultado(t) : null,
      t.eventos.length ? h('details', { class: 'plegable', open: activo ? true : null, style: { marginTop: '10px' } },
        h('summary', {}, activo ? 'Qué está haciendo' : 'Registro'),
        h('div', {}, h('pre', { class: 'bloque-codigo envuelto eventos' }, t.eventos.join('\n')))) : null,
    ));
    if (!activo && !avisado) { avisado = true; alTerminar?.(t); }
  });
  raiz.detener = parar;
  return raiz;
}

// ------------------------------------------------------------------ tema

const CLAVES_TINTA = ['papel', 'panel', 'texto', 'remoto', 'local', 'gris', 'acento'];
export const TEMA_BASE = 'sistema';

function luminancia(hex) {
  const n = parseInt(hex.slice(1), 16);
  const [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => v / 255);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export function aplicarTema(nombre, tinta) {
  const raiz = document.documentElement;
  const variables = {
    '--fondo': tinta.papel, '--superficie': tinta.panel, '--texto': tinta.texto, '--texto-2': tinta.gris,
    '--remoto': tinta.remoto, '--local': tinta.local, '--acento': tinta.acento, '--peligro': null,
  };
  for (const [variable, valor] of Object.entries(variables)) {
    if (nombre === TEMA_BASE || !valor) raiz.style.removeProperty(variable);
    else raiz.style.setProperty(variable, valor);
  }
  if (nombre === TEMA_BASE) raiz.removeAttribute('data-tema');
  else raiz.setAttribute('data-tema', luminancia(tinta.papel) < 0.4 ? 'oscuro' : 'claro');
}

export { CLAVES_TINTA };

export function pestanasSimples(opciones, actual, alCambiar) {
  const botones = opciones.map(([valor, texto]) => h('button', {
    type: 'button', role: 'tab', class: valor === actual ? 'activo' : null, 'aria-selected': String(valor === actual),
    onclick: (e) => {
      botones.forEach((b) => { b.classList.remove('activo'); b.setAttribute('aria-selected', 'false'); });
      e.currentTarget.classList.add('activo');
      e.currentTarget.setAttribute('aria-selected', 'true');
      alCambiar(valor);
    },
  }, texto));
  return h('div', { class: 'pestanas', role: 'tablist' }, botones);
}
