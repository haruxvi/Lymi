## Que cambia y por que

<!-- El por que importa mas que el que. Si arregla un fallo, cual era la causa raiz. -->

## Como se verifico

- [ ] `uv run --extra dev pytest -q`
- [ ] `uv run --extra dev ruff check src tests`
- [ ] `node design/estilos/sincronizar.mjs --check` (si toca `design/`)
- [ ] Si afirma un ahorro: ids de corrida y comando para reproducirlo

## Antes de pedir revision

- [ ] Sin secretos, payloads ni datos personales en el diff
- [ ] Codigo de terceros solo con licencia permisiva y anotado en `THIRD_PARTY_NOTICES.md`
- [ ] Documentacion actualizada (`docs/PENDIENTES.md`, `docs/BITACORA.md`) si cambia el estado
