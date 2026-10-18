// Correo: tu bandeja de Thunderbird, de solo lectura. Resumir y redactar pasan por el
// motor (ledger, redaccion de datos sensibles). lymi no envia correo: deja el .eml listo.

import {
  api, aviso, boton, cargando, chips, fmt, guardado, guardar, h, icono, panelTrabajo, pill, qs, segmentado, vacio,
} from './base.js';

const PRIORIDADES = [['alta', 'Atiende primero', 'peligro'], ['media', 'Puede esperar', 'remoto'], ['baja', 'Solo para saber', '']];

export function resumenCorreo(t) {
  const datos = t.resultado?.datos?.resumen?.datos;
  if (!datos) return aviso(t.resultado?.detalle || 'sin resumen', t.resultado?.ok ? '' : 'error');
  const grupos = PRIORIDADES.map(([p, titulo, clase]) => {
    const lista = datos.mensajes.filter((m) => m.prioridad === p);
    if (!lista.length) return null;
    return h('div', { class: 'prioridad' },
      h('h3', {}, pill(titulo, clase), h('span', { class: 'tenue chico' }, lista.length)),
      h('div', { class: 'lista' }, lista.map((m) => h('a', {
        class: 'lista-item', href: `#/correo?${qs({ carpeta: m.carpeta, n: m.n })}` },
      h('div', { class: 'lista-cuerpo' },
        h('div', { class: 'lista-titulo' }, m.asunto || '(sin asunto)'),
        h('div', { class: 'lista-meta' }, `${m.de} · ${fmt.cuando(m.fecha)}${m.hilo > 1 ? ` · hilo de ${m.hilo}` : ''}`),
        m.accion ? h('div', { class: 'chico' }, '→ ', m.accion) : null)))));
  });
  return h('div', { style: { marginTop: '10px' } },
    h('p', { class: 'chico suave' }, `${datos.directos} directos · ${datos.boletines} boletines`
      + (datos.boletines_de.length ? ` (${datos.boletines_de.slice(0, 6).join(', ')}${datos.boletines_de.length > 6 ? '…' : ''})` : '')),
    ...grupos,
    ...datos.avisos.map((a) => aviso(a, 'info')),
    h('p', { class: 'chico tenue' }, 'Fechas, remitentes y asuntos salen del archivo; el modelo solo anota prioridad y acción.'));
}

export async function vistaCorreo(ctx, consulta = '') {
  const params = new URLSearchParams(consulta || '');
  const estado = {
    carpeta: params.get('carpeta') || guardado('correo:carpeta', 'INBOX'),
    filtro: guardado('correo:filtro', 'para_mi'),
    dias: guardado('correo:dias', 14),
    abierto: params.get('n') ? Number(params.get('n')) : null,
  };
  const carpetasEl = h('nav', { class: 'correo-carpetas', 'aria-label': 'Carpetas' }, cargando());
  const listaEl = h('div', { class: 'correo-mensajes' }, cargando());
  const lectura = h('div', { class: 'correo-lectura' });
  let mensajes = [];

  let datosCarpetas;
  try {
    datosCarpetas = await api('correo/carpetas');
  } catch (err) {
    return h('section', { class: 'vista' },
      h('h1', { class: 'titulo' }, 'Correo'),
      vacio('correo', h('p', {}, err.message),
        h('p', { class: 'chico' }, 'lymi lee lo que Thunderbird guarda en este equipo, sin tus claves. Instala Thunderbird, '
          + 'agrega tu cuenta (Gmail, Outlook, lo que uses) y en Configuración de la cuenta → Sincronización y almacenamiento '
          + 'marca "Mantener los mensajes de esta cuenta en este equipo".')));
  }

  function dibujarCarpetas() {
    const visibles = datosCarpetas.carpetas.filter((c) => c.mensajes > 0);
    carpetasEl.replaceChildren(
      h('div', { class: 'nav-grupo' }, 'Carpetas'),
      ...visibles.map((c) => h('div', {
        class: `correo-carpeta${c.carpeta === estado.carpeta || c.carpeta.endsWith(`/${estado.carpeta}`) ? ' activa' : ''}`,
        role: 'button', tabindex: '0',
        onclick: () => { estado.carpeta = c.carpeta; guardar('correo:carpeta', c.carpeta); estado.abierto = null; dibujarCarpetas(); cargarLista(); },
      }, h('span', {}, c.carpeta.split('/').pop()), c.sin_leer ? h('span', { class: 'tenue chico' }, c.sin_leer) : null)),
      h('div', { class: 'chico tenue', style: { padding: '12px 10px' } }, `Solo lectura · ${datosCarpetas.direcciones.join(', ') || 'sin identidades'}`));
  }

  async function cargarLista() {
    listaEl.replaceChildren(cargando());
    let atraso = null;
    try {
      const r = await api(`correo/mensajes?${qs({ carpeta: estado.carpeta, filtro: estado.filtro, dias: estado.dias, n: 80 })}`);
      mensajes = r.mensajes;
      if (r.ultimo && Date.now() - new Date(r.ultimo).getTime() > 2 * 86400000) {
        atraso = aviso(`Lo más nuevo descargado es del ${fmt.fecha(r.ultimo)}. Abre Thunderbird para que sincronice: lymi lee lo que él guarda.`, 'info');
      }
    } catch (err) {
      listaEl.replaceChildren(aviso(err.message, 'error'));
      return;
    }
    if (!ctx.vigente()) return;
    listaEl.replaceChildren(...(atraso ? [h('div', { style: { padding: '10px' } }, atraso)] : []), ...(mensajes.length ? mensajes.map((m) => h('button', {
      type: 'button', dataset: { n: m.n },
      class: `correo-msj${m.leido ? '' : ' sin-leer'}${m.boletin ? ' boletin' : ''}${m.n === estado.abierto ? ' activo' : ''}`,
      onclick: () => abrir(m.n),
    },
    h('div', { class: 'fila1' }, h('span', { class: 'de' }, m.de), h('span', { class: 'cuando' }, fmt.cuando(m.fecha))),
    h('div', { class: 'asunto' }, m.asunto || '(sin asunto)'),
    h('div', { class: 'extracto' }, m.extracto))) : [h('div', { class: 'vacio-chico', style: { padding: '16px' } }, 'Nada con este filtro.')]));
    if (estado.abierto) abrir(estado.abierto);
    else if (!lectura.childNodes.length) mostrarInicio();
  }

  function mostrarInicio() {
    const dias = h('select', { class: 'entrada chica', 'aria-label': 'Días a resumir' },
      [1, 2, 3, 7].map((d) => h('option', { value: String(d) }, d === 1 ? 'último día' : `últimos ${d} días`)));
    let tier = 'local';
    const zona = h('div', {});
    lectura.replaceChildren(
      h('h2', {}, 'Resumen del correo'),
      h('p', { class: 'suave' }, 'El modelo anota cada correo directo con su prioridad y lo que te pide. Los boletines se separan sin modelo.'),
      h('div', { class: 'fila' }, dias, segmentado([['local', 'Local · gratis'], ['remote', 'Remoto']], tier, (v) => { tier = v; }),
        boton('Resumir', async (e) => {
          e.currentTarget.disabled = true;
          try {
            const t = await api('correo/resumen', { metodo: 'POST', cuerpo: { dias: Number(dias.value), tier, carpeta: estado.carpeta } });
            zona.replaceChildren(panelTrabajo(t.id, resumenCorreo, { titulo: 'Resumen' }));
          } catch (err) { zona.replaceChildren(aviso(err.message, 'error')); }
        }, 'primario', 'rayo')),
      zona);
  }

  async function abrir(n) {
    estado.abierto = n;
    for (const b of listaEl.querySelectorAll('.correo-msj')) b.classList.toggle('activo', Number(b.dataset.n) === n);
    lectura.replaceChildren(cargando());
    let m;
    try {
      m = await api(`correo/mensaje?${qs({ carpeta: estado.carpeta, n })}`);
    } catch (err) {
      lectura.replaceChildren(aviso(err.message, 'error'));
      return;
    }
    const zonaBorrador = h('div', {});
    const instruccion = h('textarea', { class: 'entrada', rows: 2, placeholder: 'Qué quieres responder, en tus palabras (opcional)' });
    let tier = 'local';
    lectura.replaceChildren(
      h('h2', {}, m.asunto || '(sin asunto)'),
      h('div', { class: 'correo-cab' },
        h('div', {}, h('b', {}, m.de_completo)),
        h('div', {}, `Para: ${m.para}`),
        h('div', {}, fmt.fecha(m.fecha), ' · ', m.id),
        h('div', { class: 'fila', style: { marginTop: '6px' } },
          m.boletin ? pill('boletín') : null, m.para_mi ? pill('para ti', 'acento') : pill('no te lo escribieron a ti'),
          ...m.adjuntos.map((a) => pill(`📎 ${a}`)))),
      h('div', { class: 'texto-plano' }, m.cuerpo || '(sin texto)'),
      m.truncado ? aviso('El mensaje es muy grande: se muestra el principio.', 'info') : null,
      ...m.avisos.map((a) => aviso(a, 'info')),
      h('h3', { class: 'seccion' }, 'Responder'),
      h('div', { class: 'campo' }, instruccion),
      h('div', { class: 'fila' }, segmentado([['local', 'Local · gratis'], ['remote', 'Remoto']], tier, (v) => { tier = v; }),
        boton('Proponer respuesta', async (e) => {
          e.currentTarget.disabled = true;
          try {
            const t = await api('correo/borrador', { metodo: 'POST', cuerpo: { carpeta: estado.carpeta, n, instruccion: instruccion.value, tier } });
            zonaBorrador.replaceChildren(panelTrabajo(t.id, (tr) => editorBorrador(tr.resultado), { titulo: 'Borrador' }));
          } catch (err) { zonaBorrador.replaceChildren(aviso(err.message, 'error')); }
        }, 'primario', 'rayo')),
      zonaBorrador);
  }

  function editorBorrador(r) {
    if (!r.ok) return aviso(r.detalle || 'no se pudo redactar', 'error');
    const cuerpo = h('textarea', { class: 'entrada', rows: 10, value: r.cuerpo });
    const salida = h('div', {});
    return h('div', { style: { marginTop: '10px' } },
      h('div', { class: 'chico suave' }, `Para: ${r.para} · Asunto: ${r.asunto}`),
      h('div', { class: 'campo', style: { marginTop: '6px' } }, cuerpo),
      h('div', { class: 'fila' },
        boton('Guardar como .eml', async (e) => {
          e.currentTarget.disabled = true;
          try {
            const g = await api('correo/borrador/guardar', { metodo: 'POST', cuerpo: { carpeta: r.carpeta, n: r.n, cuerpo: cuerpo.value } });
            salida.replaceChildren(aviso(`Guardado en ${g.ruta}. Ábrelo con doble clic en Thunderbird, revísalo y envíalo tú.`, 'ok'));
          } catch (err) { salida.replaceChildren(aviso(err.message, 'error')); e.currentTarget.disabled = false; }
        }, 'primario', 'guardar'),
        h('span', { class: 'chico tenue' }, 'lymi no envía correo. Guardar queda en el diario y se puede deshacer.')),
      salida);
  }

  dibujarCarpetas();
  const filtros = h('div', { class: 'correo-filtros columna' },
    chips([['para_mi', 'Para mí'], ['personas', 'Sin boletines'], ['sin_leer', 'Sin leer'], ['todos', 'Todo']], estado.filtro,
      (v) => { estado.filtro = v; guardar('correo:filtro', v); cargarLista(); }),
    h('div', { class: 'fila' },
      h('select', { class: 'entrada chica', 'aria-label': 'Período', onchange: (e) => { estado.dias = Number(e.target.value); guardar('correo:dias', estado.dias); cargarLista(); } },
        [[3, '3 días'], [14, '2 semanas'], [60, '2 meses'], [0, 'todo']].map(([v, t]) => h('option', { value: String(v), selected: v === estado.dias ? true : null }, t))),
      boton('Resumir', () => { estado.abierto = null; mostrarInicio(); }, 'chico fantasma derecha', 'rayo')));
  const raiz = h('section', { class: 'vista lienzo-completo' },
    h('div', { class: 'correo' }, carpetasEl, h('div', { class: 'correo-lista' }, filtros, listaEl), lectura));
  cargarLista();
  return raiz;
}

export { icono };
