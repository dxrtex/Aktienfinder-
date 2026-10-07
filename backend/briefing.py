"""Frische Schlagzeilen für das Tagesbriefing der App (site/data/briefing.json).

Anders als sentiment.py (Cache über mehrere Tage, nur Datum) holt dieses Modul bei jedem Scan die Nachrichten der
letzten ~36 Stunden mit Uhrzeit: für die Watchlist und die per Telegram synchronisierte Merkliste/Depot, dazu
marktweite Nachrichten (Notenbanken, Zinsen, Inflation, Zölle …) über die großen Indizes.
Muss vor dem großen Kurs-Download laufen – danach blockt Yahoo Einzelabfragen oft.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from .sentiment import tone

MACRO = ("fed ", "fed's", "federal reserve", "fomc", "powell", "ecb", "lagarde", "bank of japan", "boj", "bank of england",
         "rate cut", "rate hike", "rates", "interest rate", "inflation", "cpi", "pce", "jobs report", "payroll", "unemployment",
         "tariff", "recession", "treasury", "yields", "gdp", "central bank", "shutdown", "stimulus", "opec", "oil price")
INDICES = ("^GSPC", "^IXIC", "^GDAXI", "^STOXX50E")


def _parse(raw, hours: float) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    out = []
    for n in raw or []:
        c = n.get("content") or n
        title = (c.get("title") or "").strip()
        if not title:
            continue
        d = c.get("pubDate") or c.get("displayTime") or ""
        try:
            dt = datetime.fromisoformat(d.replace("Z", "+00:00")) if d else datetime.fromtimestamp(c["providerPublishTime"], timezone.utc)
        except Exception:
            continue
        if dt < cutoff:
            continue
        url = ((c.get("canonicalUrl") or {}).get("url") or (c.get("clickThroughUrl") or {}).get("url") or c.get("link") or "")
        out.append({"t": title[:180], "p": ((c.get("provider") or {}).get("displayName") or c.get("publisher") or "")[:40],
                    "u": url, "d": dt.astimezone(timezone.utc).isoformat(timespec="minutes"), "s": tone(title)})
    out.sort(key=lambda x: x["d"], reverse=True)
    return out


def _translate_one(text: str) -> str | None:
    import requests

    try:
        r = requests.get("https://translate.googleapis.com/translate_a/single",
                         params={"client": "gtx", "sl": "auto", "tl": "de", "dt": "t", "q": text}, timeout=8)
        if r.ok:
            j = r.json()
            if (j[2] if len(j) > 2 else "") == "de":
                return None                              # schon deutsch
            out = "".join(seg[0] for seg in j[0] if seg and seg[0]).strip()
            if out:
                return out
    except Exception:
        pass
    try:
        r = requests.get("https://api.mymemory.translated.net/get", params={"q": text, "langpair": "en|de"}, timeout=8)
        if r.ok:
            out = ((r.json().get("responseData") or {}).get("translatedText") or "").strip()
            if out and "MYMEMORY WARNING" not in out.upper() and out.lower() != text.lower():
                return out
    except Exception:
        pass
    return None


def translate(items: list[dict], budget_s: float = 60) -> int:
    """Schlagzeilen ins Deutsche übersetzen: t = Deutsch, o = Original. Ohne Erfolg bleibt der Originaltitel."""
    start, done, cache = time.time(), 0, {}
    for x in items:
        if time.time() - start > budget_s:
            break
        if x["t"] not in cache:
            cache[x["t"]] = _translate_one(x["t"])
            time.sleep(0.15)
        de = cache[x["t"]]
        if de:
            x["o"], x["t"] = x["t"], de[:200]
            done += 1
    return done


def build(tickers: list[str], names: dict | None = None, hours: float = 36, budget_s: float = 150, per: int = 3) -> dict:
    import yfinance as yf

    names = names or {}
    out = {"generated": datetime.now(timezone.utc).isoformat(timespec="minutes"), "hours": hours, "stocks": {}, "market": []}
    start = time.time()
    for t in list(dict.fromkeys(tickers)):
        if time.time() - start > budget_s:
            break
        try:
            items = _parse(yf.Ticker(t).get_news(count=10), hours)
        except Exception:
            items = []
        key = [w for w in "".join(ch if ch.isalnum() or ch == " " else " " for ch in (names.get(t) or "").lower()).split()
               if len(w) > 2 and w not in ("inc", "corp", "the", "group", "holdings", "company", "plc", "ltd", "aktiengesellschaft")][:2]
        rel = [x for x in items if not key or any(k in x["t"].lower() for k in key)]
        if rel:
            out["stocks"][t] = rel[:per]
        time.sleep(0.2)
    seen, market = set(), []
    for sym in INDICES:
        try:
            items = _parse(yf.Ticker(sym).get_news(count=20), hours)
        except Exception:
            items = []
        for x in items:
            k = x["t"].lower()
            if k in seen or not any(m in " " + k + " " for m in MACRO):
                continue
            seen.add(k)
            market.append(x)
        time.sleep(0.2)
    market.sort(key=lambda x: x["d"], reverse=True)
    out["market"] = market[:6]
    out["translated"] = translate(out["market"] + [x for l in out["stocks"].values() for x in l])
    return out
