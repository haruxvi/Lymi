"""Condiciones `when:` de los pasos.

Nunca `eval`. La expresion se parsea con `ast` y se recorre con una lista blanca:
comparaciones, `and`/`or`/`not`, literales y rutas dentro de `inputs` y `steps`.
Todo lo demas -- llamadas, aritmetica, lambdas, comprensiones, atributos que
empiecen por `_` -- se rechaza antes de evaluar nada.

El acceso por punto se resuelve como busqueda en diccionario, jamas como
`getattr` sobre objetos de Python. Eso cierra de raiz las fugas del estilo
`().__class__.__bases__`.

Una clave ausente dentro de la salida de un paso vale `None`, y cualquier
comparacion contra `None` es falsa: si un modelo omitio `score`, el paso que
depende de `score > 0.7` se omite en vez de reventar el workflow.
"""

from __future__ import annotations

import ast
import operator
from collections.abc import Mapping, Sequence
from typing import Any

LARGO_MAXIMO = 300
RAICES = frozenset({"inputs", "steps"})

_COMPARADORES = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
    ast.Is: operator.is_,
    ast.IsNot: operator.is_not,
}


class ConditionError(ValueError):
    """Expresion no permitida o mal formada."""


def _parsear(expresion: str) -> ast.expr:
    if not isinstance(expresion, str) or not expresion.strip():
        raise ConditionError("la condicion esta vacia")
    if len(expresion) > LARGO_MAXIMO:
        raise ConditionError(f"la condicion supera {LARGO_MAXIMO} caracteres")
    try:
        return ast.parse(expresion.strip(), mode="eval").body
    except SyntaxError as exc:
        raise ConditionError(f"sintaxis invalida: {exc.msg}") from exc


def _entrar(base: Any, clave: Any) -> Any:
    if base is None:
        return None
    if isinstance(base, Mapping):
        return base.get(clave)
    if isinstance(base, Sequence) and not isinstance(base, str) and isinstance(clave, int):
        return base[clave] if -len(base) <= clave < len(base) else None
    raise ConditionError(f"no se puede acceder a {clave!r} dentro de un {type(base).__name__}")


def _eval(nodo: ast.AST, contexto: Mapping[str, Any]) -> Any:
    if isinstance(nodo, ast.BoolOp):
        if isinstance(nodo.op, ast.And):
            return all(_eval(v, contexto) for v in nodo.values)
        return any(_eval(v, contexto) for v in nodo.values)

    if isinstance(nodo, ast.UnaryOp):
        valor = _eval(nodo.operand, contexto)
        if isinstance(nodo.op, ast.Not):
            return not valor
        if isinstance(nodo.op, ast.USub) and isinstance(valor, (int, float)) and not isinstance(valor, bool):
            return -valor
        raise ConditionError(f"operador unario no permitido: {type(nodo.op).__name__}")

    if isinstance(nodo, ast.Compare):
        izquierda = _eval(nodo.left, contexto)
        for op, derecho in zip(nodo.ops, nodo.comparators, strict=True):
            fn = _COMPARADORES.get(type(op))
            if fn is None:
                raise ConditionError(f"comparador no permitido: {type(op).__name__}")
            valor_derecho = _eval(derecho, contexto)
            try:
                if not fn(izquierda, valor_derecho):
                    return False
            except TypeError:
                # None > 0.7, "a" < 3...: tipos incomparables cuentan como falso.
                return False
            izquierda = valor_derecho
        return True

    if isinstance(nodo, ast.Constant):
        if nodo.value is None or isinstance(nodo.value, (str, int, float, bool)):
            return nodo.value
        raise ConditionError(f"literal no permitido: {type(nodo.value).__name__}")

    if isinstance(nodo, ast.Name):
        if nodo.id not in RAICES:
            raise ConditionError(f"nombre desconocido {nodo.id!r}: usa inputs.* o steps.*")
        return contexto.get(nodo.id)

    if isinstance(nodo, ast.Attribute):
        if nodo.attr.startswith("_"):
            raise ConditionError(f"atributo privado no permitido: {nodo.attr!r}")
        return _entrar(_eval(nodo.value, contexto), nodo.attr)

    if isinstance(nodo, ast.Subscript):
        if not isinstance(nodo.slice, ast.Constant) or not isinstance(nodo.slice.value, (str, int)):
            raise ConditionError("solo se permiten indices literales: x['clave'] o x[0]")
        if isinstance(nodo.slice.value, str) and nodo.slice.value.startswith("_"):
            raise ConditionError("clave privada no permitida")
        return _entrar(_eval(nodo.value, contexto), nodo.slice.value)

    if isinstance(nodo, (ast.List, ast.Tuple)):
        return [_eval(e, contexto) for e in nodo.elts]

    raise ConditionError(f"construccion no permitida en una condicion: {type(nodo).__name__}")


def validar(expresion: str) -> None:
    """Comprueba que la condicion solo usa construcciones permitidas, sin evaluarla."""
    _eval(_parsear(expresion), _ContextoVacio())


class _ContextoVacio(dict):
    """Contexto que acepta cualquier ruta: sirve para validar la forma, no el valor."""

    def get(self, *_: Any) -> None:
        return None


def evaluar(expresion: str, contexto: Mapping[str, Any]) -> bool:
    """Evalua la condicion contra el contexto del workflow."""
    return bool(_eval(_parsear(expresion), contexto))


def referencias(expresion: str) -> set[str]:
    """Rutas `inputs.x` / `steps.id...` que la condicion consulta."""
    rutas: set[str] = set()
    for nodo in ast.walk(_parsear(expresion)):
        partes: list[str] = []
        actual: ast.AST = nodo
        while isinstance(actual, (ast.Attribute, ast.Subscript)):
            if isinstance(actual, ast.Attribute):
                partes.append(actual.attr)
            elif isinstance(actual.slice, ast.Constant):
                partes.append(str(actual.slice.value))
            actual = actual.value
        if isinstance(actual, ast.Name) and actual.id in RAICES and partes:
            rutas.add(".".join([actual.id, *reversed(partes)]))
    return rutas
