# Contribuir a lymi

Gracias por el interes. lymi existe para que lo que afirma se pueda verificar, asi
que las reglas giran en torno a eso.

## Preparar el entorno

```bash
uv sync --extra dev
```

Requiere Python 3.12 (via `uv`) y Node 22 para el script de estilos de `design/`.

## Antes de abrir un PR

```bash
uv run --extra dev pytest -q
uv run --extra dev ruff check src tests
node design/estilos/sincronizar.mjs --check
```

La CI corre lo mismo; un PR en rojo no se revisa.

## Reglas

1. **Nada sin prueba.** Una funcionalidad no esta hecha hasta que una prueba la
   ejercita.
2. **Toda llamada a un modelo o integracion pasa por el ledger.**
3. **Nunca se persisten payloads ni secretos.** Solo hash y tamano; secretos en
   variables de entorno o `keyring`.
4. **Ningun texto ajeno ejecuta codigo.** Nada de `eval` ni plantillas completas.
5. **Afirmaciones de ahorro solo con corrida reproducible**: ids de corrida y el
   comando para repetirla.
6. **Licencias.** Solo se incorpora codigo MIT, BSD o Apache-2.0, con atribucion en
   `THIRD_PARTY_NOTICES.md`. Codigo sin licencia no se copia: solo ideas.
7. **Diseno.** Los estilos viven en `design/estilos/`; nunca valores `{{ }}` dentro
   de `style=""`.
8. **Idioma.** Codigo, comentarios y documentacion en espanol. Los comentarios
   explican el por que, no el que.

## Commits

Mensajes cortos, en imperativo y en espanol: `agrega calentamiento de cache al bench`.

## Licencia de los aportes

Al contribuir aceptas que tu aporte se publique bajo la licencia Apache-2.0 del
proyecto.
