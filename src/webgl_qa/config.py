"""Unified configuration layer — loads default.yaml + game-specific overrides.

Usage:
    from webgl_qa.config import Config

    cfg = Config("example_game")
    model = cfg.get("vision.model")
    threshold = cfg.get("detection.freeze.ssim_threshold", 0.995)
"""

from pathlib import Path
from typing import Any, Optional

import yaml


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
KNOWLEDGE_DIR = PROJECT_ROOT / "knowledge"


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base. Override wins on conflicts."""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _load_yaml(path: Path) -> dict:
    """Load a YAML file, return empty dict on failure."""
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


class Config:
    """Layered configuration: default.yaml → game_info.yaml → runtime overrides.

    Access via dotted keys: cfg.get("detection.freeze.ssim_threshold")
    """

    def __init__(self, game_name: Optional[str] = None):
        self.game_name = game_name

        # Layer 1: global defaults
        self._data = _load_yaml(CONFIG_DIR / "default.yaml")

        # Layer 2: game-specific overrides
        if game_name:
            game_info = _load_yaml(KNOWLEDGE_DIR / game_name / "game_info.yaml")
            self._data = _deep_merge(self._data, game_info)

    def get(self, dotted_key: str, default: Any = None) -> Any:
        """Lookup a value by dotted path (e.g., 'detection.freeze.ssim_threshold')."""
        keys = dotted_key.split(".")
        current = self._data
        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return default
        return current

    def get_section(self, dotted_key: str) -> dict:
        """Get an entire section as a dict. Returns empty dict if not found."""
        result = self.get(dotted_key)
        if isinstance(result, dict):
            return dict(result)
        return {}

    @property
    def raw(self) -> dict:
        """Access the full merged config dict."""
        return self._data


# Cached instances per game
_cache: dict[str, Config] = {}


def get_config(game_name: Optional[str] = None) -> Config:
    """Get or create a Config instance (cached by game_name)."""
    cache_key = game_name or "__default__"
    if cache_key not in _cache:
        _cache[cache_key] = Config(game_name)
    return _cache[cache_key]
