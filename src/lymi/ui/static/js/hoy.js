// Hoy: lo que importa ahora, en una pantalla. Cada tarjeta sale de tus datos reales;
// si una fuente no esta configurada, la tarjeta dice como configurarla.

import { api, boton, fmt, h, icono, nodos, panelTrabajo, pill, tarjetaAprobacion } from './base.js';
import { compositor, nuevaSesion } from './chat.js';
import { resumenCorreo } from './correo.js';

function tarjeta(ic, titulo, accion, ...cuerpo) {
  return h('div', { class: 'tarjeta' },
    h('div', { class: 'tarjeta-cab' }, icono(ic), titulo, accion ? h('span', { class: 'accion' }, accion) : null),
    ...cuerpo);
}

function saludo(ahora) {
  const hora = new Date(ahora).getHours();
  return hora < 12 ? 'Buenos días' : hora < 20 ? 'Buenas tardes' : 'Buenas noches';
}

function eventos(lista, vacioTexto) {
  if (!lista.length) return h('div', { class: 'vacio-chico' }, vacioTexto);
  return h('div', { class: 'lista' }, lista.map((e) => h('div', { class: 'lista-item' },
    h('span', { class: 'hora' }, e.todo_el_dia ? 'todo el día' : fmt.hora(e.inicio)),
    h('div', { class: 'lista-cuerpo' }, h('div', { class: 'lista-titulo' }, e.titulo),
      e.lugar ? h('div', { class: 'lista-meta' }, e.lugar) : null))));
}

export async function vistaHoy(ctx) {
  const [d, resumen] = await Promise.all([api('hoy'), api('resumen')]);
  const comp = compositor({ alEnviar: nuevaSesion, placeholder: 'Dale una tarea a lymi…' });
  const zonaResumen = h('div', {});

  const agenda = d.agenda.ok
    ? tarjeta('calendario', 'Agenda', h('a', { href: '#/calendario' }, 'semana'),
      h('div', { class: 'chico suave' }, 'Hoy'), eventos(d.agenda.datos.hoy, 'Nada más hoy.'),
      d.agenda.datos.manana.length ? [h('div', { class: 'chico suave', style: { marginTop: '10px' } }, 'Mañana'),
        eventos(d.agenda.datos.manana, '')] : null)
    : tarjeta('calendario', 'Agenda', h('a', { href: '#/calendario' }, 'cómo'), h('div', { class: 'vacio-chico' }, d.agenda.error));

  const correo = d.correo.ok
    ? tarjeta('correo', 'Correo que importa', h('a', { href: '#/correo' }, 'bandeja'),
      h('div', { class: 'chico suave' }, `${d.correo.datos.sin_leer} sin leer en 3 días · ${d.correo.datos.boletines} son boletines`),
      d.correo.datos.ultimo && Date.now() - new Date(d.correo.datos.ultimo).getTime() > 2 * 86400000
        ? h('div', { class: 'aviso info', style: { margin: '8px 0' } }, `Thunderbird no descarga correo desde el ${fmt.fecha(d.correo.datos.ultimo)}: ábrelo para que sincronice.`) : null,
      d.correo.datos.importantes.length
        ? h('div', { class: 'lista' }, d.correo.datos.importantes.map((m) => h('a', {
          class: 'lista-item', href: `#/correo?carpeta=${encodeURIComponent(m.carpeta)}&n=${m.n}` },
        h('div', { class: 'lista-cuerpo' }, h('div', { class: 'lista-titulo' }, m.asunto || '(sin asunto)'),
          h('div', { class: 'lista-meta' }, `${m.de} · ${fmt.cuando(m.fecha)}`)))))
        : h('div', { class: 'vacio-chico' }, 'Nadie te escribió directamente sin respuesta.'),
      h('div', { class: 'acciones' },
        boton('Resumir con el modelo local', async (e) => {
          e.currentTarget.disabled = true;
          const t = await api('correo/resumen', { metodo: 'POST', cuerpo: { dias: 1, tier: 'local' } });
          zonaResumen.replaceChildren(panelTrabajo(t.id, resumenCorreo, { titulo: 'Resumen del correo de hoy' }));
        }, 'chico', 'rayo')))
    : tarjeta('correo', 'Correo', null, h('div', { class: 'vacio-chico' }, d.correo.error),
      h('div', { class: 'chico tenue' }, 'lymi lee el correo que Thunderbird guarda en este equipo. Instálalo y marca "mantener mensajes en este equipo".'));

  const esperando = d.esperando.length
    ? tarjeta('alerta', `Esperan tu decisión · ${d.esperando.length}`, null,
      ...d.esperando.map((t) => h('div', {}, h('div', { class: 'chico suave' }, t.titulo), tarjetaAprobacion(t, () => setTimeout(() => location.reload(), 400)))))
    : null;

  const memoria = tarjeta('memoria', 'Memoria', h('a', { href: '#/memoria' }, 'revisar'),
    d.memoria_sin_revisar === null ? h('div', { class: 'vacio-chico' }, 'Sin memoria todavía.')
      : h('div', {}, h('div', { class: 'cifra' }, d.memoria_sin_revisar),
        h('div', { class: 'cifra-nota' }, d.memoria_sin_revisar === 1 ? 'nota de un agente sin revisar' : 'notas de agentes sin revisar')));

  const programaciones = tarjeta('reloj', 'Programaciones', h('a', { href: '#/programaciones' }, 'todas'),
    d.programaciones.ok && d.programaciones.datos.length
      ? h('div', { class: 'lista' }, d.programaciones.datos.map((p) => h('div', { class: 'lista-item' },
        h('div', { class: 'lista-cuerpo' }, h('div', { class: 'lista-titulo' }, p.workflow),
          h('div', { class: 'lista-meta' }, `próxima ${fmt.fecha(p.proxima)}`)))))
      : h('div', { class: 'vacio-chico' }, 'Nada programado. Programa el informe del día para que te espere listo cada mañana.'),
    d.agenda_activa ? null : h('div', { class: 'chico tenue' }, 'La agenda corre mientras la app de escritorio (o lymi serve) está abierta.'));

  const conversaciones = tarjeta('chat', 'Conversaciones', h('a', { href: '#/chat' }, 'todas'),
    d.sesiones.length ? h('div', { class: 'lista' }, d.sesiones.map((s) => h('a', { class: 'lista-item', href: `#/chat/${s.id}` },
      h('div', { class: 'lista-cuerpo' }, h('div', { class: 'lista-titulo' }, s.titulo),
        h('div', { class: 'lista-meta' }, fmt.relativo(s.actualizada))))))
      : h('div', { class: 'vacio-chico' }, 'Escríbele arriba para empezar.'));

  const total = resumen.local_tokens + resumen.remote_tokens;
  const ahorro = tarjeta('escudo', 'Tus tokens', h('a', { href: '#/corridas' }, 'ledger'),
    h('div', { class: 'rejilla cifras' },
      h('div', {}, h('div', { class: 'cifra-rotulo' }, 'En tu máquina'), h('div', { class: 'cifra local' }, fmt.tok(resumen.local_tokens))),
      h('div', {}, h('div', { class: 'cifra-rotulo' }, 'Remotos'), h('div', { class: 'cifra remoto' }, fmt.tok(resumen.remote_tokens)))),
    h('div', { class: 'cifra-nota' }, total
      ? `${Math.round((100 * resumen.local_tokens) / total)}% del trabajo no salió de tu equipo · ${fmt.entero(resumen.egress_calls)} llamadas salieron, todas auditadas`
      : 'Todavía no corre nada. Todo lo que corra queda anotado aquí.'));

  return h('section', { class: 'vista' },
    h('div', { class: 'fila' }, h('h1', { class: 'saludo' }, saludo(d.ahora)),
      h('span', { class: 'derecha suave' }, fmt.dia(d.ahora))),
    comp,
    zonaResumen,
    esperando ? h('div', { style: { marginTop: '16px' } }, esperando) : null,
    h('div', { class: 'rejilla dos', style: { marginTop: '16px' } }, agenda, correo),
    h('div', { class: 'rejilla', style: { marginTop: '14px' } }, nodos(programaciones, memoria, conversaciones, ahorro)),
    h('div', { class: 'acciones' },
      h('a', { class: 'boton', href: '#/workflows/informe-del-dia.yml' }, icono('workflows'), 'Informe del día'),
      h('a', { class: 'boton', href: '#/web' }, icono('web'), 'Investigar'),
      h('a', { class: 'boton', href: '#/agencia' }, icono('agencia'), 'Darle trabajo a la agencia'),
      pill('Todo lo que ves sale de este equipo', 'local')));
}
