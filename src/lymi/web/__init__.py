"""Lectura de la web hecha por lymi, sin servicios de terceros.

Inspirado en lo que hacen bien los scrapers y los buscadores con respuesta
(pagina a markdown limpio, mapa de un sitio, respuesta con fuentes), pero con las
garantias de lymi:

- **Nada de la red interna.** Cada salto se resuelve y se fija a una IP publica:
  ni `localhost`, ni la LAN, ni el endpoint de metadatos de la nube, ni un DNS
  que cambie entre la comprobacion y la conexion.
- **La URL es egress.** Si una URL o una consulta lleva un secreto o un dato
  personal, no sale. Y cada peticion queda en el ledger.
- **Lo leido es dato, no instruccion.** Se descarta el texto oculto (vector clasico
  de inyeccion), se sanea el Unicode invisible y se avisa si la pagina intenta
  dar ordenes.
- **Citas falsables.** Una respuesta de `investigar` trae frases textuales que se
  buscan en su fuente: lo que no aparece, se marca.
"""

from lymi.web.buscar import Buscador, Resultado, SearxNG, buscador_configurado
from lymi.web.investigar import Informe, Verificacion, investigar, verificar_citas
from lymi.web.markdown import Documento, html_a_markdown
from lymi.web.red import (
    DestinoBloqueado,
    EventoRed,
    Extraccion,
    Mapa,
    Pagina,
    Web,
    WebError,
    es_publica,
    senales_inyeccion,
)

__all__ = [
    "Buscador",
    "DestinoBloqueado",
    "Documento",
    "EventoRed",
    "Extraccion",
    "Informe",
    "Mapa",
    "Pagina",
    "Resultado",
    "SearxNG",
    "Verificacion",
    "Web",
    "WebError",
    "buscador_configurado",
    "es_publica",
    "html_a_markdown",
    "investigar",
    "senales_inyeccion",
    "verificar_citas",
]
