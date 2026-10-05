"""Kurzbeschreibungen der Unternehmen (Yahoo Finance „longBusinessSummary“), zwischengespeichert.

Yahoo blockt Einzelabfragen nach dem großen Kurs-Download – deshalb werden die Beschreibungen zu Beginn
des Scans geholt: für die Watchlist und alle Aktien, die beim letzten Scan in der Tabelle standen
(„_want“), höchstens `limit` neue je Lauf. Der Cache liegt neben dem Kurs-Cache (actions/cache).
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

PATH = Path(__file__).resolve().parent.parent / "data" / "company.json"


def load() -> dict:
    try:
        return json.loads(PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save(cache: dict) -> None:
    PATH.write_text(json.dumps(cache, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def _short(text: str, max_len: int = 520) -> str:
    """Erste Sätze bis ca. max_len Zeichen."""
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= max_len:
        return text
    cut = text[:max_len]
    end = max(cut.rfind(". "), cut.rfind("; "))
    return (cut[:end + 1] if end > 200 else cut.rsplit(" ", 1)[0] + " …").strip()


def fetch(tickers: list[str], cache: dict, limit: int = 250) -> int:
    import yfinance as yf

    todo = [t for t in dict.fromkeys(tickers) if t not in cache][:limit]
    got = 0
    for t in todo:
        try:
            info = yf.Ticker(t).get_info() or {}
        except Exception:
            info = {}
        summary = info.get("longBusinessSummary")
        if summary:
            cache[t] = {"text": _short(summary), "industry": info.get("industry") or "", "country": info.get("country") or "",
                        "employees": info.get("fullTimeEmployees"), "web": info.get("website") or ""}
            got += 1
        time.sleep(0.25)
    return got
