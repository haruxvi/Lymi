// Copia los estilos de design/estilos/ dentro de cada artboard.
//
// El canvas ejecuta cada .dc.html aislado y no puede cargar hojas externas, asi
// que la fuente de verdad vive aqui (riso.css + pantallas/<nombre>.css) y este
// script la inyecta en el <style data-estilos> de cada artboard.
//
// Tambien vigila la regla que evita los errores del linter de CSS: nunca un
// valor dinamico {{ }} dentro de style="". Los valores que cambian van en
// clases o en atributos SVG.
//
//   node design/estilos/sincronizar.mjs          escribe los artboards
//   node design/estilos/sincronizar.mjs --check  falla si algo quedo desincronizado

import { existsSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { basename, dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ESTILOS = dirname(fileURLToPath(import.meta.url));
const DISENO = dirname(ESTILOS);
const soloRevisar = process.argv.includes('--check');

const BLOQUE = /(<style data-estilos>)[\s\S]*?(<\/style>)/;
const HUECO_EN_STYLE = /style="[^"]*\{\{/g;

const leer = (ruta) => readFileSync(ruta, 'utf8').replace(/\r\n/g, '\n');
const base = leer(join(ESTILOS, 'riso.css'));

let problemas = 0;
const avisar = (mensaje) => {
  console.error(mensaje);
  problemas += 1;
};

const artboards = readdirSync(DISENO).filter((f) => f.endsWith('.dc.html')).sort();

for (const archivo of artboards) {
  const ruta = join(DISENO, archivo);
  const html = leer(ruta);

  if (!BLOQUE.test(html)) {
    avisar(`${archivo}: falta <style data-estilos></style> en <helmet>`);
    continue;
  }

  const huecos = html.match(HUECO_EN_STYLE) ?? [];
  if (huecos.length) {
    avisar(`${archivo}: ${huecos.length} valores {{ }} dentro de style="" (usa una clase o un atributo SVG)`);
  }

  const propia = join(ESTILOS, 'pantallas', `${basename(archivo, '.dc.html').toLowerCase()}.css`);
  const css = [
    '\n/* generado por design/estilos/sincronizar.mjs: editar design/estilos/, no aqui */\n',
    base,
    existsSync(propia) ? `\n${leer(propia)}` : '',
    '  ',
  ].join('');

  // Funcion de reemplazo: el CSS puede traer "$" y no debe interpretarse.
  const nuevo = html.replace(BLOQUE, (_, abre, cierra) => `${abre}${css}${cierra}`);
  if (nuevo === html) continue;

  if (soloRevisar) {
    avisar(`${archivo}: estilos desincronizados (corre sin --check)`);
  } else {
    writeFileSync(ruta, nuevo, 'utf8');
    console.log(`${archivo}: estilos actualizados`);
  }
}

// La interfaz real (`lymi ui`) usa los mismos tokens y componentes que las maquetas:
// una sola fuente para el diseno y para la app.
const RISO_APP = join(DISENO, '..', 'src', 'lymi', 'ui', 'static', 'riso.css');
const cssApp = `/* generado por design/estilos/sincronizar.mjs desde design/estilos/riso.css: no editar aqui */\n${base}`;
if (!existsSync(RISO_APP) || leer(RISO_APP) !== cssApp) {
  if (soloRevisar) {
    avisar('src/lymi/ui/static/riso.css: desincronizado (corre sin --check)');
  } else {
    writeFileSync(RISO_APP, cssApp, 'utf8');
    console.log('src/lymi/ui/static/riso.css: actualizado');
  }
}

if (!problemas) console.log(`ok: ${artboards.length} artboards y la app con estilos al dia, sin {{ }} en style=""`);
process.exit(problemas ? 1 : 0);
