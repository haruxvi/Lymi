// Editor de workflows por nodos, al estilo n8n: paleta, lienzo e inspector.
//
// El lienzo y el YAML son el mismo archivo: lo que se edita aqui se valida con el mismo
// esquema que `lymi flow run` y se guarda como YAML. El orden de ejecucion es el orden de
// izquierda a derecha: mover un nodo a la izquierda de otro lo pone antes.
//
// Lo que n8n no tiene: cada nodo dice si corre gratis en tu equipo, si se paga o si pide
// permiso, y cuanto costo de verdad (mediana de las corridas reales del ledger).

import {
  ACTIVOS, api, aviso, boton, estado, fmt, guardado, guardar, h, icono, nodos, pill, seguir, svg, tarjetaAprobacion, totales,
} from './base.js';

const ANCHO = 230;
const ALTO_PUERTO = 32;
const SEPARACION = 290;
const ICONOS = { llm: 'modelo', agencia: 'agencia', correo: 'correo', calendario: 'calendario', memoria: 'memoria', codigo: 'codigo',
  web: 'web', http: 'red', tool: 'red', pc: 'pc', transform: 'logica' };
const CLASE_GRUPO = { Modelos: 'g-modelos', 'Tus datos': 'g-datos', Red: 'g-red', 'Tu PC': 'g-pc', Logica: 'g-logica' };
const LARGOS = new Set(['prompt', 'system', 'contenido', 'tarea', 'pregunta', 'body', 'args', 'set', 'texto']);
const ETIQUETAS = {
  id: 'Nombre del nodo', when: 'Se ejecuta cuando', retries: 'Reintentos', timeout_s: 'Tiempo máximo (s)', tier: 'Dónde corre',
  prompt: 'Instrucción', system: 'Sistema', output: 'Salida', max_tokens: 'Tokens máximos', op: 'Operación', url: 'URL',
  consulta: 'Consulta', pregunta: 'Pregunta', urls: 'URLs fuente', ruta: 'Ruta', destino: 'Destino', contenido: 'Contenido',
  comando: 'Comando', args: 'Argumentos', carpeta: 'Carpeta', n: 'Cantidad', dias: 'Días', solo_sin_leer: 'Solo sin leer',
  mensaje: 'Mensaje n°', texto: 'Texto', fuente: 'Fuente', solo_hechos: 'Solo hechos', archivo: 'Archivo de la agencia',
  tarea: 'Tarea', agente: 'Agente', integration: 'Integración', tool: 'Herramienta', method: 'Método', body: 'Cuerpo',
  side_effect: 'Tiene efectos', set: 'Valores', raiz: 'Repositorio', nombre: 'Símbolo', profundidad: 'Profundidad',
  max_paginas: 'Páginas máximas', max_resultados: 'Resultados máximos', autor: 'Autor',
};
const VALORES = {
  llm: { tier: 'local', prompt: '' }, correo: { op: 'listar', dias: 1 }, calendario: { dias: 1 },
  memoria: { op: 'buscar', consulta: '' }, codigo: { op: 'buscar', consulta: '' }, web: { op: 'extraer', url: '' },
  pc: { op: 'leer', ruta: 'salidas/' }, transform: { set: { resultado: '' } }, agencia: { archivo: 'agencias/startup.example.yml', tarea: '' },
  http: { integration: '', url: '' }, tool: { integration: '', tool: '' },
};

// ------------------------------------------------------------------ esquema -> controles

function tipoCampo(esq) {
  if (!esq) return { tipo: 'json' };
  if (esq.enum) return { tipo: 'enum', opciones: esq.enum };
  if (esq.const !== undefined) return { tipo: 'enum', opciones: [esq.const] };
  const variantes = esq.anyOf ? esq.anyOf.filter((v) => v.type !== 'null') : [esq];
  const opcional = Boolean(esq.anyOf?.some((v) => v.type === 'null'));
  const v = variantes[0] || {};
  if (variantes.length > 1 && variantes.some((x) => x.type === 'array') && variantes.some((x) => x.type === 'string')) return { tipo: 'lista', opcional };
  if (v.enum) return { tipo: 'enum', opciones: v.enum, opcional };
  if (v.type === 'boolean') return { tipo: 'bool', opcional };
  if (v.type === 'integer' || v.type === 'number') return { tipo: 'numero', entero: v.type === 'integer', opcional };
  if (v.type === 'string') return { tipo: 'texto', opcional };
  if (v.type === 'array' && (v.items?.type === 'string' || !v.items)) return { tipo: 'lista', opcional };
  return { tipo: 'json', opcional };
}

function resumenNodo(paso) {
  const partes = [paso.type];
  if (paso.op) partes.push(paso.op);
  if (paso.tier) partes.push(paso.tier === 'remote' ? 'remoto' : 'local');
  const objetivo = paso.url || paso.consulta || paso.pregunta || paso.ruta || paso.nombre || paso.comando || paso.archivo || paso.tool;
  if (objetivo) partes.push(String(objetivo).slice(0, 40));
  return partes.join(' · ');
}

function referencias(paso) {
  const texto = JSON.stringify(paso);
  return [...new Set([...texto.matchAll(/steps\.([A-Za-z_][A-Za-z0-9_]*)/g)].map((m) => m[1]))];
}

function idUnico(pasos, base) {
  const ids = new Set(pasos.map((p) => p.id));
  let n = 1;
  while (ids.has(`${base}_${n}`)) n += 1;
  return `${base}_${n}`;
}

// ------------------------------------------------------------------ vista

export async function vistaEditor(ctx, archivo) {
  const esquema = await api('editor/esquema');
  const tipos = Object.fromEntries(esquema.tipos.map((t) => [t.tipo, t]));

  let flujo;
  let yamlCrudo = '';
  if (archivo) {
    const w = await api(`workflows/${encodeURIComponent(archivo)}`);
    if (w.error) {
      return h('section', { class: 'vista' },
        h('a', { class: 'volver', href: '#/workflows' }, '← Workflows'),
        h('h1', { class: 'titulo' }, w.archivo),
        aviso(`El archivo no es un workflow válido, así que el lienzo no lo puede abrir:\n${w.error}`, 'error'),
        h('pre', { class: 'bloque-codigo', style: { marginTop: '12px' } }, w.yaml));
    }
    flujo = w.flujo;
    yamlCrudo = w.yaml;
  } else {
    flujo = { name: 'nuevo_workflow', description: '', steps: [] };
  }
  flujo.steps = flujo.steps || [];

  const clavePos = `editor:pos:${archivo || 'nuevo'}`;
  let posiciones = guardado(clavePos, {});
  let seleccion = null;
  let sucio = false;
  let validacion = { ok: true, plan: [], resumen: null, yaml: yamlCrudo };
  let costos = { corridas: 0, pasos: {} };
  let corrida = null;
  let dejarDeSeguir = null;
  ctx.alSalir(() => dejarDeSeguir?.());
  const vista = { x: 40, y: 40, z: 1 };

  // -------------------------------------------------------------- elementos

  const capa = h('div', { class: 'lienzo-capa' });
  const aristas = svg('svg', { class: 'aristas', width: 1, height: 1 });
  capa.append(aristas);
  const ayuda = h('div', { class: 'lienzo-ayuda' }, h('p', {}, 'Arrastra un nodo desde la izquierda, o haz clic en uno para agregarlo.'),
    h('p', { class: 'chico' }, 'El orden de izquierda a derecha es el orden de ejecución.'));
  const lienzo = h('div', { class: 'lienzo', tabindex: '0', 'aria-label': 'Lienzo del workflow' }, capa, ayuda);
  const pie = h('div', { class: 'editor-pie', hidden: true });
  const inspector = h('aside', { class: 'editor-inspector', 'aria-label': 'Propiedades' });
  const nombreEl = h('div', { class: 'nombre' });
  const estadoValidacion = h('span', {});
  const botonGuardar = boton('Guardar', () => guardarFlujo(), '', 'guardar');
  const botonEjecutar = boton('Ejecutar', () => prepararEjecucion(), 'primario', 'play');

  // -------------------------------------------------------------- paleta

  const buscar = h('input', { class: 'entrada', type: 'search', placeholder: 'Buscar nodo…', 'aria-label': 'Buscar nodo' });
  const listaTipos = h('div', { class: 'editor-tipos' });
  function dibujarPaleta() {
    const q = buscar.value.trim().toLowerCase();
    listaTipos.replaceChildren(...esquema.grupos.flatMap((g) => {
      const delGrupo = esquema.tipos.filter((t) => t.grupo === g && (!q || `${t.titulo} ${t.descripcion} ${t.tipo}`.toLowerCase().includes(q)));
      if (!delGrupo.length) return [];
      return [h('div', { class: 'editor-grupo' }, g), ...delGrupo.map((t) => h('button', {
        type: 'button', class: 'tipo-nodo', draggable: 'true', title: t.descripcion,
        onclick: () => agregar(t.tipo, null),
        ondragstart: (e) => { e.dataTransfer.setData('text/lymi-nodo', t.tipo); e.dataTransfer.effectAllowed = 'copy'; },
      }, h('span', { class: `icono-nodo ${CLASE_GRUPO[t.grupo] || ''}` }, icono(ICONOS[t.tipo] || 'workflows')),
      h('span', {}, h('b', {}, t.titulo), h('span', {}, t.descripcion))))];
    }));
  }
  buscar.addEventListener('input', dibujarPaleta);

  // -------------------------------------------------------------- modelo

  function posicion(id, i) {
    if (!posiciones[id]) posiciones[id] = { x: 60 + i * SEPARACION, y: 140 };
    return posiciones[id];
  }

  function reordenarPorX() {
    flujo.steps.sort((a, b) => (posiciones[a.id]?.x ?? 0) - (posiciones[b.id]?.x ?? 0));
  }

  function cambio() {
    sucio = true;
    guardar(clavePos, posiciones);
    dibujarBarra();
    validarPronto();
  }

  function agregar(tipo, punto) {
    const t = tipos[tipo];
    const paso = { id: idUnico(flujo.steps, tipo), type: tipo };
    for (const r of t.requeridos) {
      if (r === 'id' || r in paso) continue;
      const c = tipoCampo(t.campos[r]);
      paso[r] = c.tipo === 'enum' ? c.opciones[0] : c.tipo === 'lista' ? [] : c.tipo === 'json' ? {} : c.tipo === 'numero' ? 0 : '';
    }
    Object.assign(paso, VALORES[tipo] || {});
    const ultimo = flujo.steps.at(-1);
    posiciones[paso.id] = punto || (ultimo ? { x: posicion(ultimo.id, 0).x + SEPARACION, y: posicion(ultimo.id, 0).y } : { x: 60, y: 140 });
    flujo.steps.push(paso);
    reordenarPorX();
    seleccion = paso.id;
    cambio();
    dibujarLienzo();
    dibujarInspector();
  }

  function quitar(id) {
    flujo.steps = flujo.steps.filter((p) => p.id !== id);
    delete posiciones[id];
    seleccion = null;
    cambio();
    dibujarLienzo();
    dibujarInspector();
  }

  function duplicar(id) {
    const original = flujo.steps.find((p) => p.id === id);
    const copia = JSON.parse(JSON.stringify(original));
    copia.id = idUnico(flujo.steps, original.type);
    const pos = posiciones[id];
    posiciones[copia.id] = { x: pos.x + 40, y: pos.y + 120 };
    flujo.steps.push(copia);
    reordenarPorX();
    seleccion = copia.id;
    cambio();
    dibujarLienzo();
    dibujarInspector();
  }

  // -------------------------------------------------------------- validacion

  let temporizador = null;
  function validarPronto() {
    clearTimeout(temporizador);
    temporizador = setTimeout(validar, 450);
  }
  async function validar() {
    if (!flujo.steps.length) {
      validacion = { ok: false, error: 'Agrega al menos un nodo.', plan: [] };
    } else {
      try {
        validacion = await api('editor/validar', { metodo: 'POST', cuerpo: { flujo } });
      } catch (err) { validacion = { ok: false, error: err.message, plan: [] }; }
    }
    if (!ctx.vigente()) return;
    dibujarBarra();
    dibujarLienzo();
    if (seleccion === null) dibujarInspector();
  }

  function erroresDe(paso) {
    if (validacion.ok || !validacion.error) return [];
    const i = flujo.steps.indexOf(paso);
    return validacion.error.split('\n').filter((l) => l.startsWith(`steps.${i}.`) || l.includes(`paso '${paso.id}'`) || l.includes(`'${paso.id}'`));
  }

  // -------------------------------------------------------------- lienzo

  function aplicarVista() {
    capa.style.transform = `translate(${vista.x}px, ${vista.y}px) scale(${vista.z})`;
  }

  function curva(x1, y1, x2, y2) {
    const dx = Math.max(60, Math.abs(x2 - x1) / 2);
    return `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
  }

  function dibujarLienzo() {
    const filas = Object.fromEntries((validacion.plan || []).map((f) => [f.id, f]));
    const estadoPasos = corrida?.pasos || {};
    for (const n of capa.querySelectorAll('.nodo')) n.remove();
    aristas.replaceChildren();
    ayuda.hidden = flujo.steps.length > 0;

    flujo.steps.forEach((paso, i) => {
      const pos = posicion(paso.id, i);
      const t = tipos[paso.type] || { grupo: '', titulo: paso.type };
      const fila = filas[paso.id];
      const medido = costos.pasos[paso.id]?.tokens || costos.pasos[paso.id]?.costo ? costos.pasos[paso.id] : null;
      const errores = erroresDe(paso);
      const corre = estadoPasos[paso.id]?.estado;
      const nodo = h('div', {
        class: `nodo${seleccion === paso.id ? ' seleccionado' : ''}${errores.length ? ' error' : ''}${corre ? ` corre-${corre}` : ''}`,
        dataset: { id: paso.id }, tabindex: '0', role: 'button', 'aria-label': `Nodo ${paso.id}`,
        style: { left: `${pos.x}px`, top: `${pos.y}px` },
      },
      h('span', { class: 'nodo-orden' }, i + 1),
      h('span', { class: 'puerto entrada-p' }), h('span', { class: 'puerto salida-p' }),
      corre ? h('span', { class: 'nodo-estado' }, estado(corre)) : null,
      h('div', { class: 'nodo-cab' },
        h('span', { class: `icono-nodo ${CLASE_GRUPO[t.grupo] || ''}` }, icono(ICONOS[paso.type] || 'workflows')),
        h('div', { class: 'nodo-titulo' }, h('b', {}, paso.id), h('span', {}, resumenNodo(paso)))),
      h('div', { class: 'nodo-pie' }, ...nodos(
        fila ? pill(fila.costo === 'gratis' ? 'gratis' : fila.costo === 'tokens remotos' ? 'se paga' : 'externo',
          fila.costo === 'gratis' ? 'local' : fila.costo === 'tokens remotos' ? 'remoto' : 'acento') : null,
        fila?.efectos ? pill('pide permiso', 'peligro') : null,
        paso.when ? pill('condicional') : null,
        medido ? pill(`~${fmt.tok(medido.tokens)} tok${medido.costo ? ` · ${fmt.costo(medido.costo)}` : ''}`, '') : null,
        errores.length ? pill(`${errores.length} error`, 'peligro') : null)));
      capa.append(nodo);
      engancharNodo(nodo, paso);
    });

    // Aristas: el orden de ejecucion, y en punteado de donde saca datos cada nodo.
    flujo.steps.forEach((paso, i) => {
      const destino = posicion(paso.id, i);
      if (i > 0) {
        const origen = posicion(flujo.steps[i - 1].id, i - 1);
        const activa = corrida?.pasos?.[paso.id]?.estado === 'en_curso';
        aristas.append(svg('path', { class: `arista${activa ? ' activa' : ''}`,
          d: curva(origen.x + ANCHO, origen.y + ALTO_PUERTO, destino.x, destino.y + ALTO_PUERTO) }));
      }
      for (const ref of referencias(paso)) {
        const j = flujo.steps.findIndex((p) => p.id === ref);
        if (j < 0 || j === i - 1) continue;
        const origen = posicion(ref, j);
        aristas.append(svg('path', { class: 'arista datos', d: curva(origen.x + ANCHO, origen.y + ALTO_PUERTO + 10, destino.x, destino.y + ALTO_PUERTO + 10) }));
      }
    });
  }

  function engancharNodo(nodo, paso) {
    let inicio = null;
    nodo.addEventListener('pointerdown', (e) => {
      e.stopPropagation();
      nodo.setPointerCapture(e.pointerId);
      const pos = posiciones[paso.id];
      inicio = { px: e.clientX, py: e.clientY, x: pos.x, y: pos.y, movio: false };
    });
    nodo.addEventListener('pointermove', (e) => {
      if (!inicio) return;
      const dx = (e.clientX - inicio.px) / vista.z;
      const dy = (e.clientY - inicio.py) / vista.z;
      if (Math.abs(dx) + Math.abs(dy) > 3) inicio.movio = true;
      if (!inicio.movio) return;
      posiciones[paso.id] = { x: Math.round(inicio.x + dx), y: Math.round(inicio.y + dy) };
      nodo.style.left = `${posiciones[paso.id].x}px`;
      nodo.style.top = `${posiciones[paso.id].y}px`;
    });
    nodo.addEventListener('pointerup', () => {
      if (!inicio) return;
      const movio = inicio.movio;
      inicio = null;
      if (movio) {
        const antes = flujo.steps.map((p) => p.id).join();
        reordenarPorX();
        if (flujo.steps.map((p) => p.id).join() !== antes) cambio();
        else guardar(clavePos, posiciones);
        dibujarLienzo();
      } else {
        seleccion = paso.id;
        dibujarLienzo();
        dibujarInspector();
      }
    });
    nodo.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { seleccion = paso.id; dibujarLienzo(); dibujarInspector(); }
      if (e.key === 'Delete') quitar(paso.id);
    });
  }

  // Desplazar el lienzo arrastrando el fondo; zoom con la rueda.
  let arrastre = null;
  lienzo.addEventListener('pointerdown', (e) => {
    if (e.target.closest('.nodo') || e.target.closest('.lienzo-controles') || e.target.closest('.editor-pie')) return;
    arrastre = { px: e.clientX, py: e.clientY, x: vista.x, y: vista.y, movio: false };
    lienzo.setPointerCapture(e.pointerId);
    lienzo.classList.add('arrastrando');
  });
  lienzo.addEventListener('pointermove', (e) => {
    if (!arrastre) return;
    if (Math.abs(e.clientX - arrastre.px) + Math.abs(e.clientY - arrastre.py) > 3) arrastre.movio = true;
    vista.x = arrastre.x + (e.clientX - arrastre.px);
    vista.y = arrastre.y + (e.clientY - arrastre.py);
    aplicarVista();
  });
  lienzo.addEventListener('pointerup', () => {
    if (arrastre && !arrastre.movio && seleccion !== null) { seleccion = null; dibujarLienzo(); dibujarInspector(); }
    arrastre = null;
    lienzo.classList.remove('arrastrando');
  });
  lienzo.addEventListener('wheel', (e) => {
    e.preventDefault();
    const caja = lienzo.getBoundingClientRect();
    const mx = e.clientX - caja.left;
    const my = e.clientY - caja.top;
    const z = Math.min(1.8, Math.max(0.35, vista.z * (e.deltaY < 0 ? 1.1 : 0.9)));
    vista.x = mx - ((mx - vista.x) * z) / vista.z;
    vista.y = my - ((my - vista.y) * z) / vista.z;
    vista.z = z;
    aplicarVista();
  }, { passive: false });
  lienzo.addEventListener('dragover', (e) => { if (e.dataTransfer.types.includes('text/lymi-nodo')) { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; } });
  lienzo.addEventListener('drop', (e) => {
    const tipo = e.dataTransfer.getData('text/lymi-nodo');
    if (!tipo) return;
    e.preventDefault();
    const caja = lienzo.getBoundingClientRect();
    agregar(tipo, { x: Math.round((e.clientX - caja.left - vista.x) / vista.z - ANCHO / 2), y: Math.round((e.clientY - caja.top - vista.y) / vista.z - 30) });
  });

  function encuadrar() {
    if (!flujo.steps.length) { Object.assign(vista, { x: 40, y: 40, z: 1 }); aplicarVista(); return; }
    const xs = flujo.steps.map((p, i) => posicion(p.id, i).x);
    const ys = flujo.steps.map((p, i) => posicion(p.id, i).y);
    const ancho = Math.max(...xs) - Math.min(...xs) + ANCHO + 120;
    const alto = Math.max(...ys) - Math.min(...ys) + 200;
    const caja = lienzo.getBoundingClientRect();
    // Legible antes que completo: si no cabe a 0.8, se ve el principio y se desplaza.
    vista.z = Math.min(1.1, Math.max(0.8, Math.min(caja.width / ancho, caja.height / alto)));
    const centrado = (caja.width - (Math.max(...xs) + ANCHO + Math.min(...xs)) * vista.z) / 2;
    vista.x = ancho * vista.z > caja.width ? 40 - Math.min(...xs) * vista.z : centrado;
    vista.y = (caja.height - (Math.max(...ys) + 120 + Math.min(...ys)) * vista.z) / 2;
    aplicarVista();
  }

  const controles = h('div', { class: 'lienzo-controles' },
    boton('', () => { vista.z = Math.min(1.8, vista.z * 1.15); aplicarVista(); }, 'chico icono-solo', 'zoommas', { 'aria-label': 'Acercar' }),
    boton('', () => { vista.z = Math.max(0.35, vista.z / 1.15); aplicarVista(); }, 'chico icono-solo', 'zoommenos', { 'aria-label': 'Alejar' }),
    boton('', encuadrar, 'chico icono-solo', 'centrar', { 'aria-label': 'Encuadrar' }));
  lienzo.append(controles);

  // -------------------------------------------------------------- inspector

  function control(nombre, esq, valor, requerido, alCambiar) {
    const c = tipoCampo(esq);
    const id = `campo-${nombre}`;
    let el;
    if (c.tipo === 'enum') {
      el = h('select', { class: 'entrada', id },
        c.opcional || !requerido ? h('option', { value: '' }, '(por defecto)') : null,
        c.opciones.map((o) => h('option', { value: String(o), selected: String(o) === String(valor ?? esq.default ?? '') ? true : null }, String(o))));
      el.addEventListener('change', () => alCambiar(el.value === '' ? undefined : el.value));
    } else if (c.tipo === 'bool') {
      el = h('input', { type: 'checkbox', id, checked: (valor ?? esq.default) ? true : null });
      el.addEventListener('change', () => alCambiar(el.checked));
      return h('label', { class: 'casilla', style: { marginBottom: '12px' } }, el, ETIQUETAS[nombre] || nombre);
    } else if (c.tipo === 'numero') {
      el = h('input', { class: 'entrada', id, type: 'number', step: c.entero ? '1' : 'any', value: valor ?? '', placeholder: esq.default ?? '' });
      el.addEventListener('input', () => alCambiar(el.value === '' ? undefined : Number(el.value)));
    } else if (c.tipo === 'lista') {
      el = h('textarea', { class: 'entrada mono', id, rows: 3, placeholder: 'uno por línea',
        value: Array.isArray(valor) ? valor.join('\n') : (valor ?? '') });
      el.addEventListener('input', () => {
        const lineas = el.value.split('\n').map((x) => x.trim()).filter(Boolean);
        alCambiar(lineas.length ? lineas : undefined);
      });
    } else if (c.tipo === 'json') {
      el = h('textarea', { class: 'entrada mono', id, rows: 4, value: valor === undefined ? '' : JSON.stringify(valor, null, 2) });
      el.addEventListener('input', () => {
        if (!el.value.trim()) { alCambiar(undefined); el.classList.remove('invalido'); return; }
        try { alCambiar(JSON.parse(el.value)); el.style.borderColor = ''; } catch { el.style.borderColor = 'var(--peligro)'; }
      });
    } else if (LARGOS.has(nombre)) {
      el = h('textarea', { class: 'entrada', id, rows: nombre === 'prompt' || nombre === 'contenido' ? 6 : 3, value: valor ?? '' });
      el.addEventListener('input', () => alCambiar(el.value === '' && !requerido ? undefined : el.value));
    } else {
      el = h('input', { class: 'entrada', id, value: valor ?? '', placeholder: esq.default ?? '' });
      el.addEventListener('input', () => alCambiar(el.value === '' && !requerido ? undefined : el.value));
    }
    return h('div', { class: 'campo' }, h('label', { class: 'campo-rotulo', for: id }, ETIQUETAS[nombre] || nombre, requerido ? ' *' : ''), el);
  }

  function dibujarInspector() {
    const paso = flujo.steps.find((p) => p.id === seleccion);
    if (!paso) { dibujarAjustesFlujo(); return; }
    const t = tipos[paso.type];
    const fila = (validacion.plan || []).find((f) => f.id === paso.id);
    const medido = costos.pasos[paso.id];
    const salida = corrida?.resultado?.salidas?.[paso.id];
    const errores = erroresDe(paso);
    const comunes = new Set(['id', 'when', 'retries', 'timeout_s']);
    const propios = Object.entries(t.campos).filter(([k]) => !comunes.has(k));
    const actualizar = (campo) => (v) => {
      if (v === undefined) delete paso[campo]; else paso[campo] = v;
      cambio();
      dibujarLienzo();
    };
    const idEntrada = h('input', { class: 'entrada mono', value: paso.id });
    idEntrada.addEventListener('change', () => {
      const nuevo = idEntrada.value.trim();
      if (!/^[A-Za-z_][A-Za-z0-9_]{0,63}$/.test(nuevo) || flujo.steps.some((p) => p !== paso && p.id === nuevo)) {
        idEntrada.value = paso.id;
        return;
      }
      posiciones[nuevo] = posiciones[paso.id];
      delete posiciones[paso.id];
      paso.id = nuevo;
      seleccion = nuevo;
      cambio();
      dibujarLienzo();
    });
    inspector.replaceChildren(...nodos(
      h('h2', {}, h('span', { class: `icono-nodo ${CLASE_GRUPO[t.grupo] || ''}` }, icono(ICONOS[paso.type] || 'workflows')), t.titulo),
      h('p', { class: 'chico suave' }, t.descripcion),
      errores.map((e) => aviso(e, 'error')),
      h('div', { class: 'campo' }, h('label', { class: 'campo-rotulo' }, 'Nombre del nodo *'), idEntrada,
        h('span', { class: 'campo-ayuda' }, `Los nodos siguientes leen su salida con {{ steps.${paso.id}.output }}`)),
      propios.map(([k, esq]) => control(k, esq, paso[k], t.requeridos.includes(k), actualizar(k))),
      h('div', { class: 'seccion' }, 'Costo'),
      h('div', { class: 'fila' }, fila ? pill(fila.costo, fila.costo === 'gratis' ? 'local' : fila.costo === 'tokens remotos' ? 'remoto' : 'acento') : pill('sin validar'),
        fila?.efectos ? pill('pide permiso antes de actuar', 'peligro') : null),
      fila ? h('div', { class: 'chico suave', style: { marginTop: '6px' } }, fila.destino) : null,
      h('div', { class: 'chico', style: { marginTop: '6px' } }, medido
        ? `Medido: ~${fmt.tok(medido.tokens)} tokens${medido.costo ? ` · ${fmt.costo(medido.costo)}` : ''} por corrida (mediana de ${medido.corridas} corridas reales)`
        : 'Sin corridas registradas: el costo real aparece después de ejecutarlo.'),
      h('details', { class: 'plegable', style: { marginTop: '14px' } }, h('summary', {}, 'Condición y reintentos'),
        h('div', {},
          control('when', { type: 'string' }, paso.when, false, actualizar('when')),
          h('div', { class: 'campo-ayuda', style: { marginTop: '-6px', marginBottom: '10px' } }, 'Ej.: steps.clasificar.output.score > 0.7'),
          control('retries', t.campos.retries, paso.retries, false, actualizar('retries')),
          control('timeout_s', t.campos.timeout_s, paso.timeout_s, false, actualizar('timeout_s')))),
      salida !== undefined ? [h('div', { class: 'seccion' }, 'Salida de la última ejecución'), h('pre', { class: 'bloque-codigo envuelto' }, salida)] : null,
      h('div', { class: 'acciones' },
        boton('Duplicar', () => duplicar(paso.id), 'chico'),
        boton('Quitar', () => quitar(paso.id), 'chico peligro', 'basura'))));
  }

  function dibujarAjustesFlujo() {
    const nombre = h('input', { class: 'entrada mono', value: flujo.name });
    nombre.addEventListener('input', () => { flujo.name = nombre.value.trim(); cambio(); });
    const descripcion = h('textarea', { class: 'entrada', rows: 2, value: flujo.description || '' });
    descripcion.addEventListener('input', () => { if (descripcion.value) flujo.description = descripcion.value; else delete flujo.description; cambio(); });
    const entradas = h('textarea', { class: 'entrada mono', rows: 4, value: flujo.inputs ? JSON.stringify(flujo.inputs, null, 2) : '',
      placeholder: '{ "tema": { "type": "string", "description": "…" } }' });
    entradas.addEventListener('input', () => {
      try { const v = entradas.value.trim() ? JSON.parse(entradas.value) : undefined; if (v) flujo.inputs = v; else delete flujo.inputs; entradas.style.borderColor = ''; cambio(); }
      catch { entradas.style.borderColor = 'var(--peligro)'; }
    });
    const integraciones = h('textarea', { class: 'entrada mono', rows: 4, value: flujo.integrations ? JSON.stringify(flujo.integrations, null, 2) : '',
      placeholder: '{ "github": { "type": "mcp", "command": "…" } }' });
    integraciones.addEventListener('input', () => {
      try { const v = integraciones.value.trim() ? JSON.parse(integraciones.value) : undefined; if (v) flujo.integrations = v; else delete flujo.integrations; integraciones.style.borderColor = ''; cambio(); }
      catch { integraciones.style.borderColor = 'var(--peligro)'; }
    });
    const r = validacion.resumen;
    inspector.replaceChildren(...nodos(
      h('h2', {}, icono('workflows'), 'Workflow'),
      h('p', { class: 'chico suave' }, 'Haz clic en un nodo para editarlo. Sin selección, esto es el workflow entero.'),
      validacion.ok ? null : aviso(validacion.error || 'no es válido', 'error'),
      h('div', { class: 'campo' }, h('label', { class: 'campo-rotulo' }, 'Nombre *'), nombre),
      h('div', { class: 'campo' }, h('label', { class: 'campo-rotulo' }, 'Descripción'), descripcion),
      r ? [h('div', { class: 'seccion' }, 'Plan, sin gastar un token'),
        h('div', { class: 'fila' }, pill(`${r.gratis} gratis`, 'local'), pill(`${r.remotos} se pagan`, 'remoto'),
          r.externos ? pill(`${r.externos} externos`, 'acento') : null, pill(`${r.con_efectos} piden permiso`, 'peligro'),
          r.condicionales ? pill(`${r.condicionales} condicionales`) : null),
        costos.corridas ? h('p', { class: 'chico suave' }, `${costos.corridas} corridas reales en el ledger.`) : null] : null,
      h('details', { class: 'plegable', style: { marginTop: '14px' } }, h('summary', {}, 'Entradas'),
        h('div', {}, entradas, h('div', { class: 'campo-ayuda' }, 'Lo que pide el workflow al correr. Se usan con {{ inputs.nombre }}.'))),
      h('details', { class: 'plegable', style: { marginTop: '8px' } }, h('summary', {}, 'Integraciones (MCP y HTTP)'), h('div', {}, integraciones)),
      validacion.yaml ? h('details', { class: 'plegable', style: { marginTop: '8px' } }, h('summary', {}, 'YAML'),
        h('div', {}, h('pre', { class: 'bloque-codigo' }, validacion.yaml))) : null));
  }

  // -------------------------------------------------------------- barra, guardar y ejecutar

  function dibujarBarra() {
    nombreEl.replaceChildren(flujo.name || 'sin nombre', h('span', { class: 'tenue chico' }, ` · ${archivo || 'sin guardar'}${sucio ? ' · cambios sin guardar' : ''}`));
    estadoValidacion.replaceChildren(validacion.ok ? pill('válido', 'local') : pill('con errores', 'peligro'));
    botonGuardar.classList.toggle('primario', sucio);
    botonEjecutar.classList.toggle('primario', !sucio);
    botonEjecutar.disabled = !archivo;
    botonEjecutar.title = archivo ? '' : 'Guárdalo primero';
  }

  async function guardarFlujo() {
    await validar();
    if (!validacion.ok) { seleccion = null; dibujarInspector(); return false; }
    try {
      if (archivo) {
        await api(`workflows/${encodeURIComponent(archivo)}`, { metodo: 'PUT', cuerpo: { flujo } });
      } else {
        const sugerido = `${(flujo.name || 'workflow').replace(/_/g, '-')}.yml`;
        const nombre = prompt('Nombre del archivo', sugerido);
        if (!nombre) return false;
        const r = await api('workflows', { metodo: 'POST', cuerpo: { archivo: nombre, flujo } });
        guardar(`editor:pos:${r.archivo}`, posiciones);
        sucio = false;
        location.hash = `#/workflows/${encodeURIComponent(r.archivo)}`;
        return true;
      }
      sucio = false;
      dibujarBarra();
      mostrarPie(aviso('Guardado. La versión anterior quedó en runs/workflows-anteriores/.', 'ok'));
      return true;
    } catch (err) {
      mostrarPie(aviso(err.message, 'error'));
      return false;
    }
  }

  function mostrarPie(...contenido) {
    pie.hidden = false;
    pie.replaceChildren(h('div', { class: 'fila', style: { marginBottom: '8px' } }, h('b', {}, 'Ejecución'),
      boton('', () => { pie.hidden = true; }, 'chico fantasma icono-solo derecha', 'cruz', { 'aria-label': 'Cerrar' })), ...contenido);
  }

  async function prepararEjecucion() {
    if (sucio && !(await guardarFlujo())) return;
    const entradas = Object.entries(flujo.inputs || {});
    if (!entradas.length) { ejecutar({}); return; }
    const campos = {};
    mostrarPie(
      ...entradas.map(([nombre, spec]) => {
        campos[nombre] = h(spec.type === 'object' ? 'textarea' : 'input', { class: 'entrada', value: spec.default ?? '' });
        return h('div', { class: 'campo' }, h('label', { class: 'campo-rotulo' }, `${nombre}${spec.required === false ? '' : ' *'} · ${spec.type || 'string'}`),
          campos[nombre], spec.description ? h('span', { class: 'campo-ayuda' }, spec.description) : null);
      }),
      boton('Correr', () => {
        const valores = {};
        for (const [n, c] of Object.entries(campos)) if (c.value !== '') valores[n] = c.value;
        ejecutar(valores);
      }, 'primario', 'play'));
  }

  async function ejecutar(entradas) {
    let t;
    try {
      t = await api(`workflows/${encodeURIComponent(archivo)}/correr`, { metodo: 'POST', cuerpo: { entradas } });
    } catch (err) { mostrarPie(aviso(err.message, 'error')); return; }
    dejarDeSeguir?.();
    dejarDeSeguir = seguir(t.id, (tr, err) => {
      if (err) { mostrarPie(aviso(err.message, 'error')); return; }
      corrida = tr;
      dibujarLienzo();
      const r = tr.resultado;
      mostrarPie(...nodos(
        h('div', { class: 'fila' }, estado(tr.estado), h('span', { class: 'chico suave' }, tr.eventos.at(-1)?.replace(/^\S+\s+/, '') || '')),
        tr.pendiente ? tarjetaAprobacion(tr) : null,
        r?.tipo === 'workflow' ? [h('div', { style: { margin: '8px 0' } }, totales(r.totales)),
          r.ok ? aviso('Terminó. Haz clic en un nodo para ver su salida.', 'ok') : aviso(r.detalle, 'error'),
          h('a', { class: 'chico', href: `#/corridas/${r.run_id}` }, `ver la corrida ${r.run_id} en el ledger`)] : null,
        r?.tipo === 'error' ? aviso(r.detalle, 'error') : null));
      if (!ACTIVOS.has(tr.estado)) {
        ctx.refrescarEstado?.();
        api(`workflows/${encodeURIComponent(archivo)}/costos`).then((c) => { costos = c; dibujarLienzo(); if (seleccion) dibujarInspector(); }).catch(() => {});
      }
    });
  }

  const raiz = h('section', { class: 'vista lienzo-completo' }, h('div', { class: 'editor' },
    h('div', { class: 'editor-barra' },
      h('a', { class: 'boton fantasma chico', href: '#/workflows' }, '← Workflows'),
      icono('workflows'), nombreEl, estadoValidacion,
      h('span', { class: 'derecha fila' }, botonGuardar, botonEjecutar)),
    h('div', { class: 'editor-paleta' }, h('div', { class: 'buscar' }, buscar), listaTipos),
    h('div', { class: 'lienzo-marco' }, lienzo, pie),
    inspector));

  window.addEventListener('beforeunload', avisoSalida);
  ctx.alSalir(() => window.removeEventListener('beforeunload', avisoSalida));
  function avisoSalida(e) { if (sucio) { e.preventDefault(); e.returnValue = ''; } }

  dibujarPaleta();
  dibujarBarra();
  dibujarLienzo();
  dibujarInspector();
  aplicarVista();
  if (archivo) api(`workflows/${encodeURIComponent(archivo)}/costos`).then((c) => { costos = c; dibujarLienzo(); }).catch(() => {});
  validar();
  requestAnimationFrame(() => requestAnimationFrame(encuadrar));
  return raiz;
}
