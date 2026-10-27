"""Non-invoking shape checks for injected private-writer collaborators."""
from __future__ import annotations

import inspect


def has_static_callable_method(dependency: object, name: str) -> bool:
    """Check a declared method without binding or evaluating dependency descriptors."""
    if type(name) is not str or not name or name != name.strip():
        return False
    try:
        member = inspect.getattr_static(dependency, name, None)
    except Exception:
        return False
    return callable(member)
