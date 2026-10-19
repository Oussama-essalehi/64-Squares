"""Configuration loading, project paths and logging setup shared by every pipeline step."""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config.yaml"


@lru_cache(maxsize=4)
def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load ``config.yaml`` (or ``path``) into a dictionary."""
    config_path = Path(path) if path else CONFIG_PATH
    with open(config_path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def project_path(key: str, config: dict[str, Any] | None = None) -> Path:
    """Return the absolute path configured under ``paths.<key>``, creating parent folders."""
    cfg = config or load_config()
    path = PROJECT_ROOT / cfg["paths"][key]
    target = path.parent if path.suffix else path
    target.mkdir(parents=True, exist_ok=True)
    return path


def get_hash_salt() -> str:
    """Read the username hashing salt from ``.env``; refuse to run without one."""
    load_dotenv(PROJECT_ROOT / ".env")
    salt = os.environ.get("HASH_SALT", "")
    if not salt:
        raise RuntimeError("HASH_SALT is empty. Copy .env.example to .env and set a long random value.")
    return salt


def setup_logging(level: int = logging.INFO) -> None:
    """Configure a compact console logger (idempotent)."""
    root = logging.getLogger()
    if root.handlers:
        return
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
