// Agencia: departamentos de agentes que se derivan trabajo, en paralelo o esperando,
// y crean ayudantes temporales. Todo bajo topes duros compartidos.

import { api, aviso, boton, cabecera, costoPill, fmt, h, icono, md, panelTrabajo, pill, seccion, select, tierPill, totales, vacio } from './base.js';

export function arbolAgencia(tareas) {
  const hijos = new Map();
  for (const t of tareas) {
    if (!hijos.has(t.padre)) hijos.set(t.padre, []);
    hijos.get(t.padre).push(t);
  }
  const pintar = (t) => h('div', { class: 'tarea' },
    h('div', { class: 'tarea-cab' }, h('b', {}, t.agente), h('span', { class: `estado ${t.estado}` }, t.estado),
      t.origen === 'creada' ? pill('ayudante creado', 'acento') : t.origen === 'delegada' ? pill(t.paralela ? 'en paralelo' : 'esperando su resultado') : null,
      t.modelo ? pill(t.modelo) : null,
      h('span', { class: 'chico tenue' }, `${t.turnos} turnos · ${fmt.tok(t.tokens_locales)} local · ${fmt.tok(t.tokens_remotos)} remoto · ${t.segundos} s`)),
    t.padre ? h('div', { class: 'tarea-texto' }, `Le pidieron: ${(t.descripcion || '').slice(0, 300)}`) : null,
    t.resultado && t.padre ? h('div', { class: 'tarea-texto' }, `Entregó: ${t.resultado.slice(0, 500)}`) : null,
    t.error ? aviso(t.error, 'error') : null,
    t.sin_respaldo?.length ? aviso(`Citas sin respaldo en lo que vio: ${t.sin_respaldo.slice(0, 3).join(', ')}`, 'error') : null,
    ...(t.avisos || []).map((a) => aviso(a, 'info')),
    ...(hijos.get(t.id) || []).map(pintar));
  return h('div', {}, (hijos.get(null) || []).map(pintar));
}

export function resultadoAgencia(t) {
  const r = t.resultado;
  return h('div', { style: { marginTop: '10px' } },
    r.ok ? md(r.resultado || '') : aviso(r.detalle || 'la agencia no terminó', 'error'),
    h('div', { class: 'msj-pie' }, totales(r.totales), h('span', {}, `ruta: ${r.ruta}`),
      h('span', {}, `${r.tareas.length} tareas, hasta ${r.max_simultaneos} a la vez`),
      h('a', { href: `#/corridas/${r.run_id}` }, 'ver en el ledger')),
    seccion('Quién hizo qué'), arbolAgencia(r.tareas));
}

export async function vistaAgencias() {
  const d = await api('agencias');
  return h('section', { class: 'vista' },
    cabecera('Agencia', 'Departamentos de agentes. Cada uno tiene su rol, su modelo y sus herramientas; se derivan trabajo, '
      + 'en paralelo o esperando, y crean ayudantes cuando hace falta. Todo con topes duros y en el ledger.'),
    d.agencias.length ? h('div', { class: 'rejilla' }, d.agencias.map((a) => h('a', { class: 'tarjeta', href: `#/agencia/${encodeURIComponent(a.archivo)}` },
      h('div', { class: 'tarjeta-cab' }, icono('agencia'), a.nombre || a.archivo),
      a.error ? aviso(a.error, 'error') : [
        h('div', { class: 'tarjeta-texto' }, a.descripcion || ''),
        h('div', { class: 'fila', style: { marginTop: '10px' } }, pill(`${a.departamentos} departamentos`), pill(`${a.agentes} agentes`),
          a.remotos ? pill(`${a.remotos} remotos`, 'remoto') : pill('todo local', 'local'))])))
      : vacio('agencia', `No hay agencias en ${d.carpeta}.`, h('p', { class: 'chico' }, 'Copia agencias/startup.example.yml y ajústala.')),
    h('p', { class: 'chico tenue', style: { marginTop: '16px' } }, `Archivos YAML en ${d.carpeta}. En el chat puedes elegir una agencia como modo.`));
}

export async function vistaAgencia(ctx, archivo) {
  const a = await api(`agencias/${encodeURIComponent(archivo)}`);
  const volver = h('a', { class: 'volver', href: '#/agencia' }, '← Agencias');
  if (a.error) return h('section', { class: 'vista' }, volver, cabecera(a.archivo, 'No es una agencia válida.'), aviso(a.error, 'error'));

  const agentes = a.departamentos.flatMap((d) => d.agentes);
  const tarea = h('textarea', { class: 'entrada', rows: 3, placeholder: 'La tarea, en tus palabras. Empieza con @departamento para elegir a quién va.' });
  const agente = select([['', 'Que lymi elija (enrutador local, gratis)'], ...a.departamentos.map((d) => [d.nombre, `Departamento ${d.nombre}`]),
    ...agentes.map((x) => [x.completo, x.completo])], '');
  const zona = h('div', {});
  const lanzar = boton('Darle la tarea', async () => {
    lanzar.disabled = true;
    try {
      const t = await api(`agencias/${encodeURIComponent(archivo)}/correr`, { metodo: 'POST', cuerpo: { tarea: tarea.value, agente: agente.value || null } });
      zona.replaceChildren(panelTrabajo(t.id, resultadoAgencia, { titulo: a.nombre, alTerminar: () => { lanzar.disabled = false; } }));
    } catch (err) { zona.replaceChildren(aviso(err.message, 'error')); lanzar.disabled = false; }
  }, 'primario', 'play');

  const lim = a.limites;
  return h('section', { class: 'vista' }, volver,
    cabecera(a.nombre, a.descripcion, costoPill(a.costo)),
    h('div', { class: 'tarjeta' },
      h('div', { class: 'campo' }, h('label', { class: 'campo-rotulo' }, 'Tarea'), tarea),
      h('div', { class: 'fila' }, agente, lanzar),
      h('p', { class: 'chico tenue' }, 'Lo que un agente quiera cambiar en tu PC te lo pregunta aquí antes.')),
    zona,
    seccion('Organigrama'),
    h('div', { class: 'organigrama' }, a.departamentos.map((d) => h('div', { class: 'departamento' },
      h('h3', {}, d.nombre), d.descripcion ? h('div', { class: 'chico suave' }, d.descripcion) : null,
      d.agentes.map((x) => h('div', { class: 'agente' },
        h('div', { class: 'agente-cab' }, h('b', {}, x.nombre), x.lider ? pill('líder', 'acento') : null, tierPill(x.tier),
          x.modelo ? pill(x.modelo) : null, x.respaldo ? pill('si se agota, local') : null, x.puede_crear ? pill('crea ayudantes') : null),
        h('div', { class: 'chico suave', style: { marginTop: '4px' } }, x.descripcion),
        x.delega_a.length ? h('div', { class: 'chico', style: { marginTop: '6px' } }, 'Delega a: ', x.delega_a.join(', ')) : null,
        x.herramientas.length ? h('div', { class: 'herramientas' }, x.herramientas.map((t) => pill(t))) : null))))),
    seccion('Topes duros', 'los comparte todo el árbol de agentes'),
    h('div', { class: 'rejilla cifras' },
      [['Niveles de delegación', lim.profundidad], ['A la vez', lim.simultaneos], ['Agentes en total', lim.agentes_totales],
        ['Turnos por agente', lim.turnos_por_agente], ['Llamadas a modelos', lim.llamadas],
        ['Tokens remotos', lim.tokens_remotos ? fmt.tok(lim.tokens_remotos) : 'sin tope'], ['Tiempo', `${Math.round(lim.segundos / 60)} min`]]
        .map(([r, v]) => h('div', { class: 'tarjeta' }, h('div', { class: 'cifra-rotulo' }, r), h('div', { class: 'cifra' }, v)))));
}
