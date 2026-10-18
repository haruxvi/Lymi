// Web: leer paginas como markdown, buscar, mapear un sitio e investigar con fuentes. Cada
// peticion pasa por el guardia de red (nada de direcciones internas) y queda en el ledger.

import { api, aviso, boton, cabecera, h, md, panelTrabajo, pestanasSimples, pill, segmentado } from './base.js';

function informe(t) {
  const salida = t.resultado?.datos?.web;
  if (!salida) return aviso(t.resultado?.detalle || 'sin resultado', t.resultado?.ok ? '' : 'error');
  if (salida.respuesta !== undefined) {
    const v = salida.verificacion;
    return h('div', { style: { marginTop: '10px' } },
      md(salida.respuesta),
      h('div', { class: 'fila', style: { margin: '10px 0' } },
        pill(v.resumen, v.inexistentes?.length || v.sin_fuente?.length ? 'remoto' : 'local')),
      h('ol', { class: 'chico' }, salida.fuentes.map((f) => h('li', {}, h('a', { href: f.url, target: '_blank', rel: 'noopener noreferrer' }, f.titulo || f.url)))),
      ...salida.avisos.map((a) => aviso(a, 'info')),
      h('p', { class: 'chico tenue' }, 'Cada cita se busca en el texto real de su fuente: las que no aparecen se marcan.'));
  }
  if (salida.markdown !== undefined) {
    return h('div', { style: { marginTop: '10px' } },
      h('h3', {}, salida.titulo || salida.url), salida.descripcion ? h('p', { class: 'suave' }, salida.descripcion) : null,
      h('pre', { class: 'bloque-codigo envuelto' }, salida.markdown),
      salida.truncado ? aviso('La página es larga: se muestra el principio.', 'info') : null);
  }
  if (salida.urls) {
    return h('div', { style: { marginTop: '10px' } }, h('p', { class: 'suave' }, `${salida.urls.length} URLs, ${salida.visitadas} páginas visitadas`),
      h('pre', { class: 'bloque-codigo' }, salida.urls.join('\n')));
  }
  if (Array.isArray(salida)) {
    return h('div', { class: 'lista', style: { marginTop: '10px' } }, salida.map((r) => h('div', { class: 'lista-item' },
      h('div', { class: 'lista-cuerpo' }, h('a', { href: r.url, target: '_blank', rel: 'noopener noreferrer' }, r.titulo || r.url),
        h('div', { class: 'chico suave' }, r.fragmento)))));
  }
  return h('pre', { class: 'bloque-codigo envuelto' }, JSON.stringify(salida, null, 2));
}

export async function vistaWeb() {
  const zona = h('div', {});
  let tier = 'local';
  const campo = h('textarea', { class: 'entrada', rows: 2 });
  const urls = h('textarea', { class: 'entrada mono', rows: 2, placeholder: 'URLs a usar como fuentes, una por línea (opcional)' });
  const urlsCampo = h('div', { class: 'campo' }, urls);
  const tierCampo = segmentado([['local', 'Local · gratis'], ['remote', 'Remoto']], tier, (v) => { tier = v; });
  let op = 'investigar';
  const textos = {
    investigar: ['¿Qué quieres saber?', 'Investigar'],
    extraer: ['https://… la página a leer', 'Leer página'],
    buscar: ['Qué buscar', 'Buscar'],
    mapear: ['https://… el sitio a mapear', 'Mapear sitio'],
  };
  const lanzar = boton('Investigar', async () => {
    lanzar.disabled = true;
    const valor = campo.value.trim();
    const cuerpo = { op, tier };
    if (op === 'investigar') { cuerpo.pregunta = valor; cuerpo.urls = urls.value.split('\n').map((u) => u.trim()).filter(Boolean); }
    else if (op === 'buscar') cuerpo.consulta = valor;
    else cuerpo.url = valor;
    try {
      const t = await api('web', { metodo: 'POST', cuerpo });
      zona.prepend(panelTrabajo(t.id, informe, { alTerminar: () => { lanzar.disabled = false; } }));
    } catch (err) { zona.prepend(aviso(err.message, 'error')); lanzar.disabled = false; }
  }, 'primario', 'web');

  const sincronizar = () => {
    campo.placeholder = textos[op][0];
    lanzar.lastChild.textContent = textos[op][1];
    urlsCampo.hidden = op !== 'investigar';
    tierCampo.hidden = op !== 'investigar';
  };
  sincronizar();

  return h('section', { class: 'vista' },
    cabecera('Web', 'Lo de Firecrawl, Playwright y Perplexity, hecho por lymi: páginas como markdown, sitios mapeados y '
      + 'respuestas con fuentes cuyas citas se comprueban. Sin servicios de terceros: tu buscador es el tuyo (SearXNG local).'),
    h('div', { class: 'tarjeta' },
      pestanasSimples([['investigar', 'Investigar'], ['extraer', 'Leer página'], ['buscar', 'Buscar'], ['mapear', 'Mapear sitio']], op,
        (v) => { op = v; sincronizar(); }),
      h('div', { class: 'campo' }, campo), urlsCampo,
      h('div', { class: 'fila' }, tierCampo, lanzar),
      h('p', { class: 'chico tenue' }, 'Nunca entra a direcciones de tu red local, y lo marcado como nunca-sale no se envía.')),
    zona);
}
