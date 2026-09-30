"""Every public function and method in talos.web has a docstring (CLAUDE.md conventions).

Protocol methods (`Store`, `Driver`) and their implementations are exempt:
the protocol's class docstring describes the interface.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil

import pytest

import talos.web


def web_modules() -> list[str]:
    return sorted(
        info.name
        for info in pkgutil.walk_packages(talos.web.__path__, prefix="talos.web.")
        if not info.name.endswith("__main__")
    )


def protocol_methods() -> set[str]:
    """Method names declared by the web layer's Protocol classes."""
    names: set[str] = set()
    for module_name in web_modules():
        for obj in vars(importlib.import_module(module_name)).values():
            if inspect.isclass(obj) and getattr(obj, "_is_protocol", False):
                if obj.__module__ == module_name:
                    names.update(a for a in vars(obj) if not a.startswith("_"))
    return names


def public_callables(module_name: str) -> list[tuple[str, object]]:
    module = importlib.import_module(module_name)
    exempt = protocol_methods()
    out: list[tuple[str, object]] = []
    for name, obj in vars(module).items():
        if name.startswith("_") or getattr(obj, "__module__", None) != module_name:
            continue
        if inspect.isfunction(obj):
            out.append((name, obj))
        elif inspect.isclass(obj):
            for attr, member in vars(obj).items():
                if attr.startswith("_") or attr in exempt or not inspect.isfunction(member):
                    continue
                out.append((f"{name}.{attr}", member))
    return out


@pytest.mark.parametrize("module_name", web_modules())
def test_public_functions_have_docstrings(module_name):
    missing = [name for name, obj in public_callables(module_name) if not inspect.getdoc(obj)]
    assert missing == [], f"{module_name}: no docstring on {missing}"
