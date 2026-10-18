// Memoria: lo que anota un agente queda SIN REVISAR hasta que tu lo promueves. Nada se
// borra: descartar es mover a descartadas. Son archivos markdown (compatibles con Obsidian).

import { api, aviso, boton, cabecera, cargando, fmt, h, pill, vacio } from './base.js';

const ESTADOS = [['afirmaciones', 'Por revisar'], ['hechos', 'Hechos'], ['descartadas', 'Descartadas']];

function nota(n, alMover) {
  const acciones = n.estado === 'afirmacion' ? [
    boton('Es cierto', () => alMover(n.id, 'promover'), 'chico primario', 'check'),
    boton('Descartar', () => alMover(n.id, 'descartar'), 'chico', 'cruz'),
  ] : [];
  return h('div', { class: 'nota' },
    h('div', { class: 'nota-texto' }, n.texto),
    n.fragmento ? h('div', { class: 'chico suave', style: { marginTop: '6px' } }, `…${n.fragmento}…`) : null,
    h('div', { class: 'nota-meta' },
      n.estado === 'afirmacion' ? pill('sin revisar', 'remoto') : n.estado === 'hecho' ? pill('hecho', 'local') : pill(n.estado),
      h('span', {}, `fuente: ${n.fuente}`), h('span', {}, `por ${n.agente}`), h('span', {}, fmt.fecha(n.creada)),
      n.corrida ? h('a', { href: `#/corridas/${n.corrida}` }, 'corrida') : null,
      h('span', { class: 'mono' }, n.linea ? `${n.ruta}:${n.linea}` : n.ruta)),
    acciones.length ? h('div', { class: 'acciones' }, acciones) : null);
}

export async function vistaMemoria(ctx) {
  let estado = 'afirmaciones';
  const pestanas = h('div', { class: 'pestanas', role: 'tablist' });
  const lista = h('div', {}, cargando());
  const buscar = h('input', { class: 'entrada', type: 'search', placeholder: 'Buscar en la memoria (BM25 local)…' });
  const texto = h('textarea', { class: 'entrada', rows: 3, placeholder: 'Algo que lymi debería saber. Lo que escribes tú entra directo como hecho.' });
  const fuente = h('input', { class: 'entrada', placeholder: 'Fuente (opcional): de dónde lo sabes' });
  const msj = h('div', {});
  let raizMemoria = '';

  async function mover(id, accion) {
    try { await api(`memoria/${id}/${accion}`, { metodo: 'POST', cuerpo: {} }); } catch (err) { msj.replaceChildren(aviso(err.message, 'error')); }
    cargar();
  }

  async function cargar() {
    const q = buscar.value.trim();
    lista.replaceChildren(cargando());
    try {
      if (q) {
        const r = await api(`memoria/buscar?q=${encodeURIComponent(q)}`);
        lista.replaceChildren(...(r.length ? r.map((n) => nota(n, mover)) : [vacio('lupa', 'Nada coincide.')]));
        return;
      }
      const d = await api(`memoria?estado=${estado}`);
      raizMemoria = d.raiz;
      pestanas.replaceChildren(...ESTADOS.map(([e, t]) => h('button', { type: 'button', role: 'tab', class: e === estado ? 'activo' : null,
        'aria-selected': String(e === estado), onclick: () => { estado = e; cargar(); } }, t, h('span', { class: 'cuenta' }, d.cuentas[e]))));
      lista.replaceChildren(...(d.notas.length ? d.notas.map((n) => nota(n, mover))
        : [vacio('memoria', estado === 'afirmaciones' ? 'No hay nada por revisar.' : 'Vacío.')]));
    } catch (err) {
      lista.replaceChildren(aviso(err.message, 'error'));
    }
  }

  let espera = null;
  buscar.addEventListener('input', () => { clearTimeout(espera); espera = setTimeout(cargar, 250); });
  await cargar();
  return h('section', { class: 'vista' },
    cabecera('Memoria', 'Lo que lymi recuerda entre sesiones. Un agente solo puede afirmar: tú decides qué es cierto. '
      + 'Sin secretos: lo que parezca una clave se rechaza.'),
    h('div', { class: 'rejilla dos' },
      h('div', { class: 'tarjeta' }, h('div', { class: 'tarjeta-cab' }, 'Anotar'),
        h('div', { class: 'campo' }, texto), h('div', { class: 'campo' }, fuente),
        boton('Guardar como hecho', async () => {
          try {
            await api('memoria', { metodo: 'POST', cuerpo: { texto: texto.value, fuente: fuente.value } });
            texto.value = ''; fuente.value = '';
            msj.replaceChildren(aviso('Guardado.', 'ok'));
            estado = 'hechos'; cargar();
          } catch (err) { msj.replaceChildren(aviso(err.message, 'error')); }
        }, 'primario', 'guardar'), msj),
      h('div', { class: 'tarjeta' }, h('div', { class: 'tarjeta-cab' }, 'Buscar'), buscar,
        h('p', { class: 'chico tenue' }, `Cada resultado trae su ruta:línea, verificable. Carpeta: ${raizMemoria}`))),
    h('div', { style: { marginTop: '18px' } }, pestanas, lista));
}
