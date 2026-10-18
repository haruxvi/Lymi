// Programaciones: workflows que corren solos con cron. Todo se valida al programar, y un
// paso con efectos solo corre sin nadie delante si lo preautorizas aqui, paso por paso.

import { api, aviso, boton, cabecera, fmt, h, icono, pill, seccion, tabla, vacio } from './base.js';

const ATAJOS = [
  ['0 8 * * *', 'Todos los días a las 8:00'],
  ['0 9 * * mon-fri', 'Días hábiles a las 9:00'],
  ['0 * * * *', 'Cada hora'],
  ['*/15 * * * *', 'Cada 15 minutos'],
  ['0 18 * * fri', 'Viernes a las 18:00'],
];

export async function vistaProgramaciones(ctx) {
  const zona = h('div', {});
  const workflows = (await api('workflows')).workflows.filter((w) => !w.error);
  const wf = h('select', { class: 'entrada' }, workflows.map((w) => h('option', { value: w.archivo }, `${w.nombre} (${w.archivo})`)));
  const cron = h('input', { class: 'entrada mono', value: '0 8 * * *', 'aria-label': 'Expresión cron' });
  const zonaHoraria = h('input', { class: 'entrada', value: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC' });
  const efectos = h('div', { class: 'columna' });
  const msj = h('div', {});

  async function pasosConEfectos() {
    efectos.replaceChildren();
    if (!wf.value) return;
    const w = await api(`workflows/${encodeURIComponent(wf.value)}`);
    const conEfectos = (w.plan || []).filter((p) => p.efectos);
    if (!conEfectos.length) { efectos.append(h('span', { class: 'chico tenue' }, 'Este workflow no tiene pasos con efectos.')); return; }
    efectos.append(h('span', { class: 'chico suave' }, 'Pasos con efectos: sin nadie delante se rechazan, salvo que los autorices.'));
    for (const p of conEfectos) {
      efectos.append(h('label', { class: 'casilla' }, h('input', { type: 'checkbox', value: p.id }), `${p.id} · ${p.destino}`));
    }
  }
  wf.addEventListener('change', pasosConEfectos);

  async function cargar() {
    const d = await api('programaciones');
    if (!ctx.vigente()) return;
    zona.replaceChildren(
      d.agenda_activa ? aviso('La agenda está corriendo en esta app: lo programado se ejecuta a su hora.', 'ok')
        : aviso('Esta ventana no ejecuta la agenda. Lo programado corre mientras la app de escritorio o `lymi serve` estén abiertos.', 'info'),
      seccion('Programado'),
      d.programaciones.length ? tabla([['WORKFLOW'], ['CUÁNDO'], ['PRÓXIMA'], ['ÚLTIMA'], ['PREAUTORIZADO'], ['ESTADO'], ['']],
        d.programaciones.map((p) => h('tr', {},
          h('td', {}, h('a', { href: `#/workflows/${encodeURIComponent(p.workflow)}` }, p.workflow)),
          h('td', { class: 'mono' }, `${p.cron} (${p.zona})`),
          h('td', {}, fmt.fecha(p.proxima)), h('td', {}, p.ultima ? fmt.fecha(p.ultima) : 'nunca'),
          h('td', {}, p.aprobados.length ? p.aprobados.join(', ') : '—'),
          h('td', {}, p.activo ? pill('activa', 'local') : pill('pausada')),
          h('td', { class: 'nowrap' },
            boton(p.activo ? 'Pausar' : 'Reanudar', async () => { await api(`programaciones/${p.id}/${p.activo ? 'pausar' : 'reanudar'}`, { metodo: 'POST', cuerpo: {} }); cargar(); }, 'chico'),
            boton('', async () => { if (confirm('¿Quitar esta programación?')) { await api(`programaciones/${p.id}`, { metodo: 'DELETE' }); cargar(); } },
              'chico fantasma', 'basura', { 'aria-label': 'Quitar' })))))
        : vacio('reloj', 'Nada programado todavía.'),
      seccion('Webhooks', 'disparan un workflow cuando otro servicio te avisa'),
      d.webhooks.length ? tabla([['NOMBRE'], ['WORKFLOW'], ['FIRMA'], ['PREAUTORIZADO'], ['ESTADO']],
        d.webhooks.map((g) => h('tr', {}, h('td', { class: 'mono' }, g.nombre), h('td', {}, g.workflow), h('td', {}, g.esquema),
          h('td', {}, g.aprobados.join(', ') || '—'), h('td', {}, g.activo ? pill('activo', 'local') : pill('inactivo')))))
        : h('p', { class: 'chico tenue' }, 'Ninguno. Se crean con `lymi hooks add`: el secreto se muestra una sola vez y vive en el almacén de claves del sistema.'));
  }

  await pasosConEfectos();
  await cargar();
  return h('section', { class: 'vista' },
    cabecera('Programaciones', 'Workflows que corren solos. El informe del día a las 8:00 es el clásico.'),
    workflows.length ? h('div', { class: 'tarjeta' },
      h('div', { class: 'tarjeta-cab' }, icono('mas'), 'Programar un workflow'),
      h('div', { class: 'rejilla dos' },
        h('div', {}, h('div', { class: 'campo' }, h('label', { class: 'campo-rotulo' }, 'Workflow'), wf),
          h('div', { class: 'campo' }, h('label', { class: 'campo-rotulo' }, 'Zona horaria'), zonaHoraria)),
        h('div', {}, h('div', { class: 'campo' }, h('label', { class: 'campo-rotulo' }, 'Cuándo (cron)'), cron),
          h('div', { class: 'chips' }, ATAJOS.map(([c, t]) => h('button', { type: 'button', class: 'chip', onclick: () => { cron.value = c; } }, t))))),
      efectos,
      h('div', { class: 'acciones' }, boton('Programar', async () => {
        const aprobados = [...efectos.querySelectorAll('input:checked')].map((i) => i.value);
        try {
          const r = await api('programaciones', { metodo: 'POST', cuerpo: { workflow: wf.value, cron: cron.value, zona: zonaHoraria.value, aprobados } });
          msj.replaceChildren(aviso(`Programado: próxima ${fmt.fecha(r.proxima)}.${r.sin_autorizar.length
            ? ` Ojo: ${r.sin_autorizar.join(', ')} se rechazarán sin nadie delante.` : ''}`, r.sin_autorizar.length ? 'info' : 'ok'));
          cargar();
        } catch (err) { msj.replaceChildren(aviso(err.message, 'error')); }
      }, 'primario', 'reloj')), msj) : vacio('workflows', 'No hay workflows válidos para programar.'),
    zona);
}
