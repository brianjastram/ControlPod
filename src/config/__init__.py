"""
Config selector. Chooses a variant module based on CONTROL_POD_MODE (default kclf_v1).
Re-exports the selected module's public symbols.
"""

import importlib
import os
from typing import Any

from . import base

MODE = os.getenv(base.ENV_VAR, base.DEFAULT_MODE)


def _load_mode(mode: str):
    try:
        return importlib.import_module(f"src.config.{mode}")
    except Exception:
        if mode != base.DEFAULT_MODE:
            return importlib.import_module(f"src.config.{base.DEFAULT_MODE}")
        raise


_cfg = _load_mode(MODE)
MODE = getattr(_cfg, "MODE_NAME", MODE)


def __getattr__(name: str) -> Any:  # pragma: no cover - dynamic export
    if hasattr(_cfg, name):
        return getattr(_cfg, name)
    raise AttributeError(f"config has no attribute {name}")


def __dir__():
    return sorted(set(dir(_cfg)))


# Explicitly export uppercase attributes (constants) and known selectors.
__all__ = [
    name for name in dir(_cfg)
    if name.isupper() or name.endswith("_IMPL") or name.endswith("_DRIVER")
]
