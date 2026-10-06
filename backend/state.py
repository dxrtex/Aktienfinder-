"""Dauerhafter Zustand zwischen den Scans (Branch „kairo-data“, im Workflow als Ordner ./state eingebunden).

- signals.json   Live-Bilanz: jedes Signal mit Trade-Plan und laufend nachgeführtem Ergebnis
- last.json      Stand des letzten Scans (Treffer, Fast-Treffer, erfüllte Kriterien) – für „neu seit gestern“
- telegram.json  Telegram: Update-Offset, Chat, synchronisierte Merkliste/Depot, zuletzt gesendet
"""

from __future__ import annotations

import json
from pathlib import Path

from .config import ROOT

DIR = ROOT / "state"


def load(name: str, default):
    try:
        return json.loads((DIR / name).read_text(encoding="utf-8"))
    except Exception:
        return default


def save(name: str, obj) -> None:
    if not DIR.exists():
        return                                    # lokal/ohne Zustands-Branch: nichts speichern
    (DIR / name).write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=_py), encoding="utf-8")


def _py(v):
    """numpy-Zahlen (z. B. int64 aus Index-Rechnungen) → JSON-taugliche Python-Werte."""
    import numpy as np
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating):
        return float(v)
    if isinstance(v, np.bool_):
        return bool(v)
    raise TypeError(f"nicht speicherbar: {type(v).__name__}")
