"""Frische Schlagzeilen für das Tagesbriefing der App (site/data/briefing.json).

Anders als sentiment.py (Cache über mehrere Tage, nur Datum) holt dieses Modul bei jedem Scan die Nachrichten der
letzten ~36 Stunden mit Uhrzeit: für die Watchlist und die per Telegram synchronisierte Merkliste/Depot, dazu
marktweite Nachrichten (Notenbanken, Zinsen, Inflation, Zölle …) über die großen Indizes.
Muss vor dem großen Kurs-Download laufen – danach blockt Yahoo Einzelabfragen oft.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from .sentiment import tone as _tone_en

POS_DE = ("hebt", "erhöht", "anhebung", "kaufempfehlung", "hochgestuft", "rekord", "steigt", "springt", "klettert", "gewinnt",
          "übertrifft", "schlägt erwartung", "kursziel rauf", "rally", "zieht an", "legt zu", "starke zahlen", "plus von")
NEG_DE = ("senkt", "gesenkt", "abgestuft", "verkaufsempfehlung", "fällt", "bricht ein", "stürzt", "sackt", "verliert", "warnt",
          "gewinnwarnung", "verfehlt", "enttäusch", "kursziel runter", "einbruch", "minus von", "klage", "ermittlung", "rückruf")


def tone(title: str) -> int:
    t = " " + title.lower() + " "
    p, n = sum(w in t for w in POS_DE), sum(w in t for w in NEG_DE)
    return 1 if p > n else -1 if n > p else _tone_en(title)

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


STOP = {"inc", "corp", "corporation", "the", "group", "holdings", "holding", "company", "plc", "ltd", "limited", "co", "se", "ag",
        "sa", "nv", "n.v.", "asa", "ab", "spa", "s.p.a.", "class", "shares", "aktiengesellschaft", "incorporated", "&"}


def short_name(name: str) -> str:
    words = [w for w in (name or "").replace(",", " ").split() if w.lower().strip(".") not in STOP]
    return " ".join(words[:2]).strip()


def gnews(query: str, hours: float) -> list[dict]:
    """Google-News-RSS (deutschsprachig) – liefert Schlagzeilen bereits auf Deutsch."""
    import requests
    import xml.etree.ElementTree as ET
    from email.utils import parsedate_to_datetime

    r = requests.get("https://news.google.com/rss/search", timeout=10, headers={"User-Agent": "Mozilla/5.0"},
                     params={"q": f"{query} when:{max(1, round(hours / 24))}d", "hl": "de", "gl": "DE", "ceid": "DE:de"})
    r.raise_for_status()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    out = []
    for it in ET.fromstring(r.content).iter("item"):
        title = (it.findtext("title") or "").strip()
        src = (it.findtext("source") or "").strip()
        if src and title.endswith(" - " + src):
            title = title[: -len(src) - 3].strip()
        try:
            dt = parsedate_to_datetime(it.findtext("pubDate") or "")
        except Exception:
            continue
        if not title or dt < cutoff:
            continue
        out.append({"t": title[:180], "p": src[:40], "u": it.findtext("link") or "",
                    "d": dt.astimezone(timezone.utc).isoformat(timespec="minutes"), "s": tone(title)})
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


def build(tickers: list[str], names: dict | None = None, hours: float = 36, budget_s: float = 180, per: int = 3) -> dict:
    import yfinance as yf

    names = names or {}
    out = {"generated": datetime.now(timezone.utc).isoformat(timespec="minutes"), "hours": hours, "stocks": {}, "market": []}
    diag = {"gnews_ok": 0, "gnews_err": 0, "yahoo_ok": 0, "yahoo_err": 0, "err": ""}
    start = time.time()
    for t in list(dict.fromkeys(tickers)):
        if time.time() - start > budget_s:
            break
        nm = short_name(names.get(t) or "")
        items = []
        if nm:                                           # 1) Google News auf Deutsch
            try:
                key = nm.split()[0].lower()
                items = [x for x in gnews(f'"{nm}" (Aktie OR Börse OR Kurs OR Quartal OR Umsatz)', hours) if key in x["t"].lower()]
                diag["gnews_ok"] += 1
            except Exception as exc:
                diag["gnews_err"] += 1; diag["err"] = diag["err"] or f"gnews {exc!r}"[:200]
        if not items:                                    # 2) Yahoo (englisch, wird übersetzt)
            try:
                raw = yf.Ticker(t).get_news(count=10)
                diag["yahoo_ok"] += 1
                key = [w for w in "".join(ch if ch.isalnum() or ch == " " else " " for ch in (names.get(t) or "").lower()).split()
                       if len(w) > 2 and w not in STOP][:2]
                items = [x for x in _parse(raw, hours) if not key or any(k in x["t"].lower() for k in key)]
            except Exception as exc:
                diag["yahoo_err"] += 1; diag["err"] = diag["err"] or f"yahoo {exc!r}"[:200]
        if items:
            out["stocks"][t] = items[:per]
        time.sleep(0.3)
    seen, market = set(), []
    for q in ("Leitzins OR Zinsentscheid OR Zinssenkung OR Zinserhöhung OR EZB OR Fed OR Notenbank",
              "Inflation OR Arbeitsmarktbericht OR Zölle OR Konjunktur Börse OR Dax OR \"Wall Street\""):
        try:
            for x in gnews(q, min(hours, 24)):
                k = x["t"].lower()
                if k not in seen:
                    seen.add(k); market.append(x)
        except Exception as exc:
            diag["err"] = diag["err"] or f"gnews markt {exc!r}"[:200]
    if not market:                                       # Ersatz: Yahoo-Meldungen der großen Indizes mit Makro-Bezug
        for sym in INDICES:
            try:
                for x in _parse(yf.Ticker(sym).get_news(count=20), hours):
                    k = x["t"].lower()
                    if k not in seen and any(m in " " + k + " " for m in MACRO):
                        seen.add(k); market.append(x)
            except Exception:
                pass
    market.sort(key=lambda x: x["d"], reverse=True)
    out["market"] = market[:6]
    out["translated"] = translate(out["market"] + [x for l in out["stocks"].values() for x in l])
    out["diag"] = diag
    return out
