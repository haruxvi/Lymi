// Sistema: el ledger (corridas y lo que salio), medir el ahorro contra una linea base,
// modelos y proveedores, apariencia, la galeria de workflows y el detalle de un trabajo.

import {
  ACTIVOS, CLAVES_TINTA, aplicarTema, api, aviso, boton, cabecera, cargando, cifra, costoPill, estado, filaClicable,
  fmt, h, icono, md, nodos, pill, seccion, seguir, tabla, tarjetaAprobacion, tierPill, totales, vacio,
} from './base.js';
import { resultadoAgencia } from './agencia.js';

// ------------------------------------------------------------------ workflows

export async function vistaWorkflows() {
  const d = await api('workflows');
  const tarjeta = (w) => h('a', { class: 'tarjeta', href: `#/workflows/${encodeURIComponent(w.archivo)}` },
    h('div', { class: 'tarjeta-cab' }, icono('workflows'), w.nombre || w.archivo),
    w.error ? aviso('No es un workflow válido: ábrelo para ver por qué.', 'error')
      : [h('div', { class: 'tarjeta-texto' }, w.descripcion || `${w.pasos} pasos`),
        h('div', { class: 'fila', style: { marginTop: '10px' } },
          pill(`${w.pasos} nodos`),
          w.resumen.gratis ? pill(`${w.resumen.gratis} gratis`, 'local') : null,
          w.resumen.remotos ? pill(`${w.resumen.remotos} se pagan`, 'remoto') : null,
          w.resumen.con_efectos ? pill(`${w.resumen.con_efectos} con aprobación`, 'peligro') : null)],
    h('div', { class: 'chico tenue', style: { marginTop: '8px' } }, w.archivo));
  return h('section', { class: 'vista' },
    cabecera('Workflows', 'Automatizaciones por nodos, como n8n, con lo que n8n no tiene: cada nodo dice si corre gratis en tu '
      + 'equipo, si se paga o si pide permiso, y cuánto costó de verdad en corridas anteriores.',
      h('a', { class: 'boton primario', href: '#/workflows/nuevo' }, icono('mas'), 'Nuevo workflow')),
    d.workflows.length ? h('div', { class: 'rejilla' }, d.workflows.map(tarjeta)) : vacio('workflows', `No hay workflows en ${d.carpeta}.`),
    h('p', { class: 'chico tenue', style: { marginTop: '16px' } }, `Cada workflow es un YAML en ${d.carpeta}: el lienzo y el archivo son lo mismo.`));
}

// ------------------------------------------------------------------ proveedores

export async function vistaProveedores(ctx) {
  const raiz = h('section', { class: 'vista' });
  const titulo = () => cabecera('Modelos y proveedores',
    'Qué puede usar lymi con lo que tienes instalado. Nada se da por listo sin comprobarlo.');

  async function dibujar(probar) {
    raiz.replaceChildren(titulo(), cargando(probar ? 'Probando la suscripción con una llamada real…' : 'Revisando…'));
    let d; let modelos;
    try {
      [d, modelos] = await Promise.all([api(`proveedores${probar ? '?probar=1' : ''}`), api('modelos')]);
    } catch (err) { raiz.append(aviso(err.message, 'error')); return; }
    if (!ctx.vigente()) return;
    raiz.replaceChildren(
      titulo(),
      h('div', { class: 'rejilla dos' },
        h('div', { class: 'tarjeta' }, h('div', { class: 'tarjeta-cab' }, icono('pc'), 'En tu equipo', h('span', { class: 'accion' }, d.tier_local ? pill('listo', 'local') : pill('no disponible', 'peligro'))),
          modelos.locales.length ? h('div', { class: 'lista' }, modelos.locales.map((m) => h('div', { class: 'lista-item' },
            h('div', { class: 'lista-cuerpo' }, h('div', { class: 'lista-titulo' }, m.id, m.id === modelos.local_defecto ? ' · por defecto' : ''),
              h('div', { class: 'lista-meta' }, [m.parametros, m.cuantizacion, fmt.bytes(m.bytes)].filter(Boolean).join(' · '))))))
            : h('div', { class: 'vacio-chico' }, modelos.error_local || 'Sin modelos. Instala uno con: ollama pull qwen2.5:3b'),
          h('p', { class: 'chico tenue' }, 'Gratis y privado: el trabajo pesado corre aquí. Cambia el de por defecto con LYMI_LOCAL_MODEL; en el chat eliges por conversación.')),
        h('div', { class: 'tarjeta' }, h('div', { class: 'tarjeta-cab' }, icono('modelo'), 'Remoto', h('span', { class: 'accion' }, d.tier_remoto ? pill('listo', 'local') : pill('no disponible', 'peligro'))),
          modelos.remoto ? [h('div', {}, modelos.remoto), h('div', { class: 'chips', style: { marginTop: '8px' } }, modelos.remotos.map((m) => pill(m.id)))]
            : h('div', { class: 'vacio-chico' }, 'Sin proveedor remoto. Instala Claude Code y usa /login, o define ANTHROPIC_API_KEY.'),
          h('p', { class: 'chico tenue' }, 'Solo se usa cuando tú lo eliges, y todo lo que sale queda en Lo que salió, con los datos sensibles redactados.'))),
      seccion('Voz', 'en tu equipo, sin servicios en la nube'),
      await tarjetaVoz(),
      seccion('Chequeos'),
      tabla([['ESTADO'], ['QUÉ'], ['DETALLE'], ['CÓMO ARREGLARLO']],
        d.chequeos.map((c) => h('tr', {}, h('td', {}, estado(c.estado === 'ok' ? 'ok' : c.estado === 'falta' ? 'falta' : 'fallo')),
          h('td', { class: 'mono' }, c.nombre), h('td', {}, c.detalle), h('td', { class: 'mono chico' }, c.arreglo || '—')))),
      h('div', { class: 'acciones' },
        boton('Probar la suscripción (gasta ~20 tokens)', () => dibujar(true), '', 'rayo'),
        h('span', { class: 'chico tenue' }, d.probado ? 'Suscripción comprobada con una llamada real.'
          : 'Sin probar: el programa existe, pero una sesión caducada se ve igual desde fuera.')));
  }
  await dibujar(false);
  return raiz;
}

async function tarjetaVoz() {
  const v = await api('voz').catch(() => null);
  if (!v) return aviso('No se pudo consultar la voz.', 'error');
  return h('div', { class: 'rejilla dos' },
    h('div', { class: 'tarjeta' }, h('div', { class: 'tarjeta-cab' }, icono('microfono'), 'Dictado',
      h('span', { class: 'accion' }, v.dictado.disponible ? pill(`whisper ${v.dictado.modelo}`, 'local') : pill('falta instalar', 'peligro'))),
    v.dictado.disponible ? h('div', { class: 'chico suave' }, v.dictado.binario)
      : h('div', { class: 'chico suave' }, v.dictado.motivo),
    h('p', { class: 'chico tenue' }, `Para esta máquina (${v.dictado.memoria_gb} GB de RAM) conviene ${v.dictado.sugerido}. `
      + 'whisper.cpp corre sin red; lymi siempre dice qué modelo transcribió.')),
    h('div', { class: 'tarjeta' }, h('div', { class: 'tarjeta-cab' }, icono('altavoz'), 'Lectura en voz alta',
      h('span', { class: 'accion' }, v.lectura.disponible ? pill('lista', 'local') : pill('no disponible', 'peligro'))),
    h('div', { class: 'chico suave' }, v.lectura.disponible ? `Voz del sistema (${v.lectura.motor}).` : 'En Linux instala espeak-ng.'),
    v.lectura.disponible ? h('div', { class: 'acciones' }, boton('Probar', () => api('voz/hablar', { metodo: 'POST', cuerpo: { texto: 'Hola, soy lymi.' } }), 'chico', 'altavoz')) : null));
}

// ------------------------------------------------------------------ medir

function recibo(res) {
  const maximo = Math.max(res.base.tokens, res.lymi.tokens, 1);
  const barra = (rotulo, tokens, clase) => h('div', { class: 'fila', style: { margin: '6px 0' } },
    h('span', { style: { width: '90px' } }, rotulo),
    h('div', { style: { flex: '1', height: '10px', borderRadius: '6px', background: 'var(--superficie-2)' } },
      h('div', { style: { width: `${((100 * tokens) / maximo).toFixed(1)}%`, height: '100%', borderRadius: '6px', background: clase } })),
    h('span', { class: 'num', style: { width: '80px' } }, `${fmt.tok(tokens)} tok`));
  const lineas = [res.ahorro === null ? res.motivo : 'Ambas corridas pasaron su puerta de correctitud.',
    `línea base: ${res.base.puerta}`, `lymi: ${res.lymi.puerta}`];
  if (res.local_tokens) lineas.push(`${fmt.tok(res.local_tokens)} tokens procesados en local: no salieron de tu equipo.`);
  if (res.egress) lineas.push(`${res.egress} llamadas de lymi salieron (destino y hash en Lo que salió).`);
  if (res.suscripcion) lineas.push('Suscripción: se compara en tokens, no en dólares.');
  return h('div', { class: 'tarjeta', style: { marginTop: '12px' } },
    res.demo ? pill('modo demo: no demuestra ahorro real', 'remoto') : null,
    h('div', { class: 'cifra', style: { fontSize: '40px', color: res.ahorro === null ? 'var(--peligro)' : 'var(--local)' } },
      res.ahorro === null ? 'Sin ahorro anunciable' : `−${Math.round(res.ahorro * 100)}%`),
    res.ahorro === null ? null : h('div', { class: 'suave' }, 'tokens remotos frente a la línea base'),
    h('div', { style: { margin: '14px 0' } }, barra('línea base', res.base.tokens, 'var(--texto-3)'), barra('lymi', res.lymi.tokens, 'var(--local)')),
    h('ul', { class: 'chico' }, lineas.map((l) => h('li', {}, l))),
    h('div', { class: 'fila chico tenue' }, h('a', { href: `#/corridas/${res.base.run_id}` }, res.base.run_id), 'vs',
      h('a', { href: `#/corridas/${res.lymi.run_id}` }, res.lymi.run_id), h('span', { class: 'derecha mono' }, res.reproduce)));
}

export async function vistaMedir() {
  const mensaje = h('div', {});
  let real = false;
  const confirmar = h('input', { type: 'checkbox' });
  const calentar = h('input', { type: 'checkbox', checked: true });
  const lanzar = boton('Medir', async () => {
    lanzar.disabled = true;
    try {
      const t = await api('bench', { metodo: 'POST', cuerpo: { tarea: 'snake', demo: !real, calentar: calentar.checked, confirmar: confirmar.checked } });
      location.hash = `#/trabajos/${t.id}`;
    } catch (err) { mensaje.replaceChildren(aviso(err.message, 'error')); lanzar.disabled = false; }
  }, 'primario', 'medir');
  const opcion = (titulo, texto, valor) => h('label', { class: 'tarjeta clicable' },
    h('div', { class: 'fila' }, h('input', { type: 'radio', name: 'modo', checked: valor === real ? true : null,
      onchange: () => { real = valor; } }), h('b', {}, titulo)), h('div', { class: 'tarjeta-texto' }, texto));
  return h('section', { class: 'vista' },
    cabecera('Medir ahorro', 'La misma tarea (un Snake en Python) con la línea base pública y con lymi, contra la misma prueba de '
      + 'correctitud. El recibo solo anuncia ahorro si las dos pasan y ninguna heredó caché de la otra.'),
    h('div', { class: 'rejilla dos' },
      opcion('Demo', 'Respuestas guionadas. No gasta ni demuestra ahorro: sirve para ver el recibo.', false),
      opcion('Real', 'Tus proveedores de verdad: Claude y el modelo local. Tarda unos minutos.', true)),
    h('div', { class: 'acciones' }, h('label', { class: 'casilla' }, calentar, 'Calentar la caché antes (llamada mínima, anotada aparte)'),
      h('label', { class: 'casilla' }, confirmar, 'Entiendo que la medición real gasta tokens')),
    h('div', { class: 'acciones' }, lanzar), mensaje);
}

// ------------------------------------------------------------------ ledger

function tablaCorridas(corridas) {
  return tabla([['CORRIDA'], ['QUÉ'], ['ESTADO'], ['REMOTOS', 'num'], ['LOCALES', 'num'], ['COSTO', 'num'], ['SALIERON', 'num'], ['CUÁNDO']],
    corridas.map((c) => filaClicable(`#/corridas/${c.run_id}`,
      h('td', { class: 'mono' }, c.run_id), h('td', {}, c.task_id, h('span', { class: 'tenue' }, ` · ${c.variant}`)),
      h('td', {}, estado(c.status)), h('td', { class: 'num' }, fmt.tok(c.remote_tokens)), h('td', { class: 'num' }, fmt.tok(c.local_tokens)),
      h('td', { class: 'num' }, fmt.costo(c.cost_usd, c.billing_mode)), h('td', { class: 'num' }, c.egress_calls),
      h('td', { class: 'nowrap' }, fmt.fecha(c.started_at)))));
}

export async function vistaCorridas() {
  const corridas = await api('corridas?limite=300');
  return h('section', { class: 'vista' },
    cabecera('Corridas', 'Todo lo que pasó por un modelo, la red o tu equipo. Cada fila abre sus llamadas: tokens, costo, destino y hash.'),
    corridas.length ? tablaCorridas(corridas) : vacio('corridas', 'El ledger está vacío.'));
}

export async function vistaCorrida(_ctx, id) {
  const c = await api(`corridas/${id}`);
  return h('section', { class: 'vista' },
    h('a', { class: 'volver', href: '#/corridas' }, '← Corridas'),
    cabecera(`${c.task_id} · ${c.variant}`, c.notes || null, estado(c.status)),
    h('div', { class: 'rejilla cifras' },
      cifra('Tokens remotos', fmt.tok(c.remote_tokens), 'remoto', c.remote_cache_tokens ? `${fmt.tok(c.remote_cache_tokens)} de caché` : null),
      cifra('Tokens locales', fmt.tok(c.local_tokens), 'local', 'no salieron de tu equipo'),
      cifra('Costo', fmt.costo(c.cost_usd, c.billing_mode)),
      cifra('Llamadas que salieron', c.egress_calls, '', `${fmt.ms(c.latency_ms)} en total`)),
    seccion(`Llamadas · ${c.n_calls}`),
    c.llamadas.length ? tabla([['#', 'num'], ['PARA QUÉ'], ['PROVEEDOR · MODELO'], ['DÓNDE'], ['ENTRADA', 'num'], ['SALIDA', 'num'],
      ['COSTO', 'num'], ['DURACIÓN', 'num'], ['SALIÓ'], ['REDACTADO', 'num'], ['SHA-256 · TAMAÑO']],
    c.llamadas.map((l) => h('tr', {},
      h('td', { class: 'num' }, l.seq),
      h('td', {}, l.purpose || '—', l.ok ? null : aviso(l.error || 'falló', 'error')),
      h('td', { class: 'mono chico' }, `${l.provider} · ${l.model}`),
      h('td', {}, l.billing_mode === 'local' || l.tier === 'local' ? tierPill('local') : l.tier === 'integracion' ? pill('integración', 'acento') : tierPill('remote')),
      h('td', { class: 'num' }, fmt.tok(l.input_tokens)), h('td', { class: 'num' }, fmt.tok(l.output_tokens)),
      h('td', { class: 'num' }, fmt.costo(l.cost_usd, l.billing_mode)), h('td', { class: 'num' }, fmt.ms(l.latency_ms)),
      h('td', {}, l.egress ? pill('sí', 'remoto') : '—'), h('td', { class: 'num' }, l.redacciones || '—'),
      h('td', { class: 'mono chico' }, l.payload_sha256 ? `${fmt.hash(l.payload_sha256)} · ${fmt.bytes(l.payload_bytes)}` : '—'))))
      : vacio(null, 'Esta corrida no registró llamadas.'),
    h('p', { class: 'chico tenue' }, `corrida ${c.run_id} · ${fmt.fecha(c.started_at)}${c.git_sha ? ` · git ${c.git_sha}` : ''}`
      + ' · el contenido nunca se guarda: solo su SHA-256 y su tamaño'));
}

export async function vistaEgress() {
  const filas = await api('egress?limite=500');
  const bytes = filas.reduce((s, f) => s + (f.payload_bytes || 0), 0);
  const redactados = filas.reduce((s, f) => s + (f.redacciones || 0), 0);
  return h('section', { class: 'vista' },
    cabecera('Lo que salió de tu equipo', 'Cada llamada que envió datos fuera: a dónde, para qué, su huella y su tamaño. Nunca el contenido.'),
    h('div', { class: 'rejilla cifras' },
      cifra('Llamadas que salieron', fmt.entero(filas.length), 'remoto', filas.length >= 500 ? 'las 500 más recientes' : null),
      cifra('Datos enviados', fmt.bytes(bytes)),
      cifra('Datos sensibles redactados', fmt.entero(redactados), 'local', 'reemplazados antes de salir; el proveedor nunca vio el valor')),
    seccion('Registro'),
    filas.length ? tabla([['CUÁNDO'], ['DESTINO'], ['PARA QUÉ'], ['CORRIDA'], ['SHA-256'], ['TAMAÑO', 'num'], ['REDACTADO', 'num'], ['']],
      filas.map((f) => filaClicable(`#/corridas/${f.run_id}`,
        h('td', { class: 'nowrap' }, fmt.fecha(f.ts)), h('td', { class: 'mono chico' }, `${f.provider} · ${f.model}`),
        h('td', {}, f.purpose || '—'), h('td', { class: 'chico' }, `${f.task_id} · ${f.variant}`),
        h('td', { class: 'mono chico' }, fmt.hash(f.payload_sha256)), h('td', { class: 'num' }, fmt.bytes(f.payload_bytes)),
        h('td', { class: 'num' }, f.redacciones || '—'), h('td', {}, estado(f.ok ? 'ok' : 'fallo')))))
      : vacio('escudo', 'Nada salió de tu equipo todavía.'));
}

// ------------------------------------------------------------------ apariencia

export async function vistaApariencia() {
  const datos = await api('tema');
  let actual = { nombre: datos.nombre, tinta: { ...datos.tinta } };
  const mensaje = h('div', {});
  const selectores = {};
  const tarjetas = datos.presets.map((p) => {
    const b = h('button', { type: 'button', class: 'tema', onclick: () => guardar(p.id, p.tinta) },
      h('span', { class: 'muestras', 'aria-hidden': 'true' }, ['papel', 'panel', 'acento', 'local', 'remoto'].map((k) => h('i', { style: { background: p.tinta[k] } }))),
      h('span', {}, p.nombre, p.id === 'sistema' ? h('div', { class: 'chico tenue' }, 'claro u oscuro según tu equipo') : null));
    b.dataset.id = p.id;
    return b;
  });
  const nombres = { papel: 'fondo', panel: 'paneles', texto: 'texto', gris: 'texto suave', acento: 'acento', local: 'local', remoto: 'remoto' };
  const colores = CLAVES_TINTA.map((clave) => {
    const input = h('input', { type: 'color', 'aria-label': `color ${nombres[clave]}` });
    input.addEventListener('input', () => { actual = { nombre: 'personalizado', tinta: { ...actual.tinta, [clave]: input.value } }; pintar(); });
    selectores[clave] = input;
    return h('label', { class: 'color' }, input, nombres[clave]);
  });
  function pintar() {
    aplicarTema(actual.nombre, actual.tinta);
    for (const b of tarjetas) b.classList.toggle('activo', b.dataset.id === actual.nombre);
    for (const clave of CLAVES_TINTA) selectores[clave].value = actual.tinta[clave];
  }
  async function guardar(nombre, tinta) {
    mensaje.replaceChildren();
    try {
      const r = await api('tema', { metodo: 'PUT', cuerpo: { nombre, tinta } });
      actual = { nombre: r.nombre, tinta: { ...r.tinta } };
      pintar();
      mensaje.replaceChildren(aviso(`Guardado en ${datos.ruta}`, 'ok'));
    } catch (err) { mensaje.replaceChildren(aviso(err.message, 'error')); }
  }
  const raiz = h('section', { class: 'vista' },
    cabecera('Apariencia', `Se guarda en ${datos.ruta} y se puede editar a mano.`),
    datos.aviso ? aviso(datos.aviso, 'info') : null,
    seccion('Tema'), h('div', { class: 'rejilla' }, tarjetas),
    seccion('Colores propios'), h('div', { class: 'colores' }, colores),
    h('div', { class: 'acciones' }, boton('Guardar colores', () => guardar('personalizado', actual.tinta), 'primario', 'guardar')),
    mensaje);
  pintar();
  return raiz;
}

// ------------------------------------------------------------------ un trabajo

function resultadoWorkflow(res) {
  return [
    h('div', { style: { margin: '10px 0' } }, totales(res.totales)),
    res.ok ? null : aviso(res.detalle, 'error'),
    tabla([['NODO'], ['ESTADO'], ['DETALLE'], ['DURACIÓN', 'num']],
      res.pasos.map((p) => h('tr', {}, h('td', { class: 'mono' }, p.id), h('td', {}, estado(p.estado)), h('td', {}, p.detalle || '—'),
        h('td', { class: 'num' }, fmt.ms(p.duracion_ms))))),
    Object.entries(res.salidas).map(([paso, valor]) => h('details', { class: 'plegable', style: { marginTop: '8px' } },
      h('summary', {}, `Salida de ${paso}`), h('div', {}, h('pre', { class: 'bloque-codigo envuelto' }, valor)))),
    h('p', { class: 'chico' }, h('a', { href: `#/corridas/${res.run_id}` }, `ver la corrida ${res.run_id} en el ledger`)),
  ];
}

export async function vistaTrabajo(ctx, id) {
  const raiz = h('section', { class: 'vista' }, cargando());
  const parar = seguir(id, (t, err) => {
    if (err) { raiz.replaceChildren(aviso(err.message, 'error')); return; }
    const r = t.resultado;
    raiz.replaceChildren(...nodos(
      cabecera(t.titulo, `Trabajo ${t.tipo} · ${fmt.fecha(t.creado)}`, estado(t.estado)),
      t.pendiente ? tarjetaAprobacion(t) : null,
      r?.tipo === 'recibo' ? recibo(r) : null,
      r?.tipo === 'workflow' ? resultadoWorkflow(r) : null,
      r?.tipo === 'agencia' ? resultadoAgencia(t) : null,
      r?.tipo === 'borrador' && r.ok ? h('div', { class: 'tarjeta' }, h('div', { class: 'chico suave' }, `Para: ${r.para} · ${r.asunto}`), h('div', { class: 'texto-plano' }, r.cuerpo)) : null,
      r?.tipo === 'error' ? aviso(r.detalle, 'error') : null,
      r && r.ok === false && r.tipo !== 'workflow' && r.tipo !== 'agencia' && r.detalle ? aviso(r.detalle, 'error') : null,
      ACTIVOS.has(t.estado) && !t.pendiente ? cargando('En curso… esta página se actualiza sola.') : null,
      seccion('Registro'), h('pre', { class: 'bloque-codigo envuelto' }, t.eventos.join('\n') || '—')));
    if (!ACTIVOS.has(t.estado)) ctx.refrescarEstado?.();
  });
  ctx.alSalir(parar);
  return raiz;
}

export { md, costoPill };
