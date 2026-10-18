// Tu PC: que puede tocar lymi y que toco. Cada escritura, movimiento o borrado guarda
// antes como estaba; deshacer devuelve todo, en orden inverso. Borrar nunca borra.

import { api, aviso, boton, cabecera, fmt, h, icono, pill, seccion, vacio } from './base.js';

const OPS = { creado: 'creó', modificado: 'modificó', movido: 'movió', borrado: 'borró (guardado en el diario)', comando: 'ejecutó' };

function entrada(e) {
  const que = e.op === 'movido' ? `${e.origen} → ${e.destino}` : e.op === 'comando' ? `${e.nombre} ${(e.args || []).join(' ')} (código ${e.codigo})` : e.ruta;
  return h('div', { class: 'lista-item' },
    h('span', { class: 'hora' }, fmt.hora(e.ts)),
    h('div', { class: 'lista-cuerpo' }, h('div', {}, h('b', {}, OPS[e.op] || e.op), ' ', h('span', { class: 'mono' }, que))));
}

export async function vistaEquipo(ctx) {
  const [d, perfil] = await Promise.all([api('diario'), api('equipo/perfil')]);
  const msj = h('div', {});
  return h('section', { class: 'vista' },
    cabecera('Tu PC', 'lymi actúa sobre tu equipo con operaciones cerradas: leer, listar, escribir, mover, borrar y ejecutar '
      + 'comandos de una lista blanca. Nunca abre una consola, y lo que cambia se puede deshacer.'),
    h('div', { class: 'rejilla dos' },
      h('div', { class: 'tarjeta' }, h('div', { class: 'tarjeta-cab' }, icono('escudo'), 'Puede escribir en'),
        perfil.escribibles.map((r) => h('div', { class: 'mono' }, r)),
        h('div', { class: 'tarjeta-cab', style: { marginTop: '14px' } }, 'Puede leer'),
        perfil.legibles.map((r) => h('div', { class: 'mono' }, r))),
      h('div', { class: 'tarjeta' }, h('div', { class: 'tarjeta-cab' }, icono('pc'), 'Comandos permitidos'),
        Object.keys(perfil.comandos).length ? Object.entries(perfil.comandos).map(([c, sub]) => h('div', { class: 'fila' },
          h('span', { class: 'mono' }, c), sub.length ? h('span', { class: 'chico suave' }, `solo: ${sub.join(', ')}`) : pill('cualquier argumento')))
          : h('div', { class: 'vacio-chico' }, 'Ninguno: lymi no ejecuta comandos.'),
        h('div', { class: 'tarjeta-cab', style: { marginTop: '14px' } }, 'Siempre vetado'),
        h('div', { class: 'chico suave' }, 'El sistema operativo, los programas instalados, tus credenciales (.ssh, .aws, .gnupg…), el ledger y .git.'),
        h('p', { class: 'chico tenue' }, `Se configura en ${perfil.archivo}.`))),
    seccion('Lo que hizo', 'por corrida, lo más reciente primero'),
    msj,
    d.corridas.length ? d.corridas.map((c) => h('div', { class: 'tarjeta', style: { marginBottom: '10px' } },
      h('div', { class: 'tarjeta-cab' }, h('span', { class: 'mono' }, c.corrida), h('span', { class: 'chico tenue' }, `${c.total} acciones · ${fmt.fecha(c.ultima)}`),
        h('span', { class: 'accion' }, c.deshecho ? pill(`deshecho ${c.deshecho}`, 'local')
          : boton('Deshacer todo', async () => {
            if (!confirm(`¿Deshacer las ${c.total} acciones de ${c.corrida}? Lo que se quite también queda guardado.`)) return;
            try {
              const r = await api(`diario/${encodeURIComponent(c.corrida)}/deshacer`, { metodo: 'POST', cuerpo: {} });
              msj.replaceChildren(aviso(r.informe.join('\n') || 'Hecho.', 'ok'));
              location.reload();
            } catch (err) { msj.replaceChildren(aviso(err.message, 'error')); }
          }, 'chico', 'deshacer'))),
      h('div', { class: 'lista' }, c.entradas.slice().reverse().map(entrada))))
      : vacio('pc', 'lymi todavía no tocó nada en tu equipo.'));
}
