"""从项目根目录加载 .env；由应用入口或独立脚本在 import 其它 backend 模块前调用一次。"""

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_LOADED = False


def environment_file() -> Path | None:
    """Apply python-dotenv's explicit opt-out to Pydantic settings as well."""
    if os.environ.get("PYTHON_DOTENV_DISABLED", "").casefold() in {
        "1",
        "true",
        "t",
        "yes",
        "y",
    }:
        return None
    return PROJECT_ROOT / ".env"


def load_env() -> None:
    global _LOADED
    if _LOADED:
        return
    path = environment_file()
    if path is not None:
        load_dotenv(path)
    _LOADED = True
