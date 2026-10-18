// Interfaz de lymi: navegacion, enrutador y barra de estado.
// Cada seccion vive en su modulo de /static/js/.

import { aplicarTema, api, aviso, boton, cargando, fmt, h, icono, nodos } from './js/base.js';
import { vistaAgencia, vistaAgencias } from './js/agencia.js';
import { vistaCalendario } from './js/calendario.js';
import { vistaChat } from './js/chat.js';
import { vistaCodigo } from './js/codigo.js';
import { vistaCorreo } from './js/correo.js';
import { vistaEditor } from './js/editor.js';
import { vistaEquipo } from './js/equipo.js';
import { vistaHoy } from './js/hoy.js';
import { vistaMemoria } from './js/memoria.js';
import { vistaProgramaciones } from './js/programaciones.js';
import {
  vistaApariencia, vistaCorrida, vistaCorridas, vistaEgress, vistaMedir, vistaProveedores, vistaTrabajo,
  vistaWorkflows,
} from './js/sistema.js';
import { vistaWeb } from './js/web.js';

const NAV = [
  ['Trabajo', [
    ['hoy', 'Hoy', 'hoy'],
    ['chat', 'Chat', 'chat'],
    ['correo', 'Correo', 'correo'],
    ['calendario', 'Calendario', 'calendario'],
    ['agencia', 'Agencia', 'agencia'],
    ['workflows', 'Workflows', 'workflows'],
    ['programaciones', 'Programaciones', 'reloj'],
    ['memoria', 'Memoria', 'memoria'],
    ['codigo', 'Código', 'codigo'],
    ['web', 'Web', 'web'],
    ['equipo', 'Tu PC', 'equipo'],
  ]],
  ['Sistema', [
    ['corridas', 'Corridas', 'corridas'],
    ['egress', 'Lo que salió', 'salida'],
    ['medir', 'Medir ahorro', 'medir'],
    ['proveedores', 'Modelos y proveedores', 'chip'],
    ['apariencia', 'Apariencia', 'paleta'],
  ]],
];

const RUTAS = [
  [/^#\/hoy$/, vistaHoy, 'hoy'],
  [/^#\/chat$/, vistaChat, 'chat'],
  [/^#\/chat\/([0-9a-f]{12})$/, vistaChat, 'chat'],
  [/^#\/correo(?:\?(.*))?$/, (ctx, q) => vistaCorreo(ctx, q || ''), 'correo'],
  [/^#\/calendario$/, vistaCalendario, 'calendario'],
  [/^#\/agencia$/, vistaAgencias, 'agencia'],
  [/^#\/agencia\/([A-Za-z0-9._%-]+)$/, vistaAgencia, 'agencia'],
  [/^#\/workflows$/, vistaWorkflows, 'workflows'],
  [/^#\/workflows\/nuevo$/, (ctx) => vistaEditor(ctx, null), 'workflows'],
  [/^#\/workflows\/([A-Za-z0-9._%-]+)$/, vistaEditor, 'workflows'],
  [/^#\/programaciones$/, vistaProgramaciones, 'programaciones'],
  [/^#\/memoria$/, vistaMemoria, 'memoria'],
  [/^#\/codigo$/, vistaCodigo, 'codigo'],
  [/^#\/web$/, vistaWeb, 'web'],
  [/^#\/equipo$/, vistaEquipo, 'equipo'],
  [/^#\/corridas$/, vistaCorridas, 'corridas'],
  [/^#\/corridas\/([0-9a-f]{12})$/, vistaCorrida, 'corridas'],
  [/^#\/egress$/, vistaEgress, 'egress'],
  [/^#\/medir$/, vistaMedir, 'medir'],
  [/^#\/proveedores$/, vistaProveedores, 'proveedores'],
  [/^#\/apariencia$/, vistaApariencia, 'apariencia'],
  [/^#\/trabajos\/([0-9a-f]{10})$/, vistaTrabajo, null],
];

function dibujarNav() {
  const nav = document.getElementById('nav');
  nav.replaceChildren(...NAV.flatMap(([grupo, items]) => [
    h('div', { class: 'nav-grupo' }, grupo),
    ...items.map(([ruta, texto, ic]) => h('a', { class: 'nav-item', href: `#/${ruta}`, dataset: { ruta } },
      icono(ic), h('span', {}, texto))),
  ]));
}

function marcarNav(seccion) {
  for (const enlace of document.querySelectorAll('#nav .nav-item')) {
    const activo = enlace.dataset.ruta === seccion;
    enlace.classList.toggle('activo', activo);
    if (activo) enlace.setAttribute('aria-current', 'page');
    else enlace.removeAttribute('aria-current');
  }
  const item = NAV.flatMap(([, items]) => items).find(([r]) => r === seccion);
  document.title = item ? `${item[1]} · lymi` : 'lymi';
}

// ------------------------------------------------------------------ barra de estado

let esperandoAntes = 0;

// ------------------------------------------------------------------ avisos

let cursorAvisos = null;

function tostada(aviso) {
  const zona = document.getElementById('avisos') || document.body.appendChild(h('div', { id: 'avisos', class: 'avisos', 'aria-live': 'polite' }));
  const icono_ = { aprobacion: 'alerta', evento: 'calendario', programacion: 'reloj', error: 'alerta', terminado: 'check' }[aviso.tipo] || 'check';
  const cerrar = () => tarjeta.remove();
  const tarjeta = h('div', { class: `aviso-flotante ${aviso.tipo}`, role: 'status' },
    icono(icono_),
    h('div', { class: 'aviso-cuerpo' }, h('b', {}, aviso.titulo), aviso.texto ? h('div', { class: 'chico suave' }, aviso.texto) : null,
      aviso.enlace ? h('a', { href: aviso.enlace, class: 'chico', onclick: cerrar }, 'Ver') : null),
    h('button', { type: 'button', class: 'boton fantasma chico icono-solo', 'aria-label': 'Cerrar aviso', onclick: cerrar }, icono('cruz')));
  zona.append(tarjeta);
  setTimeout(cerrar, aviso.tipo === 'aprobacion' ? 30000 : 12000);
}

async function mirarAvisos() {
  let r;
  try {
    r = await api(`avisos?desde=${cursorAvisos ?? 0}`);
  } catch { return; }
  if (cursorAvisos === null) { cursorAvisos = r.ultimo; return; } // al abrir no se repite lo viejo
  for (const a of r.avisos) {
    tostada(a);
    // En el navegador (lymi ui) y con la pestana oculta, tambien como notificacion del sistema.
    if (!r.nativos && document.hidden && 'Notification' in window && Notification.permission === 'granted') {
      const n = new Notification(a.titulo, { body: a.texto, icon: '/static/icono.png', tag: `lymi-${a.id}` });
      n.onclick = () => { window.focus(); if (a.enlace) location.hash = a.enlace; };
    }
  }
  cursorAvisos = r.ultimo;
  if (!r.nativos && 'Notification' in window && Notification.permission === 'default' && r.avisos.length && !pidioPermiso) {
    pidioPermiso = true;
    tostada({ tipo: 'terminado', titulo: '¿Te aviso aunque no mires esta pestaña?', texto: 'Notificaciones locales del navegador; no pasan por ningún servicio externo.',
      enlace: '' });
    const ultima = document.querySelector('#avisos .aviso-flotante:last-child .aviso-cuerpo');
    ultima?.append(h('button', { type: 'button', class: 'boton chico', onclick: () => Notification.requestPermission() }, 'Sí, avisarme'));
  }
}

let pidioPermiso = false;

async function actualizarEstado() {
  const barra = document.getElementById('estado');
  try {
    const r = await api('resumen');
    const parar = boton(r.detenido ? 'Reanudar' : 'Detener todo', async () => {
      parar.disabled = true;
      try { await api(r.detenido ? 'reanudar' : 'parar', { metodo: 'POST', cuerpo: {} }); } catch (err) { parar.textContent = err.message; }
      actualizarEstado();
    }, `chico ${r.detenido ? 'primario' : 'peligro'}`, r.detenido ? 'play' : 'pausa');
    barra.replaceChildren(...nodos(
      h('span', { class: 'dato local' }, 'Local ', h('b', {}, fmt.tok(r.local_tokens)), ' tok gratis'),
      h('span', { class: 'dato remoto' }, 'Remoto ', h('b', {}, fmt.tok(r.remote_tokens)), ' tok'),
      h('span', { class: 'dato' }, h('b', {}, fmt.entero(r.corridas)), ' corridas'),
      h('a', { class: 'dato', href: '#/egress' }, h('b', {}, fmt.entero(r.egress_calls)), ' llamadas salieron'),
      r.trabajos_activos ? h('span', { class: 'dato' }, h('b', {}, r.trabajos_activos), ' en curso') : null,
      r.esperando ? h('a', { class: 'dato remoto', href: '#/hoy' }, h('b', {}, r.esperando), ' esperan tu decisión') : null,
      h('span', { class: 'espaciador' }),
      r.detenido ? h('span', { class: 'pill peligro' }, 'lymi está detenido') : null,
      parar,
    ));
    const cuenta = document.querySelector('#nav [data-ruta="hoy"] .nav-cuenta');
    if (r.esperando && !cuenta) document.querySelector('#nav [data-ruta="hoy"]')?.append(h('span', { class: 'nav-cuenta' }, r.esperando));
    else if (cuenta && !r.esperando) cuenta.remove();
    else if (cuenta) cuenta.textContent = r.esperando;
    esperandoAntes = r.esperando;
    await mirarAvisos();
  } catch (err) {
    barra.replaceChildren(h('span', { class: 'tenue' }, `Sin conexión con lymi: ${err.message}`));
  }
}

async function pieLateral() {
  const pie = document.getElementById('lateral-pie');
  pie.replaceChildren(h('span', {}, h('span', { class: 'punto' }), 'Solo en este equipo'));
}

// ------------------------------------------------------------------ enrutador

let generacion = 0;
let limpiezas = [];

async function navegar() {
  limpiezas.forEach((fn) => { try { fn(); } catch { /* una limpieza que falla no frena la navegacion */ } });
  limpiezas = [];
  const hash = location.hash || '#/hoy';
  const ruta = RUTAS.find(([patron]) => patron.test(hash));
  if (!ruta) { location.replace('#/hoy'); return; }
  const [patron, vista, seccion] = ruta;
  const parametros = hash.match(patron).slice(1).map((p) => (p === undefined ? undefined : p.includes('=') ? p : decodeURIComponent(p)));
  const miGeneracion = ++generacion;
  const contexto = {
    alSalir: (fn) => { limpiezas.push(fn); },
    vigente: () => miGeneracion === generacion,
    refrescarEstado: actualizarEstado,
  };
  marcarNav(seccion);
  const contenedor = document.getElementById('vista');
  contenedor.replaceChildren(h('div', { class: 'vista' }, cargando()));
  try {
    const nodo = await vista(contexto, ...parametros);
    if (miGeneracion !== generacion) return;
    contenedor.replaceChildren(nodo);
    contenedor.scrollTop = 0;
    if (!nodo.querySelector('[autofocus]')) contenedor.focus({ preventScroll: true });
    else nodo.querySelector('[autofocus]').focus();
  } catch (err) {
    if (miGeneracion !== generacion) return;
    contenedor.replaceChildren(h('div', { class: 'vista' }, aviso(`No se pudo cargar: ${err.message}`, 'error')));
  }
}

async function iniciar() {
  try {
    const t = await api('tema');
    aplicarTema(t.nombre, t.tinta);
  } catch { /* sin tema guardado: el del sistema */ }
  dibujarNav();
  pieLateral();
  window.addEventListener('hashchange', navegar);
  actualizarEstado();
  setInterval(actualizarEstado, 6000);
  navegar();
}

iniciar();
