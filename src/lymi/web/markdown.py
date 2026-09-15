"""HTML a markdown limpio, con la libreria estandar.

Se queda con el contenido: el `<main>` o el unico `<article>` si existen, y fuera
menus, pies, formularios y scripts. Tambien fuera todo lo que el navegador no
muestra (`hidden`, `aria-hidden`, `display:none`, letra de tamano cero): un texto
invisible para la persona y visible para el modelo es la forma mas barata de
inyectarle instrucciones.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

_VACIOS = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
)
_OMITIR = frozenset({
    "script", "style", "noscript", "template", "svg", "iframe", "canvas", "form", "button", "select",
    "textarea", "nav", "footer", "aside", "object", "embed", "head", "dialog", "input", "label",
})
_BLOQUES = frozenset({
    "p", "div", "section", "article", "main", "header", "figure", "figcaption", "address", "details",
    "summary", "dl", "dt", "dd", "center", "li", "tr",
})
_OCULTO_ESTILO = re.compile(
    r"display:none|visibility:hidden|font-size:0(?![.\d])|opacity:0(?![.\d])|max-height:0(?![.\d])"
)
_ESPACIOS = re.compile(r"\s+")
_ITEM = re.compile(r"^\s+(?:[-*]|\d+\.)\s")
LIMITE_ENLACES = 500


class Nodo:
    __slots__ = ("attrs", "hijos", "padre", "tag")

    def __init__(self, tag: str, attrs: dict[str, str], padre: Nodo | None) -> None:
        self.tag = tag
        self.attrs = attrs
        self.hijos: list[Nodo | str] = []
        self.padre = padre


class _Constructor(HTMLParser):
    """Arbol tolerante: una etiqueta sin cerrar no rompe el resto del documento."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.raiz = Nodo("#documento", {}, None)
        self._actual = self.raiz

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        nodo = Nodo(tag, {k: v or "" for k, v in attrs}, self._actual)
        self._actual.hijos.append(nodo)
        if tag not in _VACIOS:
            self._actual = nodo

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._actual.hijos.append(Nodo(tag, {k: v or "" for k, v in attrs}, self._actual))

    def handle_endtag(self, tag: str) -> None:
        nodo: Nodo | None = self._actual
        while nodo is not None and nodo.tag != tag:
            nodo = nodo.padre
        if nodo is not None and nodo.padre is not None:
            self._actual = nodo.padre

    def handle_data(self, data: str) -> None:
        self._actual.hijos.append(data)


def _oculto(nodo: Nodo) -> bool:
    a = nodo.attrs
    if "hidden" in a or a.get("aria-hidden", "").lower() == "true":
        return True
    if nodo.tag == "input" and a.get("type", "").lower() == "hidden":
        return True
    return bool(_OCULTO_ESTILO.search(a.get("style", "").replace(" ", "").lower()))


def _buscar(nodo: Nodo, tags: frozenset[str] | set[str]) -> list[Nodo]:
    encontrados: list[Nodo] = []
    pila = [nodo]
    while pila:
        actual = pila.pop()
        for hijo in reversed(actual.hijos):
            if isinstance(hijo, Nodo):
                if hijo.tag in tags:
                    encontrados.append(hijo)
                pila.append(hijo)
    return encontrados


def _texto_plano(nodo: Nodo) -> str:
    partes: list[str] = []
    for hijo in nodo.hijos:
        if isinstance(hijo, str):
            partes.append(hijo)
        elif hijo.tag not in _OMITIR and not _oculto(hijo):
            partes.append("\n" if hijo.tag == "br" else _texto_plano(hijo))
    return "".join(partes)


def _raiz_de_contenido(raiz: Nodo) -> Nodo:
    principales = [n for n in _buscar(raiz, {"main"}) if not _oculto(n)]
    principales += [n for n in _buscar(raiz, {"div", "section"}) if n.attrs.get("role") == "main"]
    if principales:
        return max(principales, key=lambda n: len(_texto_plano(n)))
    articulos = [n for n in _buscar(raiz, {"article"}) if not _oculto(n)]
    if len(articulos) == 1:
        return articulos[0]
    cuerpos = _buscar(raiz, {"body"})
    return cuerpos[0] if cuerpos else raiz


@dataclass(slots=True)
class Documento:
    titulo: str
    descripcion: str
    markdown: str
    enlaces: list[str] = field(default_factory=list)
    idioma: str | None = None


class _Render:
    def __init__(self, base: str, omitir_header: bool) -> None:
        self.base = base
        self.omitir_header = omitir_header
        self.enlaces: dict[str, None] = {}

    def absoluta(self, href: str) -> str | None:
        href = href.strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:", "data:")):
            return None
        partes = urlsplit(urljoin(self.base, href))
        if partes.scheme not in {"http", "https"}:
            return None
        return urlunsplit(partes._replace(fragment=""))

    def hijos(self, nodo: Nodo, pre: bool = False) -> str:
        return "".join(self.nodo(h, pre) for h in nodo.hijos)

    def linea(self, nodo: Nodo) -> str:
        return " ".join(self.hijos(nodo).split())

    def nodo(self, n: Nodo | str, pre: bool = False) -> str:
        if isinstance(n, str):
            return n if pre else _ESPACIOS.sub(" ", n)
        t = n.tag
        if t in _OMITIR or _oculto(n) or (t == "header" and self.omitir_header) or t == "title":
            return ""
        if len(t) == 2 and t[0] == "h" and t[1] in "123456":
            texto = self.linea(n)
            return f"\n\n{'#' * int(t[1])} {texto}\n\n" if texto else ""
        if t == "br":
            return "\n"
        if t == "hr":
            return "\n\n---\n\n"
        if t == "pre":
            codigo = _texto_plano(n).strip("\n")
            return f"\n\n```\n{codigo}\n```\n\n" if codigo.strip() else ""
        if t == "code" and not pre:
            texto = self.hijos(n).strip()
            return f"`{texto}`" if texto else ""
        if t in {"strong", "b"}:
            texto = self.hijos(n).strip()
            return f"**{texto}**" if texto else ""
        if t in {"em", "i"}:
            texto = self.hijos(n).strip()
            return f"*{texto}*" if texto else ""
        if t == "a":
            texto = " ".join(self.hijos(n).split())
            href = self.absoluta(n.attrs.get("href", ""))
            if href and len(self.enlaces) < LIMITE_ENLACES:
                self.enlaces[href] = None
            return f"[{texto}]({href})" if texto and href else texto
        if t == "img":
            alt = " ".join(n.attrs.get("alt", "").split())
            src = self.absoluta(n.attrs.get("src", ""))
            return f"![{alt}]({src})" if alt and src else ""
        if t in {"ul", "ol"}:
            return self.lista(n, ordenada=t == "ol")
        if t == "blockquote":
            interior = limpiar(self.hijos(n))
            return "\n\n" + "\n".join(f"> {linea}" if linea else ">" for linea in interior.splitlines()) + "\n\n"
        if t == "table":
            return self.tabla(n)
        if t in _BLOQUES:
            return f"\n\n{self.hijos(n).strip()}\n\n"
        return self.hijos(n)

    def lista(self, nodo: Nodo, *, ordenada: bool) -> str:
        lineas: list[str] = []
        numero = 0
        for hijo in nodo.hijos:
            if not isinstance(hijo, Nodo) or hijo.tag != "li" or _oculto(hijo):
                continue
            contenido = "\n".join(linea for linea in limpiar(self.hijos(hijo)).splitlines() if linea.strip())
            if not contenido:
                continue
            numero += 1
            primera, *resto = contenido.split("\n")
            lineas.append(f"{numero}. {primera}" if ordenada else f"- {primera}")
            lineas.extend(f"  {linea}" for linea in resto)
        return "\n\n" + "\n".join(lineas) + "\n\n" if lineas else ""

    def tabla(self, nodo: Nodo) -> str:
        matriz = []
        for fila in _buscar(nodo, {"tr"}):
            celdas = [
                " ".join(self.hijos(c).split()).replace("|", "\\|")
                for c in fila.hijos
                if isinstance(c, Nodo) and c.tag in {"td", "th"} and not _oculto(c)
            ]
            if any(celdas):
                matriz.append(celdas)
        if not matriz:
            return ""
        ancho = max(len(f) for f in matriz)
        lineas = []
        for i, fila in enumerate(matriz):
            fila = fila + [""] * (ancho - len(fila))
            lineas.append("| " + " | ".join(fila) + " |")
            if i == 0:
                lineas.append("|" + " --- |" * ancho)
        return "\n\n" + "\n".join(lineas) + "\n\n"


def limpiar(texto: str) -> str:
    """Normaliza espacios y lineas en blanco, sin tocar los bloques de codigo."""
    salida: list[str] = []
    en_codigo = False
    for linea in texto.split("\n"):
        if linea.strip().startswith("```"):
            en_codigo = not en_codigo
            salida.append(linea.strip())
            continue
        if en_codigo:
            salida.append(linea.rstrip())
            continue
        linea = linea.rstrip()
        salida.append(linea if _ITEM.match(linea) or linea.startswith("  ") and salida and salida[-1] else linea.lstrip())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(salida)).strip()


def html_a_markdown(html: str, base_url: str) -> Documento:
    constructor = _Constructor()
    constructor.feed(html)
    constructor.close()
    raiz = constructor.raiz

    titulos = _buscar(raiz, {"title"})
    titulo = " ".join(_texto_plano(titulos[0]).split()) if titulos else ""
    descripcion = ""
    for meta in _buscar(raiz, {"meta"}):
        clave = (meta.attrs.get("name") or meta.attrs.get("property") or "").lower()
        if clave in {"description", "og:description"} and meta.attrs.get("content"):
            descripcion = " ".join(meta.attrs["content"].split())
            break
    htmls = _buscar(raiz, {"html"})
    idioma = htmls[0].attrs.get("lang") or None if htmls else None

    contenido = _raiz_de_contenido(raiz)
    render = _Render(base_url, omitir_header=contenido.tag in {"body", "#documento"})
    markdown = limpiar(render.hijos(contenido))
    if not titulo:
        h1 = _buscar(contenido, {"h1"})
        titulo = " ".join(_texto_plano(h1[0]).split()) if h1 else ""
    return Documento(titulo, descripcion, markdown, list(render.enlaces), idioma)
