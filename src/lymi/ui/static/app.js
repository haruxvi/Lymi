// Interfaz de lymi. JavaScript sin dependencias ni red: todo lo que muestra sale de
// la API local, que lee el ledger real.
//
// Regla de seguridad: ningun dato entra al DOM como HTML. Todo pasa por h(), que
// crea nodos de texto; asi un nombre de workflow o la salida de un modelo no
// pueden inyectar marcado. Los estilos dinamicos van por CSSOM (el.style), que la
// CSP permite, nunca por atributos style="".

const TOKEN = document.querySelector('meta[name="lymi-token"]')?.content ?? '';
const CLAVES_TINTA = ['papel', 'panel', 'texto', 'remoto', 'local', 'gris'];
const TEMA_BASE = 'riso-rosa-menta';
const ACTIVOS = new Set(['en_curso', 'esperando']);

// ------------------------------------------------------------------ utilidades

function h(tag, attrs, ...hijos) {
  const el = document.createElement(tag);
  for (const [clave, valor] of Object.entries(attrs || {})) {
    if (valor === null || valor === undefined || valor === false) continue;
    if (clave === 'class') el.className = valor;
    else if (clave === 'style') Object.assign(el.style, valor);
    else if (clave.startsWith('on') && typeof valor === 'function') el.addEventListener(clave.slice(2), valor);
    else el.setAttribute(clave, valor === true ? '' : String(valor));
  }
  for (const hijo of nodos(hijos)) el.append(hijo instanceof Node ? hijo : document.createTextNode(String(hijo)));
  return el;
}

function nodos(...valores) {
  return valores.flat(Infinity).filter((v) => v !== null && v !== undefined && v !== false);
}

async function api(ruta, { metodo = 'GET', cuerpo } = {}) {
  const cabeceras = { 'X-Lymi-Token': TOKEN };
  if (cuerpo !== undefined) cabeceras['Content-Type'] = 'application/json';
  const respuesta = await fetch(`/api/${ruta}`, {
    method: metodo,
    headers: cabeceras,
    body: cuerpo === undefined ? undefined : JSON.stringify(cuerpo),
    cache: 'no-store',
  });
  let datos = null;
  try {
    datos = await respuesta.json();
  } catch {
    // respuesta sin JSON: el mensaje de error usa el codigo
  }
  if (!respuesta.ok) throw new Error(datos?.error || `error ${respuesta.status}`);
  return datos;
}

const fmt = {
  tok(n) {
    const v = Number(n || 0);
    if (v >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
    if (v >= 1e3) return `${(v / 1e3).toFixed(1)}k`;
    return String(v);
  },
  entero: (n) => Number(n || 0).toLocaleString('es'),
  costo(v, billing) {
    if (v === null || v === undefined) return billing === 'subscription' ? 'suscr.' : 'n/d';
    return v < 1 ? `$${v.toFixed(4)}` : `$${v.toFixed(2)}`;
  },
  fecha(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? iso : d.toLocaleString('es', { dateStyle: 'short', timeStyle: 'medium' });
  },
  bytes(b) {
    if (b === null || b === undefined) return '—';
    if (b >= 1048576) return `${(b / 1048576).toFixed(1)} MB`;
    if (b >= 1024) return `${(b / 1024).toFixed(1)} KB`;
    return `${b} B`;
  },
  hash: (s) => (s ? `${s.slice(0, 12)}…` : '—'),
  ms(v) {
    if (v === null || v === undefined) return '—';
    return v >= 1000 ? `${(v / 1000).toFixed(1)} s` : `${v} ms`;
  },
};

// ------------------------------------------------------------------ piezas

const estado = (valor) => h('span', { class: `estado ${valor}` }, String(valor).replace('_', ' '));
const vacio = (...texto) => h('div', { class: 'vacio' }, ...texto);
const aviso = (texto, clase = '') => h('div', { class: `aviso ${clase}`, role: clase === 'error' ? 'alert' : null }, texto);

function cabecera(titulo, sub, ...extra) {
  return h('header', { class: 'vista-cabecera' },
    h('div', {}, h('h1', { class: 'vista-titulo' }, titulo), sub ? h('p', { class: 'vista-sub' }, sub) : null),
    ...extra);
}

function tarjetaCifra(rotulo, valor, clase = '', nota = null) {
  return h('div', { class: 'tarjeta' },
    h('div', { class: 'rotulo' }, rotulo),
    h('div', { class: `cifra ${clase}` }, valor),
    nota ? h('div', { class: 'nota' }, nota) : null);
}

function filaClicable(destino, ...celdas) {
  const ir = () => { location.hash = destino; };
  return h('tr', {
    class: 'clicable',
    tabindex: '0',
    onclick: ir,
    onkeydown: (e) => { if (e.key === 'Enter') ir(); },
  }, ...celdas);
}

function tabla(columnas, filas) {
  return h('div', { class: 'tabla-marco' },
    h('table', { class: 'tabla' },
      h('thead', {}, h('tr', {}, columnas.map(([titulo, clase]) => h('th', { class: clase || null, scope: 'col' }, titulo)))),
      h('tbody', {}, filas)));
}

function claseTier(tier, billing) {
  if (billing === 'local' || tier === 'local') return ['tier-local', 'LOCAL'];
  if (tier === 'integracion') return ['tier-efecto', 'INTEGRACIÓN'];
  return ['tier-remoto', 'REMOTO'];
}

function pillCosto(costo) {
  const clase = costo === 'gratis' ? 'tier-local' : costo === 'tokens remotos' ? 'tier-remoto' : 'tier-efecto';
  return h('span', { class: `pill ${clase}` }, costo.toUpperCase());
}

function tablaCorridas(corridas) {
  return tabla(
    [['CORRIDA'], ['TAREA'], ['VARIANTE'], ['ESTADO'], ['REMOTOS', 'num'], ['LOCALES', 'num'],
      ['COSTO', 'num'], ['EGRESS', 'num'], ['INICIO']],
    corridas.map((c) => filaClicable(`#/corridas/${c.run_id}`,
      h('td', { class: 'mono-chico' }, c.run_id),
      h('td', {}, c.task_id),
      h('td', { class: 'mono-chico' }, c.variant),
      h('td', {}, estado(c.status)),
      h('td', { class: 'num' }, fmt.tok(c.remote_tokens)),
      h('td', { class: 'num' }, fmt.tok(c.local_tokens)),
      h('td', { class: 'num' }, fmt.costo(c.cost_usd, c.billing_mode)),
      h('td', { class: 'num' }, c.egress_calls),
      h('td', { class: 'mono-chico' }, fmt.fecha(c.started_at)))),
  );
}

function listaTrabajos(lista) {
  return tabla([['TRABAJO'], ['ESTADO'], ['CREADO']],
    lista.map((t) => filaClicable(`#/trabajos/${t.id}`,
      h('td', {}, t.titulo), h('td', {}, estado(t.estado)), h('td', { class: 'mono-chico' }, fmt.fecha(t.creado)))));
}

// ------------------------------------------------------------------ tema

function aplicarTema(nombre, tinta) {
  const raiz = document.documentElement.style;
  const variables = {
    '--papel': tinta.papel, '--papel-hondo': tinta.papel, '--tinta': tinta.papel,
    '--panel': tinta.panel, '--superficie': tinta.panel,
    '--texto': tinta.texto, '--crema': tinta.texto, '--texto-suave': tinta.texto,
    '--rosa': tinta.remoto, '--menta': tinta.local, '--lila': tinta.gris, '--gris': tinta.gris,
  };
  for (const [variable, valor] of Object.entries(variables)) {
    // El tema base usa los tokens de riso.css tal cual, con sus matices intermedios.
    if (nombre === TEMA_BASE) raiz.removeProperty(variable);
    else raiz.setProperty(variable, valor);
  }
}

function tomlDe(nombre, tinta) {
  return ['# ~/.config/lymi/theme.toml', `name = "${nombre}"`, '', '[tinta]',
    ...CLAVES_TINTA.map((k) => `${k} = "${tinta[k]}"`)].join('\n');
}

const muestras = (tinta) => h('span', { class: 'muestras', 'aria-hidden': 'true' },
  CLAVES_TINTA.map((k) => h('i', { style: { background: tinta[k] } })));

// ------------------------------------------------------------------ ledger

function dato(rotulo, valor, clase = '') {
  return h('div', { class: 'ledger-dato' },
    h('span', { class: 'ledger-rotulo' }, rotulo),
    h('span', { class: `ledger-cifra ${clase}` }, valor));
}

function botonParada(estaDetenido) {
  const boton = h('button', { class: `boton ${estaDetenido ? 'menta' : 'contorno'} boton-parada`, type: 'button' },
    estaDetenido ? 'Reanudar' : 'Detener todo');
  boton.addEventListener('click', async () => {
    boton.disabled = true;
    try {
      await api(estaDetenido ? 'reanudar' : 'parar', { metodo: 'POST', cuerpo: {} });
    } catch (err) {
      boton.textContent = err.message;
    }
    actualizarLedger();
  });
  return boton;
}

async function actualizarLedger() {
  const barra = document.getElementById('ledger');
  try {
    const r = await api('resumen');
    barra.replaceChildren(...nodos(
      h('span', { class: 'etiqueta rosa' }, 'LEDGER'),
      dato('LOCAL · GRATIS', fmt.tok(r.local_tokens), 'local'),
      dato('REMOTO · SE PAGA', fmt.tok(r.remote_tokens), 'remoto'),
      dato('CORRIDAS', fmt.entero(r.corridas)),
      r.trabajos_activos ? dato('EN CURSO', r.trabajos_activos) : null,
      h('div', { class: 'espaciador' }),
      r.detenido ? h('span', { class: 'sello rosa ledger-sello' }, 'DETENIDO') : null,
      botonParada(r.detenido),
      h('span', { class: `sello ${r.egress_calls ? 'rosa' : 'menta'} ledger-sello` }, `EGRESS ${r.egress_calls}`),
    ));
  } catch (err) {
    barra.replaceChildren(h('span', { class: 'ledger-vacio' }, `sin conexión con lymi: ${err.message}`));
  }
}

// ------------------------------------------------------------------ vistas

async function vistaInicio() {
  const r = await api('resumen');
  const accion = (n, titulo, texto, destino, acento) => h('a', { class: `tarjeta ${acento}`, href: destino },
    h('div', { class: 'tarjeta-n' }, n), h('div', { class: 'tarjeta-titulo' }, titulo), h('div', { class: 'nota' }, texto));
  return h('section', { class: 'vista' },
    h('div', { class: 'inicio-cabeza' },
      h('div', { class: 'trama trama-rosa inicio-trama' }),
      h('div', { class: 'inicio-marca desregistro', 'aria-hidden': 'true' },
        h('span', { class: 'sombra' }, 'lymi'), h('span', { class: 'frente' }, 'lymi')),
      h('h1', { class: 'inicio-tesis' }, 'Todo token, ', h('span', { class: 'resalta rosa' }, 'anotado'),
        '. Todo byte que sale, ', h('span', { class: 'resalta menta' }, 'auditado'), '.')),
    h('div', { class: 'rejilla' },
      tarjetaCifra('CORRIDAS EN EL LEDGER', fmt.entero(r.corridas)),
      tarjetaCifra('TOKENS LOCALES · GRATIS', fmt.tok(r.local_tokens), 'local'),
      tarjetaCifra('TOKENS REMOTOS · SE PAGAN', fmt.tok(r.remote_tokens), 'remoto', 'caché incluida'),
      tarjetaCifra('LLAMADAS QUE SALIERON', fmt.entero(r.egress_calls))),
    h('h2', { class: 'seccion' }, 'Qué hacer'),
    h('div', { class: 'rejilla' },
      accion('01', 'Revisar proveedores', 'Qué está listo en tu máquina y qué falta.', '#/proveedores', 'acento-menta'),
      accion('02', 'Medir', 'Snake con la línea base y con lymi. Emite el recibo.', '#/medir', 'acento-rosa'),
      accion('03', 'Correr un workflow', 'Plan primero: qué cuesta y qué pide aprobación.', '#/workflows', ''),
      accion('04', 'Auditar lo que salió', 'Destino y hash de cada llamada que dejó tu máquina.', '#/egress', '')),
    h('h2', { class: 'seccion' }, 'Últimas corridas'),
    r.ultimas.length ? tablaCorridas(r.ultimas)
      : vacio('El ledger está vacío. Empieza por ', h('a', { href: '#/medir' }, 'Medir'), ' en modo demo: no gasta tokens.'));
}

async function vistaProveedores(ctx) {
  const raiz = h('section', { class: 'vista' });
  const titulo = () => cabecera('Proveedores',
    'Qué puede correr lymi con lo que tienes instalado. Nada se da por listo sin comprobarlo.');

  async function dibujar(probar) {
    raiz.replaceChildren(titulo(), h('p', { class: 'cargando' }, probar ? 'probando la suscripción…' : 'revisando…'));
    let d;
    try {
      d = await api(`proveedores${probar ? '?probar=1' : ''}`);
    } catch (err) {
      raiz.append(aviso(err.message, 'error'));
      return;
    }
    if (!ctx.vigente()) return;
    raiz.replaceChildren(
      titulo(),
      h('div', { class: 'rejilla' },
        tarjetaCifra('TIER LOCAL', d.tier_local ? 'listo' : 'no disponible', d.tier_local ? 'local' : '',
          d.tier_local ? 'El volumen pesado corre gratis en tu GPU.' : 'Sin modelo local, todo el volumen iría al modelo caro.'),
        tarjetaCifra('TIER REMOTO', d.tier_remoto ? 'listo' : 'no disponible', d.tier_remoto ? 'remoto' : '',
          d.tier_remoto ? 'Se puede medir de verdad.' : 'Solo está disponible el modo demo.')),
      h('h2', { class: 'seccion' }, 'Chequeos'),
      tabla([['ESTADO'], ['PROVEEDOR'], ['DETALLE', 'celda-ancha'], ['CÓMO ARREGLARLO']],
        d.chequeos.map((c) => h('tr', {},
          h('td', {}, estado(c.estado)),
          h('td', { class: 'mono-chico' }, c.nombre),
          h('td', {}, c.detalle),
          h('td', { class: 'mono-chico' }, c.arreglo || '—')))),
      h('div', { class: 'acciones' },
        h('button', { class: 'boton contorno', type: 'button', onclick: () => dibujar(true) },
          'Probar la suscripción (gasta ~20 tokens)'),
        h('span', { class: 'campo-ayuda' }, d.probado
          ? 'Suscripción comprobada con una llamada real.'
          : 'Sin probar: el binario existe, pero una sesión caducada se ve igual desde fuera.')),
    );
  }

  await dibujar(false);
  return raiz;
}

async function vistaMedir() {
  const mensaje = h('div', { 'aria-live': 'polite' });
  const radioDemo = h('input', { type: 'radio', name: 'modo', value: 'demo', checked: true });
  const radioReal = h('input', { type: 'radio', name: 'modo', value: 'real' });
  const calentar = h('input', { type: 'checkbox', checked: true });
  const confirmar = h('input', { type: 'checkbox' });
  const opcion = (input, titulo, texto) => h('label', { class: 'opcion' }, input,
    h('span', {}, h('span', { class: 'opcion-titulo' }, titulo), h('span', { class: 'nota' }, texto)));
  const opcionCalentar = opcion(calentar, 'Calentar la caché',
    'Una llamada mínima antes de medir, registrada aparte, para que las dos corridas lean la misma caché.');
  const opcionConfirmar = opcion(confirmar, 'Entiendo que gasta tokens',
    'La medición real usa tu suscripción o tu API y tarda unos minutos.');
  const lanzar = h('button', { class: 'boton primario', type: 'button' }, 'Lanzar medición');

  function sincronizar() {
    const real = radioReal.checked;
    for (const [etiqueta, input] of [[opcionCalentar, calentar], [opcionConfirmar, confirmar]]) {
      input.disabled = !real;
      etiqueta.classList.toggle('deshabilitada', !real);
    }
    lanzar.disabled = real && !confirmar.checked;
  }
  [radioDemo, radioReal, confirmar].forEach((el) => el.addEventListener('change', sincronizar));

  lanzar.addEventListener('click', async () => {
    lanzar.disabled = true;
    mensaje.replaceChildren();
    const real = radioReal.checked;
    try {
      const trabajo = await api('bench', {
        metodo: 'POST',
        cuerpo: { tarea: 'snake', demo: !real, calentar: calentar.checked, confirmar: confirmar.checked },
      });
      location.hash = `#/trabajos/${trabajo.id}`;
    } catch (err) {
      mensaje.replaceChildren(aviso(err.message, 'error'));
      sincronizar();
    }
  });
  sincronizar();

  let recientes = [];
  try {
    recientes = (await api('trabajos')).filter((t) => t.tipo === 'bench');
  } catch {
    // sin lista de trabajos no se bloquea el formulario
  }

  return h('section', { class: 'vista' },
    cabecera('Medir', 'Snake en Python con la línea base pública y con lymi, contra la misma puerta de correctitud. '
      + 'El recibo solo anuncia ahorro si ambas pasan y ninguna heredó caché de la otra.'),
    h('div', { class: 'formulario' },
      h('div', { class: 'opciones', role: 'radiogroup', 'aria-label': 'Modo de medición' },
        opcion(radioDemo, 'Demo', 'Respuestas guionadas. No gasta tokens ni demuestra ahorro: sirve para ver la tubería.'),
        opcion(radioReal, 'Real', 'Tus proveedores de verdad: Claude y el modelo local.')),
      h('div', { class: 'opciones' }, opcionCalentar, opcionConfirmar),
      h('div', { class: 'acciones' }, lanzar),
      mensaje),
    h('h2', { class: 'seccion' }, 'Mediciones de esta sesión'),
    recientes.length ? listaTrabajos(recientes) : vacio('Todavía no lanzaste ninguna desde la interfaz.'));
}

async function vistaCorridas() {
  const corridas = await api('corridas?limite=200');
  return h('section', { class: 'vista' },
    cabecera('Corridas', 'Todo lo que quedó en el ledger. Cada fila abre sus llamadas.'),
    corridas.length ? tablaCorridas(corridas) : vacio('El ledger está vacío.'));
}

async function vistaCorrida(_ctx, id) {
  const c = await api(`corridas/${id}`);
  const nota = c.billing_mode === 'subscription' ? 'Suscripción: se compara en tokens, no en dólares.'
    : c.unpriced_calls ? `${c.unpriced_calls} llamadas sin tarifa: el costo está incompleto.` : null;
  return h('section', { class: 'vista' },
    h('a', { class: 'volver', href: '#/corridas' }, '← corridas'),
    cabecera(`${c.task_id} · ${c.variant}`, c.notes || null, estado(c.status)),
    h('div', { class: 'rejilla' },
      tarjetaCifra('REMOTOS · CACHÉ INCLUIDA', fmt.tok(c.remote_tokens), 'remoto',
        c.remote_cache_tokens ? `${fmt.tok(c.remote_cache_tokens)} de caché` : null),
      tarjetaCifra('LOCALES · NO SALIERON', fmt.tok(c.local_tokens), 'local'),
      tarjetaCifra('COSTO', fmt.costo(c.cost_usd, c.billing_mode), '', nota),
      tarjetaCifra('LLAMADAS QUE SALIERON', c.egress_calls, '', `${fmt.ms(c.latency_ms)} en total`)),
    h('h2', { class: 'seccion' }, `Llamadas · ${c.n_calls}`),
    c.llamadas.length ? tabla(
      [['#', 'num'], ['PROPÓSITO'], ['PROVEEDOR · MODELO'], ['TIER'], ['ENTRADA', 'num'], ['SALIDA', 'num'],
        ['CACHÉ', 'num'], ['COSTO', 'num'], ['DURACIÓN', 'num'], ['SALIÓ'], ['REDACTADO', 'num'], ['SHA-256 · TAMAÑO']],
      c.llamadas.map((l) => {
        const [clase, etiqueta] = claseTier(l.tier, l.billing_mode);
        return h('tr', {},
          h('td', { class: 'num' }, l.seq),
          h('td', {}, l.purpose || '—', l.ok ? null : h('div', { class: 'aviso error' }, l.error || 'falló')),
          h('td', { class: 'mono-chico' }, `${l.provider} · ${l.model}`),
          h('td', {}, h('span', { class: `pill ${clase}` }, etiqueta)),
          h('td', { class: 'num' }, fmt.tok(l.input_tokens)),
          h('td', { class: 'num' }, fmt.tok(l.output_tokens)),
          h('td', { class: 'num' }, fmt.tok(l.cache_read_tokens + l.cache_write_tokens)),
          h('td', { class: 'num' }, fmt.costo(l.cost_usd, l.billing_mode)),
          h('td', { class: 'num' }, fmt.ms(l.latency_ms)),
          h('td', {}, l.egress ? estado('sí') : '—'),
          h('td', { class: 'num' }, l.redacciones || '—'),
          h('td', { class: 'mono-chico' }, l.payload_sha256 ? `${fmt.hash(l.payload_sha256)} · ${fmt.bytes(l.payload_bytes)}` : '—'));
      }))
      : vacio('Esta corrida no registró llamadas.'),
    h('p', { class: 'campo-ayuda' },
      `corrida ${c.run_id} · inicio ${fmt.fecha(c.started_at)}${c.git_sha ? ` · git ${c.git_sha}` : ''}`
      + ' · el payload nunca se guarda: solo su SHA-256 y su tamaño'));
}

async function vistaWorkflows() {
  const datos = await api('workflows');
  const tarjeta = (w) => h('a', { class: 'tarjeta', href: `#/workflows/${encodeURIComponent(w.archivo)}` },
    h('div', { class: 'rotulo' }, w.archivo),
    h('div', { class: 'tarjeta-titulo' }, w.nombre || 'workflow inválido'),
    w.error ? h('div', { class: 'aviso error' }, 'No es un workflow válido: ábrelo para ver por qué.')
      : [h('div', { class: 'nota' }, w.descripcion || `${w.pasos} pasos`),
        h('div', { class: 'acciones' },
          h('span', { class: 'pill tier-local' }, `${w.resumen.gratis} GRATIS`),
          h('span', { class: 'pill tier-remoto' }, `${w.resumen.remotos} REMOTOS`),
          w.resumen.con_efectos ? h('span', { class: 'pill tier-efecto' }, `${w.resumen.con_efectos} APROBACIÓN`) : null)]);
  return h('section', { class: 'vista' },
    cabecera('Workflows', `Archivos YAML de ${datos.carpeta}. Cada paso declara si corre gratis en local, si se paga o si pide aprobación.`),
    datos.workflows.length ? h('div', { class: 'rejilla' }, datos.workflows.map(tarjeta))
      : vacio(`No hay workflows en ${datos.carpeta}.`));
}

async function vistaWorkflow(_ctx, archivo) {
  const w = await api(`workflows/${encodeURIComponent(archivo)}`);
  const volver = h('a', { class: 'volver', href: '#/workflows' }, '← workflows');
  if (w.error) {
    return h('section', { class: 'vista' }, volver,
      cabecera(w.archivo, 'Este archivo no es un workflow válido.'),
      aviso(w.error, 'error'),
      h('pre', { class: 'codigo-bloque' }, w.yaml));
  }

  const campos = {};
  const formulario = Object.entries(w.entradas).map(([nombre, spec]) => {
    const id = `entrada-${nombre}`;
    let control;
    if (spec.type === 'boolean') {
      control = h('select', { class: 'entrada', id },
        h('option', { value: '' }, spec.required ? 'elige…' : '(sin valor)'),
        h('option', { value: 'true' }, 'true'), h('option', { value: 'false' }, 'false'));
    } else if (spec.type === 'number') {
      control = h('input', { class: 'entrada', id, type: 'number', step: 'any' });
    } else {
      control = h('textarea', { class: 'entrada', id, spellcheck: 'false',
        placeholder: spec.type === 'object' ? '{ "clave": "valor" }' : null });
    }
    if (spec.default !== null && spec.default !== undefined) {
      control.value = typeof spec.default === 'string' ? spec.default : JSON.stringify(spec.default);
    }
    campos[nombre] = control;
    return h('div', { class: 'campo' },
      h('label', { class: 'campo-rotulo', for: id }, `${nombre.toUpperCase()}${spec.required ? ' *' : ''} · ${spec.type}`),
      control,
      spec.description ? h('span', { class: 'campo-ayuda' }, spec.description) : null);
  });

  const mensaje = h('div', { 'aria-live': 'polite' });
  const correr = h('button', { class: 'boton primario', type: 'button' }, 'Correr workflow');
  correr.addEventListener('click', async () => {
    correr.disabled = true;
    mensaje.replaceChildren();
    const entradas = {};
    for (const [nombre, control] of Object.entries(campos)) if (control.value !== '') entradas[nombre] = control.value;
    try {
      const trabajo = await api(`workflows/${encodeURIComponent(w.archivo)}/correr`, { metodo: 'POST', cuerpo: { entradas } });
      location.hash = `#/trabajos/${trabajo.id}`;
    } catch (err) {
      mensaje.replaceChildren(aviso(err.message, 'error'));
      correr.disabled = false;
    }
  });

  const r = w.resumen;
  return h('section', { class: 'vista' }, volver,
    cabecera(w.nombre, w.descripcion || w.archivo),
    h('div', { class: 'rejilla' },
      tarjetaCifra('PASOS GRATIS', r.gratis, 'local'),
      tarjetaCifra('CON TOKENS REMOTOS', r.remotos, 'remoto'),
      tarjetaCifra('EXTERNOS', r.externos),
      tarjetaCifra('PIDEN APROBACIÓN', r.con_efectos, '', 'Nada con efectos corre sin que lo apruebes aquí.')),
    h('h2', { class: 'seccion' }, 'Plan · sin gastar un token'),
    tabla([['PASO'], ['TIPO'], ['COSTO'], ['DESTINO'], ['CONDICIÓN'], ['']],
      w.plan.map((p) => h('tr', {},
        h('td', { class: 'mono-chico' }, p.id),
        h('td', { class: 'mono-chico' }, p.tipo),
        h('td', {}, pillCosto(p.costo)),
        h('td', { class: 'mono-chico' }, p.destino),
        h('td', { class: 'mono-chico' }, p.condicion || '—'),
        h('td', {}, p.efectos ? h('span', { class: 'sello rosa sello-chico' }, 'PIDE APROBACIÓN') : null)))),
    h('h2', { class: 'seccion' }, 'Entradas'),
    h('div', { class: 'formulario' },
      formulario.length ? formulario : h('p', { class: 'campo-ayuda' }, 'Este workflow no declara entradas.'),
      h('div', { class: 'acciones' }, correr),
      mensaje),
    h('h2', { class: 'seccion' }, w.archivo),
    h('pre', { class: 'codigo-bloque' }, w.yaml),
    h('p', { class: 'campo-ayuda' }, 'El YAML es la fuente de verdad: hoy se edita el archivo; el lienzo de nodos es el siguiente paso.'));
}

function tarjetaAprobacion(trabajo, refrescar) {
  const p = trabajo.pendiente;
  const mensaje = h('div', { 'aria-live': 'assertive' });
  const botones = [];
  const decidir = async (decision) => {
    botones.forEach((b) => { b.disabled = true; });
    try {
      await api(`trabajos/${trabajo.id}/aprobacion`, { metodo: 'POST', cuerpo: { decision } });
    } catch (err) {
      mensaje.replaceChildren(aviso(err.message, 'error'));
    }
    refrescar();
  };
  botones.push(
    h('button', { class: 'boton tinta', type: 'button', onclick: () => decidir('aprobar') }, 'Aprobar'),
    h('button', { class: 'boton contorno', type: 'button', onclick: () => decidir('siempre') }, 'Siempre para este destino'),
    h('button', { class: 'boton rechazo', type: 'button', onclick: () => decidir('rechazar') }, 'Rechazar'));
  return h('div', { class: 'hoja hoja-app aprobacion', role: 'alertdialog', 'aria-label': `Aprobar ${p.paso}` },
    h('i', { class: 'cinta' }),
    h('span', { class: 'sello rosa sello-hoja' }, 'PIDE APROBACIÓN'),
    h('h2', { class: 'hoja-titulo' }, `${p.paso} quiere ejecutar`),
    h('p', { class: 'hoja-texto' },
      `destino ${p.destino}${p.metodo ? ` · ${p.metodo}` : ''} · si nadie responde en ${Math.round(p.vence_en_s)} s, cuenta como rechazo`),
    h('pre', { class: 'codigo-bloque' }, p.vista),
    h('div', { class: 'acciones' }, botones),
    mensaje);
}

function recibo(res) {
  const maximo = Math.max(res.base.tokens, res.lymi.tokens, 1);
  const barra = (rotulo, tokens, clase) => h('div', { class: 'comp-fila' },
    h('span', { class: 'mono' }, rotulo),
    h('div', { class: 'comp-pista' },
      h('div', { class: `comp-relleno ${clase}`, style: { width: `${((100 * tokens) / maximo).toFixed(1)}%` } })),
    h('span', { class: 'num' }, `${fmt.tok(tokens)} tok`));

  const lineas = [res.ahorro === null ? res.motivo : 'Ambas corridas pasaron su puerta de correctitud.',
    `línea base: ${res.base.puerta}`, `lymi: ${res.lymi.puerta}`];
  if (res.local_tokens) lineas.push(`${fmt.tok(res.local_tokens)} tokens procesados en local: no salieron de tu máquina.`);
  if (res.egress) lineas.push(`${res.egress} llamadas de lymi sí salieron (destino y hash en Egress).`);
  if (res.cache_remota) lineas.push(`Los tokens remotos incluyen ${fmt.tok(res.cache_remota)} de caché.`);
  if (res.suscripcion) lineas.push('Suscripción: se compara en tokens, no en dólares.');
  if (res.sin_tarifa) lineas.push(`${res.sin_tarifa} llamadas sin tarifa: el costo está incompleto.`);

  return h('div', { class: 'hoja hoja-app recibo' },
    h('i', { class: 'cinta' }),
    res.demo ? h('span', { class: 'sello rosa sello-hoja' }, 'MODO DEMO') : null,
    h('div', { class: 'rotulo' }, `RECIBO · ${res.titulo.toUpperCase()}`),
    res.ahorro === null
      ? h('div', { class: 'titular sin-ahorro' }, 'Sin ahorro anunciable')
      : [h('div', { class: 'titular ahorro' }, `−${Math.round(res.ahorro * 100)}%`),
        h('p', { class: 'hoja-texto' }, 'tokens remotos frente a la línea base')],
    h('div', { class: 'comparacion' }, barra('línea base', res.base.tokens, 'base'), barra('lymi', res.lymi.tokens, 'lymi')),
    h('ul', { class: 'lineas-recibo' }, lineas.map((l) => h('li', {}, l))),
    res.demo ? h('p', { class: 'hoja-texto' }, 'Respuestas guionadas: los números son reproducibles pero no demuestran ahorro real.') : null,
    h('div', { class: 'pie-recibo' },
      h('span', {}, h('a', { href: `#/corridas/${res.base.run_id}` }, res.base.run_id), ' vs ',
        h('a', { href: `#/corridas/${res.lymi.run_id}` }, res.lymi.run_id)),
      h('span', {}, `reproduce: ${res.reproduce}`)));
}

function resultadoWorkflow(res) {
  const t = res.totales;
  return [
    h('div', { class: 'rejilla' },
      tarjetaCifra('REMOTOS', fmt.tok(t.remote_tokens), 'remoto'),
      tarjetaCifra('LOCALES', fmt.tok(t.local_tokens), 'local'),
      tarjetaCifra('COSTO', fmt.costo(t.cost_usd, t.billing_mode)),
      tarjetaCifra('LLAMADAS QUE SALIERON', t.egress_calls ?? 0)),
    res.ok ? null : aviso(res.detalle, 'error'),
    h('h2', { class: 'seccion' }, 'Pasos'),
    tabla([['PASO'], ['ESTADO'], ['DETALLE', 'celda-ancha'], ['DURACIÓN', 'num']],
      res.pasos.map((p) => h('tr', {},
        h('td', { class: 'mono-chico' }, p.id),
        h('td', {}, estado(p.estado)),
        h('td', {}, p.detalle || '—'),
        h('td', { class: 'num' }, fmt.ms(p.duracion_ms))))),
    Object.keys(res.salidas).length ? [
      h('h2', { class: 'seccion' }, 'Salidas'),
      Object.entries(res.salidas).map(([paso, valor]) => h('div', { class: 'campo' },
        h('span', { class: 'campo-rotulo' }, paso),
        h('pre', { class: 'codigo-bloque eventos' }, valor))),
    ] : null,
    h('p', { class: 'campo-ayuda' }, h('a', { href: `#/corridas/${res.run_id}` }, `ver la corrida ${res.run_id} en el ledger`)),
  ];
}

function dibujarTrabajo(trabajo, refrescar) {
  const esBench = trabajo.tipo === 'bench';
  return nodos(
    h('a', { class: 'volver', href: esBench ? '#/medir' : '#/workflows' }, esBench ? '← medir' : '← workflows'),
    cabecera(trabajo.titulo, esBench ? 'Medición contra la línea base' : 'Corrida de workflow', estado(trabajo.estado)),
    trabajo.pendiente ? tarjetaAprobacion(trabajo, refrescar) : null,
    trabajo.resultado?.tipo === 'recibo' ? recibo(trabajo.resultado) : null,
    trabajo.resultado?.tipo === 'workflow' ? resultadoWorkflow(trabajo.resultado) : null,
    trabajo.resultado?.tipo === 'error' ? aviso(trabajo.resultado.detalle, 'error') : null,
    ACTIVOS.has(trabajo.estado) && !trabajo.pendiente
      ? h('p', { class: 'cargando' }, 'en curso… esta página se actualiza sola') : null,
    h('h2', { class: 'seccion' }, 'Eventos'),
    h('pre', { class: 'codigo-bloque eventos' }, trabajo.eventos.join('\n') || '—'));
}

async function vistaTrabajo(ctx, id) {
  const raiz = h('section', { class: 'vista' });
  let firma = '';
  let temporizador = null;
  ctx.alSalir(() => clearTimeout(temporizador));

  async function refrescar() {
    clearTimeout(temporizador);
    let trabajo;
    try {
      trabajo = await api(`trabajos/${id}`);
    } catch (err) {
      raiz.replaceChildren(aviso(err.message, 'error'));
      return;
    }
    if (!ctx.vigente()) return;
    const nueva = JSON.stringify(trabajo);
    // Solo se redibuja si algo cambio: asi no se pierde el foco ni la seleccion.
    if (nueva !== firma) {
      firma = nueva;
      raiz.replaceChildren(...dibujarTrabajo(trabajo, refrescar));
    }
    if (ACTIVOS.has(trabajo.estado)) temporizador = setTimeout(refrescar, 1000);
    else actualizarLedger();
  }

  await refrescar();
  return raiz;
}

async function vistaEgress() {
  const filas = await api('egress?limite=500');
  const bytes = filas.reduce((suma, f) => suma + (f.payload_bytes || 0), 0);
  return h('section', { class: 'vista' },
    cabecera('Lo que salió de tu máquina', 'Cada llamada que envió datos fuera: destino, corrida, hash y tamaño. Nunca el contenido.'),
    h('div', { class: 'rejilla' },
      tarjetaCifra('LLAMADAS QUE SALIERON', fmt.entero(filas.length), 'remoto',
        filas.length >= 500 ? 'mostrando las 500 más recientes' : null),
      tarjetaCifra('BYTES ENVIADOS', fmt.bytes(bytes)),
      tarjetaCifra('DATOS REDACTADOS ANTES DE SALIR', fmt.entero(filas.reduce((s, f) => s + (f.redacciones || 0), 0)), 'local',
        'Secretos y datos personales reemplazados por marcadores; el proveedor nunca vio el valor.')),
    h('h2', { class: 'seccion' }, 'Registro'),
    filas.length ? tabla(
      [['FECHA'], ['DESTINO'], ['PROPÓSITO'], ['CORRIDA'], ['SHA-256'], ['TAMAÑO', 'num'], ['REDACTADO', 'num'], ['ESTADO']],
      filas.map((f) => filaClicable(`#/corridas/${f.run_id}`,
        h('td', { class: 'mono-chico' }, fmt.fecha(f.ts)),
        h('td', { class: 'mono-chico' }, `${f.provider} · ${f.model}`),
        h('td', {}, f.purpose || '—'),
        h('td', { class: 'mono-chico' }, `${f.task_id} · ${f.variant}`),
        h('td', { class: 'mono-chico' }, fmt.hash(f.payload_sha256)),
        h('td', { class: 'num' }, fmt.bytes(f.payload_bytes)),
        h('td', { class: 'num' }, f.redacciones || '—'),
        h('td', {}, estado(f.ok ? 'ok' : 'fallo')))))
      : vacio('Nada salió de tu máquina todavía.'));
}

async function vistaApariencia() {
  const datos = await api('tema');
  let actual = { nombre: datos.nombre, tinta: { ...datos.tinta } };
  const toml = h('pre', { class: 'codigo-bloque' });
  const mensaje = h('div', { 'aria-live': 'polite' });
  const selectores = {};

  const tarjetas = datos.presets.map((p) => {
    const boton = h('button', { class: 'tarjeta-tema', type: 'button', 'aria-pressed': 'false',
      onclick: () => guardar(p.id, p.tinta) }, muestras(p.tinta), h('span', {}, p.nombre));
    boton.dataset.id = p.id;
    return boton;
  });

  const colores = CLAVES_TINTA.map((clave) => {
    const input = h('input', { type: 'color', 'aria-label': `color ${clave}` });
    input.addEventListener('input', () => {
      actual = { nombre: 'personalizado', tinta: { ...actual.tinta, [clave]: input.value } };
      pintar();
    });
    selectores[clave] = input;
    return h('label', { class: 'color' }, input, h('span', {}, clave));
  });

  function pintar() {
    aplicarTema(actual.nombre, actual.tinta);
    toml.textContent = tomlDe(actual.nombre, actual.tinta);
    for (const boton of tarjetas) {
      const activa = boton.dataset.id === actual.nombre;
      boton.classList.toggle('activa', activa);
      boton.setAttribute('aria-pressed', String(activa));
    }
    for (const clave of CLAVES_TINTA) selectores[clave].value = actual.tinta[clave];
  }

  async function guardar(nombre, tinta) {
    mensaje.replaceChildren();
    try {
      const r = await api('tema', { metodo: 'PUT', cuerpo: { nombre, tinta } });
      actual = { nombre: r.nombre, tinta: { ...r.tinta } };
      pintar();
      mensaje.replaceChildren(aviso(`Guardado en ${datos.ruta}`, 'ok'));
    } catch (err) {
      mensaje.replaceChildren(aviso(err.message, 'error'));
    }
  }

  const raiz = h('section', { class: 'vista' },
    cabecera('Apariencia', `Tintas de la interfaz. Se guardan en ${datos.ruta} y se pueden editar a mano.`),
    datos.aviso ? aviso(datos.aviso, 'error') : null,
    h('h2', { class: 'seccion' }, 'Tintas'),
    h('div', { class: 'rejilla' }, tarjetas),
    h('h2', { class: 'seccion' }, 'Colores propios'),
    h('div', { class: 'colores' }, colores),
    h('div', { class: 'acciones' },
      h('button', { class: 'boton primario', type: 'button', onclick: () => guardar('personalizado', actual.tinta) }, 'Guardar colores')),
    mensaje,
    h('h2', { class: 'seccion' }, 'theme.toml'),
    toml);
  pintar();
  return raiz;
}

// ------------------------------------------------------------------ enrutador

const RUTAS = [
  [/^#\/inicio$/, vistaInicio, 'inicio'],
  [/^#\/proveedores$/, vistaProveedores, 'proveedores'],
  [/^#\/medir$/, vistaMedir, 'medir'],
  [/^#\/corridas$/, vistaCorridas, 'corridas'],
  [/^#\/corridas\/([0-9a-f]{12})$/, vistaCorrida, 'corridas'],
  [/^#\/workflows$/, vistaWorkflows, 'workflows'],
  [/^#\/workflows\/([A-Za-z0-9._%-]+)$/, vistaWorkflow, 'workflows'],
  [/^#\/egress$/, vistaEgress, 'egress'],
  [/^#\/apariencia$/, vistaApariencia, 'apariencia'],
  [/^#\/trabajos\/([0-9a-f]{10})$/, vistaTrabajo, null],
];

let generacion = 0;
let limpieza = null;

function marcarNav(seccion) {
  for (const enlace of document.querySelectorAll('#nav .nav-item')) {
    const activo = enlace.dataset.ruta === seccion;
    enlace.classList.toggle('activo', activo);
    if (activo) enlace.setAttribute('aria-current', 'page');
    else enlace.removeAttribute('aria-current');
  }
  document.title = seccion ? `lymi · ${seccion}` : 'lymi';
}

async function navegar() {
  if (limpieza) {
    limpieza();
    limpieza = null;
  }
  const hash = location.hash || '#/inicio';
  const ruta = RUTAS.find(([patron]) => patron.test(hash));
  if (!ruta) {
    location.replace('#/inicio');
    return;
  }
  const [patron, vista, seccion] = ruta;
  const parametros = hash.match(patron).slice(1).map(decodeURIComponent);
  const miGeneracion = ++generacion;
  const contexto = {
    alSalir: (fn) => { limpieza = fn; },
    vigente: () => miGeneracion === generacion,
  };
  marcarNav(seccion);

  const contenedor = document.getElementById('vista');
  contenedor.replaceChildren(h('p', { class: 'cargando' }, 'cargando…'));
  try {
    const nodo = await vista(contexto, ...parametros);
    if (miGeneracion !== generacion) return;
    contenedor.replaceChildren(nodo);
    contenedor.scrollTop = 0;
    contenedor.focus({ preventScroll: true });
  } catch (err) {
    if (miGeneracion !== generacion) return;
    contenedor.replaceChildren(aviso(`No se pudo cargar: ${err.message}`, 'error'));
  }
}

async function iniciar() {
  try {
    const t = await api('tema');
    aplicarTema(t.nombre, t.tinta);
  } catch {
    // sin tema guardado se usan los tokens de riso.css
  }
  window.addEventListener('hashchange', navegar);
  actualizarLedger();
  setInterval(actualizarLedger, 8000);
  navegar();
}

iniciar();
