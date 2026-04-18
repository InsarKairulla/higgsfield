from __future__ import annotations

import importlib
import pkgutil


_LOADED = False


def load_builtin_metrics() -> None:
    global _LOADED
    if _LOADED:
        return
    for module_info in pkgutil.iter_modules(__path__):
        if module_info.name.startswith("_"):
            continue
        importlib.import_module(f"{__name__}.{module_info.name}")
    _LOADED = True

