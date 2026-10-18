// Chat con lymi. Cada mensaje lo responde un asistente con herramientas (o un debate, o
// una de tus agencias) por el mismo motor que todo lo demas: ledger, topes y aprobaciones.

import {
  ACTIVOS, api, aviso, boton, cargando, fmt, guardado, guardar, h, icono, md, nodos, pill, seguir, select,
  tarjetaAprobacion, totales, vacio,
} from './base.js';
import { botonMicrofono, interruptorLectura, leer, leerRespuestas } from './voz.js';

const SUGERENCIAS = [
  '¿Qué tengo hoy en la agenda y qué correos debería responder primero?',
  'Investiga qué es WebGPU y dame 3 fuentes',
  'Busca en mi memoria lo que sé sobre el proyecto y resúmelo',
  'Lista los archivos de la carpeta salidas',
];

let catalogo = null;
async function cargarCatalogo() {
  if (catalogo) return catalogo;
  const [modelos, agencias] = await Promise.all([
    api('modelos').catch(() => ({ locales: [], remotos: [], remoto: null })),
    api('agencias').catch(() => ({ agencias: [] })),
  ]);
  catalogo = { modelos, agencias: agencias.agencias.filter((a) => !a.error) };
  return catalogo;
}

// ------------------------------------------------------------------ compositor

export function compositor({ alEnviar, sesion = null, placeholder = 'Pídele algo a lymi…', autofocus = false }) {
  const prefs = guardado('chat', { modo: 'asistente', tier: 'local', modelo_local: '', modelo_remoto: 'opus', presupuesto: 20000 });
  const area = h('textarea', { placeholder, rows: 2, 'aria-label': 'Mensaje para lymi', autofocus: autofocus ? true : null });
  const enviar = h('button', { type: 'button', class: 'boton primario icono-solo', title: 'Enviar (Ctrl+Enter)', 'aria-label': 'Enviar' }, icono('enviar'));
  const opciones = h('div', { class: 'fila' });
  const estadoMsj = h('div', { 'aria-live': 'polite' });

  const ajustar = () => { area.style.height = 'auto'; area.style.height = `${Math.min(area.scrollHeight, 260)}px`; };
  area.addEventListener('input', ajustar);

  let modoSel; let tierSel; let localSel; let remotoSel; let presupuesto;
  if (!sesion) {
    cargarCatalogo().then(({ modelos, agencias }) => {
      modoSel = select([['asistente', 'Asistente'], ['debate', 'Debate (3 agentes)'],
        ...agencias.map((a) => [`agencia:${a.archivo}`, `Agencia: ${a.nombre}`])], prefs.modo, { class: 'entrada chica', 'aria-label': 'Modo' });
      tierSel = select([['local', 'Local · gratis'], ['remote', 'Remoto · se paga']], prefs.tier,
        { class: 'entrada chica', 'aria-label': 'Dónde corre' });
      const locales = modelos.locales.length ? modelos.locales.map((m) => [m.id, `${m.id}${m.parametros ? ` · ${m.parametros}` : ''}`])
        : [['', modelos.error_local ? 'Ollama no responde' : 'sin modelos locales']];
      localSel = select([['', `por defecto (${modelos.local_defecto || 'qwen'})`], ...locales], prefs.modelo_local,
        { class: 'entrada chica', 'aria-label': 'Modelo local' });
      remotoSel = select(modelos.remotos.length ? modelos.remotos.map((m) => [m.id, `${m.id} · ${modelos.remoto}`])
        : [['', 'sin proveedor remoto']], prefs.modelo_remoto, { class: 'entrada chica', 'aria-label': 'Modelo remoto' });
      presupuesto = h('input', { class: 'entrada chica', type: 'number', min: '0', step: '1000', value: String(prefs.presupuesto ?? ''),
        title: 'Tope de tokens remotos para esta conversación (0 = sin tope)', 'aria-label': 'Presupuesto de tokens remotos' });
      const sincronizar = () => {
        const remoto = tierSel.value === 'remote';
        remotoSel.hidden = !remoto;
        presupuesto.hidden = !remoto;
        presupuesto.previousSibling.hidden = !remoto;
      };
      tierSel.addEventListener('change', sincronizar);
      opciones.replaceChildren(modoSel, tierSel, localSel, remotoSel, h('span', { class: 'chico tenue' }, 'tope'), presupuesto);
      sincronizar();
    });
  } else {
    opciones.replaceChildren(...nodos(
      pill(sesion.modo === 'debate' ? 'debate' : sesion.agencia ? `agencia ${sesion.agencia}` : 'asistente', 'acento'),
      pill(sesion.tier === 'remote' ? `remoto${sesion.modelo_remoto ? ` · ${sesion.modelo_remoto}` : ''}` : `local${sesion.modelo_local ? ` · ${sesion.modelo_local}` : ''}`,
        sesion.tier === 'remote' ? 'remoto' : 'local'),
      sesion.presupuesto ? pill(`tope ${fmt.tok(sesion.presupuesto)} tok`) : null,
    ));
  }

  async function mandar() {
    const texto = area.value.trim();
    if (!texto) return;
    enviar.disabled = true;
    estadoMsj.replaceChildren();
    const datos = { texto };
    if (!sesion && modoSel) {
      const modo = modoSel.value;
      Object.assign(datos, {
        modo: modo.startsWith('agencia:') ? 'agencia' : modo,
        agencia: modo.startsWith('agencia:') ? modo.slice(8) : null,
        tier: tierSel.value, modelo_local: localSel.value || null,
        modelo_remoto: tierSel.value === 'remote' ? (remotoSel.value || null) : null,
        presupuesto: tierSel.value === 'remote' ? Number(presupuesto.value || 0) : null,
      });
      guardar('chat', { modo, tier: tierSel.value, modelo_local: localSel.value, modelo_remoto: remotoSel.value, presupuesto: Number(presupuesto.value || 0) });
    }
    try {
      await alEnviar(datos);
      area.value = '';
      ajustar();
    } catch (err) {
      estadoMsj.replaceChildren(aviso(err.message, 'error'));
    } finally {
      enviar.disabled = false;
    }
  }
  enviar.addEventListener('click', mandar);
  area.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey || !e.shiftKey)) { e.preventDefault(); mandar(); }
  });

  const raiz = h('div', {},
    h('div', { class: 'compositor' }, area, h('div', { class: 'compositor-pie' }, opciones, h('div', { class: 'derecha' },
      h('span', { class: 'chico tenue' }, 'Enter envía · Shift+Enter salto'), botonMicrofono(area, estadoMsj), enviar))),
    estadoMsj);
  raiz.area = area;
  return raiz;
}

export async function nuevaSesion(datos) {
  const r = await api('sesiones', { metodo: 'POST', cuerpo: datos });
  location.hash = `#/chat/${r.sesion.id}`;
}

// ------------------------------------------------------------------ mensajes

function arbolTareas(tareas) {
  if (!tareas?.length) return null;
  const hijos = new Map();
  for (const t of tareas) {
    if (!hijos.has(t.padre)) hijos.set(t.padre, []);
    hijos.get(t.padre).push(t);
  }
  const pintar = (t) => h('div', { class: 'tarea' },
    h('div', { class: 'tarea-cab' },
      h('b', {}, t.agente), h('span', { class: `estado ${t.estado}` }, t.estado),
      t.origen !== 'inicial' ? pill(t.origen === 'creada' ? 'ayudante creado' : t.paralela ? 'delegada en paralelo' : 'delegada') : null,
      t.modelo ? pill(t.modelo) : null,
      h('span', { class: 'chico tenue' }, `${t.turnos} turnos · ${t.llamadas} llamadas · ${fmt.tok(t.tokens_locales)} local · ${fmt.tok(t.tokens_remotos)} remoto · ${t.segundos} s`)),
    t.descripcion && t.padre ? h('div', { class: 'tarea-texto' }, `Le pidieron: ${t.descripcion.slice(0, 400)}`) : null,
    t.resultado && t.padre ? h('div', { class: 'tarea-texto' }, `Entregó: ${t.resultado.slice(0, 600)}`) : null,
    t.error ? aviso(t.error, 'error') : null,
    t.sin_respaldo?.length ? aviso(`${t.sin_respaldo.length} citas que no aparecen en nada de lo que vio: ${t.sin_respaldo.slice(0, 3).join(', ')}`, 'error') : null,
    ...(t.avisos || []).map((a) => aviso(a, 'info')),
    ...(hijos.get(t.id) || []).map(pintar));
  return h('details', { class: 'plegable arbol-tareas' },
    h('summary', {}, `Cómo lo resolvió · ${tareas.length} ${tareas.length === 1 ? 'tarea' : 'tareas'}`),
    h('div', {}, (hijos.get(null) || []).map(pintar)));
}

function mensaje(m, enCurso) {
  if (m.rol === 'persona') {
    return h('div', { class: 'msj persona' }, h('div', { class: 'msj-avatar' }, 'Tú'),
      h('div', { class: 'msj-cuerpo' }, h('div', { class: 'msj-texto' }, m.texto)));
  }
  let cuerpo;
  if (m.estado === 'en_curso') cuerpo = enCurso || cargando('lymi está trabajando…');
  else if (m.estado === 'fallo') cuerpo = aviso(m.error || 'no terminó', 'error');
  else cuerpo = md(m.texto);
  return h('div', { class: 'msj lymi' }, h('div', { class: 'msj-avatar' }, 'l'),
    h('div', { class: 'msj-cuerpo' }, h('div', { class: 'msj-quien' }, 'lymi'), cuerpo,
      m.estado !== 'en_curso' ? h('div', { class: 'msj-pie' },
        totales(m.totales),
        m.texto ? h('button', { type: 'button', class: 'boton fantasma chico', onclick: () => leer(m.texto) }, icono('altavoz'), 'Leer') : null,
        m.run_id ? h('a', { href: `#/corridas/${m.run_id}` }, 'ver en el ledger') : null) : null,
      m.estado !== 'en_curso' ? arbolTareas(m.tareas) : null));
}

function progreso(trabajo) {
  return h('div', {},
    h('div', { class: 'fila chico suave' }, h('span', { class: `estado ${trabajo.estado}` }, trabajo.estado === 'esperando' ? 'espera tu decisión' : 'trabajando'),
      h('span', {}, trabajo.eventos.at(-1)?.replace(/^\S+\s+/, '') || '')),
    trabajo.pendiente ? tarjetaAprobacion(trabajo) : null);
}

// ------------------------------------------------------------------ vista

export async function vistaChat(ctx, sesionId = null) {
  const lista = h('div', { class: 'chat-sesiones' });
  const principal = h('div', { class: 'chat-principal' });
  const raiz = h('section', { class: 'vista lienzo-completo' }, h('div', { class: 'chat' },
    h('aside', { class: 'chat-lista' },
      h('div', { class: 'chat-lista-cab' }, h('h2', {}, 'Conversaciones'),
        h('a', { class: 'boton chico derecha', href: '#/chat' }, icono('mas'), 'Nueva')),
      lista),
    principal));

  async function dibujarLista() {
    const sesiones = await api('sesiones');
    lista.replaceChildren(...(sesiones.length ? sesiones.map((s) => h('a', {
      class: `chat-sesion${s.id === sesionId ? ' activa' : ''}`, href: `#/chat/${s.id}` },
    h('div', { class: 'lista-titulo' }, s.titulo),
    h('div', { class: 'lista-meta' }, `${fmt.relativo(s.actualizada)} · ${s.mensajes} mensajes${s.modo === 'debate' ? ' · debate' : ''}`)))
      : [h('div', { class: 'vacio-chico' }, 'Todavía no hay conversaciones.')]));
  }

  if (!sesionId) {
    const comp = compositor({ alEnviar: nuevaSesion, autofocus: true });
    principal.append(h('div', { class: 'chat-mensajes' }, h('div', { class: 'chat-mensajes-in' },
      h('div', {},
        h('h1', { class: 'titulo' }, '¿En qué te ayudo?'),
        h('p', { class: 'sub' }, 'lymi usa sus herramientas de verdad: tu correo, tu agenda, tus archivos, tu código, la web y tu memoria. '
          + 'Lo que cambie algo te lo pregunta antes. Todo queda en el ledger.'),
        comp,
        h('div', { class: 'sugerencias' }, SUGERENCIAS.map((s) => h('button', { type: 'button', class: 'chip',
          onclick: () => { comp.area.value = s; comp.area.focus(); } }, s))),
        h('p', { class: 'chico tenue' }, 'Debate: un moderador le pasa tu pregunta a dos agentes con posturas opuestas que investigan en paralelo, y escribe el veredicto.')))));
    await dibujarLista();
    return raiz;
  }

  const mensajesIn = h('div', { class: 'chat-mensajes-in' });
  const mensajesMarco = h('div', { class: 'chat-mensajes' }, mensajesIn);
  let sesion;
  let dejarDeSeguir = null;
  ctx.alSalir(() => dejarDeSeguir?.());

  async function dibujar(bajar = true) {
    sesion = await api(`sesiones/${sesionId}`);
    if (!ctx.vigente()) return;
    const ultimo = sesion.mensajes.at(-1);
    const vivo = ultimo?.rol === 'lymi' && ultimo.estado === 'en_curso' && ultimo.trabajo;
    const enCurso = vivo ? h('div', {}, cargando('lymi está trabajando…')) : null;
    mensajesIn.replaceChildren(...sesion.mensajes.map((m) => mensaje(m, m === ultimo ? enCurso : null)));
    if (bajar) mensajesMarco.scrollTop = mensajesMarco.scrollHeight;
    dejarDeSeguir?.();
    dejarDeSeguir = null;
    if (vivo) {
      dejarDeSeguir = seguir(ultimo.trabajo, (t, err) => {
        if (err) { enCurso.replaceChildren(aviso(err.message, 'error')); return; }
        if (ACTIVOS.has(t.estado)) enCurso.replaceChildren(progreso(t));
        else {
          dejarDeSeguir?.(); dejarDeSeguir = null;
          setTimeout(async () => {
            await dibujar(); dibujarLista(); ctx.refrescarEstado?.();
            const final = sesion.mensajes.at(-1);
            if (leerRespuestas() && final?.rol === 'lymi' && final.estado === 'ok' && final.texto) leer(final.texto).catch(() => {});
          }, 300);
        }
      });
    }
  }

  await dibujar();
  const cab = h('div', { class: 'chat-cab' }, h('h1', {}, sesion.titulo), interruptorLectura(),
    boton('', async () => {
      if (!confirm('¿Borrar esta conversación de este equipo? El ledger no cambia.')) return;
      await api(`sesiones/${sesionId}`, { metodo: 'DELETE' });
      location.hash = '#/chat';
    }, 'fantasma icono-solo', 'basura', { title: 'Borrar conversación', 'aria-label': 'Borrar conversación' }));
  const comp = compositor({
    sesion, autofocus: true,
    alEnviar: async ({ texto }) => { await api(`sesiones/${sesionId}/mensajes`, { metodo: 'POST', cuerpo: { texto } }); await dibujar(); },
  });
  principal.append(cab, mensajesMarco, h('div', { class: 'chat-compositor' }, comp));
  await dibujarLista();
  return raiz;
}

export { vacio };
