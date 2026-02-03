# Shared config defaults and helpers for ControlPod variants.

import os

DEFAULT_MODE = "kclf_v2"
ENV_VAR = "CONTROL_POD_MODE"


# Common/shared defaults (override in variant modules as needed)
LOCAL_ROOT_DIR = "/home/pi"
LOG_DIR = LOCAL_ROOT_DIR + "/logs"


def env_str(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value if value else default


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    if not value:
        return default
    try:
        if value.lower().startswith("0x"):
            return int(value, 16)
        return int(value)
    except ValueError:
        return default

