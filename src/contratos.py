"""
contratos.py - Decoradores simples de Design by Contract.

Permiten expresar precondiciones, postcondiciones e invariantes sin depender de
librerias externas. Las excepciones por defecto heredan de ValueError para
mantener compatibilidad con las validaciones actuales del dominio.
"""

from __future__ import annotations

from functools import wraps
from inspect import signature
from typing import Callable, Type


class ContractViolation(ValueError):
    """Error base para incumplimientos de contrato."""


class PreconditionError(ContractViolation):
    """La entrada de una funcion no cumple su contrato."""


class PostconditionError(ContractViolation):
    """El resultado de una funcion no cumple su contrato."""


class InvariantError(ContractViolation):
    """El estado de un objeto no cumple sus invariantes."""


def require(
    predicate: Callable[..., bool],
    message: str,
    exception: Type[Exception] = PreconditionError,
):
    """Valida una precondicion antes de ejecutar la funcion decorada."""

    def decorator(func):
        func_signature = signature(func)

        @wraps(func)
        def wrapper(*args, **kwargs):
            bound = func_signature.bind(*args, **kwargs)
            bound.apply_defaults()
            if not predicate(**bound.arguments):
                raise exception(message)
            return func(*args, **kwargs)

        return wrapper

    return decorator


def ensure(
    predicate: Callable[..., bool],
    message: str,
    exception: Type[Exception] = PostconditionError,
):
    """Valida una postcondicion despues de ejecutar la funcion decorada."""

    def decorator(func):
        func_signature = signature(func)

        @wraps(func)
        def wrapper(*args, **kwargs):
            bound = func_signature.bind(*args, **kwargs)
            bound.apply_defaults()
            result = func(*args, **kwargs)
            if not predicate(result=result, **bound.arguments):
                raise exception(message)
            return result

        return wrapper

    return decorator


def invariant(
    predicate: Callable[[object], bool],
    message: str,
    exception: Type[Exception] = InvariantError,
):
    """Comprueba el estado de self al terminar un metodo de instancia."""

    def decorator(method):
        method_signature = signature(method)

        @wraps(method)
        def wrapper(*args, **kwargs):
            bound = method_signature.bind(*args, **kwargs)
            bound.apply_defaults()
            result = method(*args, **kwargs)
            instance = bound.arguments.get("self")
            if instance is None:
                raise exception("No se puede comprobar un invariante sin self.")
            if not predicate(instance):
                raise exception(message)
            return result

        return wrapper

    return decorator
