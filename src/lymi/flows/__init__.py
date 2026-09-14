"""Workflows declarativos: pasos en YAML, cada uno con su tier y su costo a la vista.

Modulos:
    schema     -- forma del workflow y todo lo que se valida sin ejecutar
    template   -- `{{ ruta }}`, busqueda pura, sin ejecucion de codigo
    condition  -- `when:` con lista blanca estricta sobre `ast`
    nodes      -- ejecucion de cada tipo de paso
    engine     -- orden, condiciones, aprobaciones, reintentos, ledger
    plan       -- que haria el workflow, sin gastar un token
"""
