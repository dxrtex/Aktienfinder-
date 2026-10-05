"""Marktstimmung je Aktie: Analysten-Konsens, Kursziel und aktuelle Schlagzeilen (Yahoo Finance), zwischengespeichert.

Wie die Unternehmensbeschreibungen wird das zu Beginn des Scans geholt (Yahoo blockt Einzelabfragen nach dem
großen Kurs-Download): Watchlist zuerst, dann alle Aktien, die beim letzten Scan in der Tabelle standen
(„_want“). Einträge gelten `max_age_days` Tage; je Lauf höchstens `limit` Abfragen bzw. `budget_s` Sekunden.
Die Schlagzeilen werden mit einer einfachen Wortliste grob eingeordnet (positiv / negativ / neutral) –
Kairo bleibt technisch, die Stimmung ist nur ein Zusatz.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

PATH = Path(__file__).resolve().parent.parent / "data" / "sentiment.json"

POS = ("upgrade", "upgraded", "beat", "beats", "tops", "raises", "raised", "record", "surge", "surges", "soar", "soars", "jump",
       "jumps", "rally", "rallies", "strong", "outperform", "buy rating", "bullish", "higher", "gains", "wins", "win ", "approval",
       "approved", "partnership", "expands", "growth", "boost", "boosts", "upbeat", "optimistic", "price target raised", "rebound")
NEG = ("downgrade", "downgraded", "miss", "misses", "cuts", "cut ", "lowers", "lowered", "plunge", "plunges", "slump", "slumps",
       "falls", "fall ", "drop", "drops", "tumble", "tumbles", "weak", "warning", "warns", "lawsuit", "probe", "investigation",
       "bearish", "underperform", "sell rating", "recall", "layoffs", "loss", "losses", "decline", "declines", "concern", "fears",
       "sinks", "slides", "halt", "delay", "delayed", "fraud", "short seller")


def load() -> dict:
    try:
        return json.loads(PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save(cache: dict) -> None:
    PATH.write_text(json.dumps(cache, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def tone(title: str) -> int:
    t = " " + title.lower() + " "
    p = sum(w in t for w in POS)
    n = sum(w in t for w in NEG)
    return 1 if p > n else -1 if n > p else 0


def _news(tk, name: str) -> list[dict]:
    try:
        raw = tk.get_news(count=12) or []
    except Exception:
        raw = []
    key = re.sub(r"[^a-z0-9 ]", " ", (name or "").lower()).split()
    key = [w for w in key if len(w) > 2 and w not in ("inc", "corp", "the", "group", "holdings", "company", "plc", "ltd")][:2]
    out = []
    for n in raw:
        c = n.get("content") or n
        title = c.get("title") or ""
        if not title:
            continue
        url = ((c.get("canonicalUrl") or {}).get("url") or (c.get("clickThroughUrl") or {}).get("url") or c.get("link") or "")
        pub = (c.get("provider") or {}).get("displayName") or c.get("publisher") or ""
        date = c.get("pubDate") or c.get("displayTime") or ""
        if not date and c.get("providerPublishTime"):
            date = datetime.fromtimestamp(c["providerPublishTime"], timezone.utc).isoformat()
        out.append({"t": title[:180], "p": pub[:40], "u": url, "d": str(date)[:10], "s": tone(title),
                    "rel": any(k in title.lower() for k in key) if key else True})
    out.sort(key=lambda x: x["d"], reverse=True)
    rel = [x for x in out if x["rel"]] or out
    return [{k: v for k, v in x.items() if k != "rel"} for x in rel[:5]]


def fetch(tickers: list[str], cache: dict, names: dict | None = None, limit: int = 300, budget_s: float = 480,
          max_age_days: float = 3) -> int:
    import yfinance as yf

    now = time.time()
    order = list(dict.fromkeys(tickers))
    stale = [t for t in order if now - (cache.get(t) or {}).get("ts", 0) > max_age_days * 86400]
    stale.sort(key=lambda t: (cache.get(t) or {}).get("ts", 0))       # fehlende/älteste zuerst, Watchlist vorne (stabil)
    got, start = 0, time.time()
    for t in stale[:limit]:
        if time.time() - start > budget_s:
            break
        tk = yf.Ticker(t)
        try:
            info = tk.get_info() or {}
        except Exception:
            info = {}
        e = {"ts": int(time.time())}
        rk = info.get("recommendationKey")
        if rk and rk != "none":
            e.update(rk=rk, rm=info.get("recommendationMean"), na=info.get("numberOfAnalystOpinions"))
        for k_src, k in (("targetMeanPrice", "tm"), ("targetHighPrice", "th"), ("targetLowPrice", "tl"),
                         ("currentPrice", "cp"), ("shortPercentOfFloat", "sf")):
            if info.get(k_src) is not None:
                e[k] = info[k_src]
        e["news"] = _news(tk, (names or {}).get(t) or info.get("shortName") or "")
        if len(e) > 2 or e["news"]:
            cache[t] = e
            got += 1
        time.sleep(0.25)
    return got


def summary(e: dict | None, close: float | None, sector: dict | None, market: dict | None) -> dict | None:
    """Kompakte Stimmung für die Website: Analysten, Schlagzeilen, Umfeld (Branche + Gesamtmarkt) und Gesamturteil."""
    if not e and not sector and not market:
        return None
    e = e or {}
    out: dict = {}
    score, parts = 0.0, 0
    rm = e.get("rm")
    if rm:
        out["an"] = {"k": e.get("rk"), "m": round(rm, 2), "n": e.get("na")}
        score += 1 if rm <= 2.0 else -1 if rm >= 3.0 else 0
        parts += 1
    if e.get("tm") and close:
        out["tgt"] = {"m": e["tm"], "h": e.get("th"), "l": e.get("tl"), "up": round(e["tm"] / close - 1, 4)}
    news = e.get("news") or []
    if news:
        s = sum(n["s"] for n in news)
        out["news"] = [{**n, "t": n["t"][:140]} for n in news[:3]]
        out["ns"] = 1 if s >= 2 else -1 if s <= -2 else 0
        score += out["ns"]
        parts += 1
    if sector:
        out["sec"] = sector
        score += {"green": 1, "red": -1}.get(sector.get("tone"), 0) * 0.5
    if market:
        out["mkt"] = market
        score += {"green": 1, "red": -1}.get(market.get("tone"), 0) * 0.5
    if e.get("sf"):
        out["sf"] = e["sf"]
    if e.get("ts"):
        out["d"] = datetime.fromtimestamp(e["ts"], timezone.utc).strftime("%Y-%m-%d")
    out["v"] = "pos" if score >= 1.25 else "neg" if score <= -1.25 else "mix"
    return out
