# Politica de seguridad

lymi maneja credenciales de proveedores, registra que datos salen de tu maquina y
puede ejecutar pasos con efectos. Un fallo en cualquiera de esas areas es grave.

## Versiones soportadas

El proyecto esta en alfa (`0.0.x`). Solo se corrige la rama `main`.

## Reportar una vulnerabilidad

**No abras un issue publico.** Usa el reporte privado de GitHub:
pestana **Security** del repositorio → **Report a vulnerability**.

Incluye, si puedes:

- commit o version afectada,
- pasos para reproducirlo,
- impacto (que datos quedan expuestos o que accion se ejecuta sin permiso).

## Lo que mas interesa

- Secretos que terminen en SQLite, logs, YAML, prompts o vistas previas.
- Payloads persistidos: el ledger solo debe guardar hash y tamano.
- Un tier "local" que envie datos fuera de loopback sin opt-in explicito.
- Plantillas o condiciones de workflows que ejecuten codigo.
- Pasos con efectos que corran sin aprobacion, o que se reintenten.
- Tokens OAuth accesibles fuera del almacen del sistema (`keyring`).
