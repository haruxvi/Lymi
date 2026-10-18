// Codigo: el mapa de un repositorio que consultan los agentes, para ti. Buscar simbolos,
// leer solo la funcion que importa, quien la llama y que rompe si cambia. Todo local.

import { api, aviso, boton, cabecera, cargando, filaClicable, guardado, guardar, h, pill, seccion, tabla, vacio } from './base.js';

export async function vistaCodigo(ctx) {
  const raiz = h('input', { class: 'entrada mono', value: guardado('codigo:raiz', ''), placeholder: 'C:\\ruta\\a\\tu\\repositorio' });
  const consulta = h('input', { class: 'entrada', type: 'search', placeholder: 'Buscar función o clase por nombre…' });
  const zona = h('div', {});
  const detalle = h('div', {});

  async function pedir(op, extra = {}) {
    guardar('codigo:raiz', raiz.value.trim());
    return api('codigo', { metodo: 'POST', cuerpo: { op, raiz: raiz.value.trim(), ...extra } });
  }

  async function mostrar(op, extra, titulo, destino = detalle) {
    destino.replaceChildren(cargando());
    try {
      const r = await pedir(op, extra);
      destino.replaceChildren(seccion(titulo), h('pre', { class: 'bloque-codigo' }, r.texto));
    } catch (err) { destino.replaceChildren(aviso(err.message, 'error')); }
  }

  async function indexar() {
    zona.replaceChildren(cargando('Indexando (la primera vez tarda; después solo mira lo que cambió)…'));
    detalle.replaceChildren();
    try {
      const r = await pedir('indexar');
      const m = r.datos;
      zona.replaceChildren(
        aviso(r.texto, 'ok'),
        h('div', { class: 'fila', style: { margin: '12px 0' } },
          pill(`${m.total} archivos`), ...Object.entries(m.lenguajes).map(([l, n]) => pill(`${l} ${n}`))),
        tabla([['ARCHIVO'], ['LENGUAJE'], ['LÍNEAS', 'num'], ['SÍMBOLOS', 'num'], ['USA']],
          m.archivos.map((a) => filaClicable(() => mostrar('esqueleto', { ruta: a.ruta }, `Esqueleto de ${a.ruta}`),
            h('td', { class: 'mono' }, a.ruta), h('td', {}, a.lenguaje, a.exacto ? '' : ' (aprox.)'),
            h('td', { class: 'num' }, a.lineas), h('td', { class: 'num' }, a.simbolos),
            h('td', { class: 'mono chico' }, a.usa.slice(0, 4).join(', ') + (a.usa.length > 4 ? '…' : ''))))),
        m.mostrados < m.total ? h('p', { class: 'chico tenue' }, `Mostrando ${m.mostrados} de ${m.total}.`) : null);
    } catch (err) { zona.replaceChildren(aviso(err.message, 'error')); }
  }

  async function buscar() {
    if (!consulta.value.trim()) return;
    zona.replaceChildren(cargando());
    detalle.replaceChildren();
    try {
      const r = await pedir('buscar', { consulta: consulta.value.trim() });
      zona.replaceChildren(r.datos.length ? tabla([['SÍMBOLO'], ['TIPO'], ['DÓNDE'], ['FIRMA'], ['']],
        r.datos.map((s) => h('tr', {},
          h('td', { class: 'mono' }, s.nombre), h('td', {}, s.tipo), h('td', { class: 'mono chico' }, `${s.ruta}:${s.linea}`),
          h('td', { class: 'mono chico' }, (s.firma || '').slice(0, 80)),
          h('td', { class: 'nowrap' },
            boton('Ver', () => mostrar('fragmento', { nombre: s.nombre }, `Código de ${s.nombre}`), 'chico'),
            boton('Quién llama', () => mostrar('llamadores', { nombre: s.nombre }, `Quién llama a ${s.nombre}`), 'chico fantasma'),
            boton('Impacto', () => mostrar('impacto', { nombre: s.nombre }, `Qué toca un cambio en ${s.nombre}`), 'chico fantasma')))))
        : vacio('lupa', 'Sin coincidencias.'));
    } catch (err) { zona.replaceChildren(aviso(err.message, 'error')); }
  }
  consulta.addEventListener('keydown', (e) => { if (e.key === 'Enter') buscar(); });

  return h('section', { class: 'vista' },
    cabecera('Código', 'El mapa de un repositorio: los agentes leen la función que importa en vez del archivo entero, '
      + 'y cada llamador viene clasificado (confirmado, ambiguo o por nombre). Nada sale de tu equipo.'),
    h('div', { class: 'tarjeta' },
      h('div', { class: 'campo' }, h('label', { class: 'campo-rotulo' }, 'Repositorio'), h('div', { class: 'fila' }, raiz, boton('Indexar', indexar, 'primario', 'codigo'))),
      h('div', { class: 'fila' }, consulta, boton('Buscar', buscar, '', 'lupa'))),
    detalle, zona);
}
