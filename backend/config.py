"""Lädt die zentrale config.yaml als verschachteltes, per Attribut lesbares Objekt."""

from pathlib import Path
from types import SimpleNamespace

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"


def _ns(obj):
    if isinstance(obj, dict):
        return SimpleNamespace(**{k: _ns(v) for k, v in obj.items()})
    return obj


def load_config(path: Path | str = CONFIG_PATH) -> SimpleNamespace:
    with open(path, encoding="utf-8") as f:
        return _ns(yaml.safe_load(f))


def as_dict(ns) -> dict:
    """Konfiguration zurück in ein dict (z. B. für die JSON-Ausgabe)."""
    if isinstance(ns, SimpleNamespace):
        return {k: as_dict(v) for k, v in vars(ns).items()}
    return ns


CONFIG = load_config()
