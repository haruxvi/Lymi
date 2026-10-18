// Calendario: tus eventos de archivos .ics, agrupados por dia. Sin conexiones.

import { api, cabecera, fmt, h, segmentado, vacio, aviso } from './base.js';

export async function vistaCalendario(ctx) {
  const zona = h('div', {});
  let dias = 7;

  async function cargar() {
    let d;
    try {
      d = await api(`calendario?dias=${dias}`);
    } catch (err) {
      zona.replaceChildren(vacio('calendario', h('p', {}, err.message),
        h('p', { class: 'chico' }, 'Exporta tus calendarios como .ics (Google Calendar: Configuración → Importar y exportar; '
          + 'Outlook y Thunderbird también exportan) y déjalos en la carpeta calendario/ de lymi, o apunta LYMI_CALENDARIO a tu carpeta.')));
      return;
    }
    if (!ctx.vigente()) return;
    const porDia = new Map();
    for (const e of d.eventos) {
      const clave = new Date(e.inicio).toDateString();
      if (!porDia.has(clave)) porDia.set(clave, []);
      porDia.get(clave).push(e);
    }
    const hoy = new Date();
    const bloques = [];
    for (let i = 0; i < dias; i += 1) {
      const dia = new Date(hoy); dia.setDate(hoy.getDate() + i);
      const lista = porDia.get(dia.toDateString()) || [];
      if (!lista.length && i > 1) continue;
      bloques.push(h('div', { class: 'dia' },
        h('h3', {}, i === 0 ? 'Hoy ' : i === 1 ? 'Mañana ' : '', h('span', { class: 'tenue' }, fmt.dia(dia.toISOString()))),
        lista.length ? lista.map((e) => h('div', { class: 'evento' },
          h('span', { class: 'hora' }, e.todo_el_dia ? 'todo el día' : `${fmt.hora(e.inicio)}–${fmt.hora(e.fin)}`),
          h('div', {}, h('b', {}, e.titulo), e.lugar ? h('div', { class: 'chico suave' }, e.lugar) : null,
            h('div', { class: 'chico tenue' }, e.calendario))))
          : h('div', { class: 'vacio-chico' }, 'Libre.')));
    }
    zona.replaceChildren(
      ...bloques,
      ...d.avisos.map((a) => aviso(a, 'info')),
      h('p', { class: 'chico tenue' }, `Leído de: ${d.archivos.join(', ')}. Repeticiones, zonas horarias y excepciones incluidas.`));
  }

  await cargar();
  return h('section', { class: 'vista' },
    cabecera('Calendario', 'Tu agenda desde archivos .ics de este equipo. lymi no se conecta a Google ni a Microsoft.',
      segmentado([[7, '7 días'], [14, '2 semanas'], [30, '30 días']], dias, (v) => { dias = v; cargar(); })),
    zona);
}
