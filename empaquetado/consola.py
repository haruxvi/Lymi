"""Punto de entrada del ejecutable de terminal (`lymi-cli`) del programa instalado.

Trabaja sobre la misma carpeta de datos que la ventana (ledger, agenda, workflows,
memoria): lo que haces en la terminal se ve en la app y al reves. Para el mapa de
codigo de un repositorio, pasale `--raiz`.
"""

import os

from lymi.escritorio import hogar, preparar_hogar, recursos

if __name__ == "__main__":
    datos = hogar()
    preparar_hogar(datos, recursos())
    os.chdir(datos)

    from lymi.cli import app

    app(prog_name="lymi")
