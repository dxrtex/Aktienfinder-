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
    (DIR / name).write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
