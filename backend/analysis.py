"""Positions-Analyse für das Depot: Trend, Momentum, Marken für Stop/Ziele, Chance, Markt, Nachrichten.

Läuft im Scan für alle Aktien mit Detailseite (Watchlist, Treffer, Fast-Treffer). Das Depot selbst
kennt der Scan nicht – die App verknüpft die Analyse auf dem Gerät mit Einstieg und Stückzahl.

Wahrscheinlichkeit „Ziel vor Stop“: Kurs als Zufallspfad mit Drift (Brownsche Bewegung). Für Abstand a
nach unten, b nach oben, Tagesschwankung σ und Drift μ gilt
    P(oben zuerst) = (1 − e^(−2μa/σ²)) / (1 − e^(−2μ(a+b)/σ²)),   ohne Drift a / (a + b),
und die erwartete Dauer bis eine der Marken fällt ≈ a·b / σ² Handelstage. μ kommt aus der Steigung der
EMA 50 (gedämpft, begrenzt) – Trends halten oft, aber nicht immer.
"""

from __future__ import annotations

import math
import re
import time

import numpy as np
import pandas as pd

from .indicators import ema, pivot_highs, pivot_lows

MARKET = (("^GSPC", "S&P 500"), ("^NDX", "Nasdaq 100"), ("^GDAXI", "DAX"), ("^STOXX", "STOXX Europe 600"), ("^VIX", "VIX"))
SECTOR_ETF = {"Technology": "XLK", "Financial Services": "XLF", "Healthcare": "XLV", "Consumer Cyclical": "XLY",
              "Consumer Defensive": "XLP", "Energy": "XLE", "Industrials": "XLI", "Basic Materials": "XLB",
              "Utilities": "XLU", "Real Estate": "XLRE", "Communication Services": "XLC"}
SECTOR_DE = {"Technology": "Technologie", "Financial Services": "Finanzen", "Healthcare": "Gesundheit",
             "Consumer Cyclical": "Zyklischer Konsum", "Consumer Defensive": "Basiskonsum", "Energy": "Energie",
             "Industrials": "Industrie", "Basic Materials": "Rohstoffe", "Utilities": "Versorger",
             "Real Estate": "Immobilien", "Communication Services": "Kommunikation"}
EUROPE = (".PA", ".AS", ".MI", ".MC", ".CO", ".ST", ".SW", ".L", ".HE", ".OL", ".BR", ".VI", ".LS", ".IR")
POS_WORDS = r"beat|beats|tops|raise[sd]?|upgrade|record|surge|soar|jump|rall(y|ies)|strong|win[s]?|contract|approval|partnership|buyback|outperform|bullish|growth|profit"
NEG_WORDS = r"miss(es)?|cut[s]?|downgrade|lawsuit|probe|investigation|plunge|slump|tumble|fall[s]?|drop[s]?|weak|warn(s|ing)?|offering|dilution|recall|delay|loss(es)?|bearish|sell-off|layoff|short seller|fraud"


def _p(x: float) -> str:
    """Prozent mit Vorzeichen, deutsches Komma nicht nötig (ganze Zahlen)."""
    return f"{x * 100:+.0f} %"


def benchmark_for(ticker: str) -> str:
    if ticker.endswith(".DE"):
        return "^GDAXI"
    if ticker.endswith(EUROPE):
        return "^STOXX"
    return "^GSPC"


def _chg(c: np.ndarray, days: int) -> float | None:
    return float(c[-1] / c[-1 - days] - 1) if len(c) > days and c[-1 - days] else None


def trend_state(df: pd.DataFrame) -> dict:
    c = df["Close"].to_numpy(float)
    e20, e50, e200 = (ema(df["Close"], n).to_numpy(float) for n in (20, 50, 200))
    up = int(c[-1] > e50[-1]) + int(c[-1] > e200[-1]) + int(e50[-1] > e50[-21])
    tone = "green" if up == 3 else "red" if up == 0 else "yellow"
    label = {3: "Aufwärtstrend", 2: "leicht positiv", 1: "angeschlagen", 0: "Abwärtstrend"}[up]
    return {"c": round(float(c[-1]), 2), "chg1m": _chg(c, 21), "chg3m": _chg(c, 63), "tone": tone, "label": label,
            "above50": bool(c[-1] > e50[-1]), "above200": bool(c[-1] > e200[-1])}


def market_context(hist: dict[str, pd.DataFrame]) -> dict:
    out = {}
    for t, name in MARKET:
        df = hist.get(t)
        if df is None or len(df) < 210:
            continue
        s = trend_state(df)
        s["name"] = name
        if t == "^VIX":
            v = s["c"]
            s.update(tone="green" if v < 18 else "yellow" if v < 25 else "red",
                     label="ruhig" if v < 18 else "erhöht" if v < 25 else "Angst/Stress")
        out[t] = s
    spx, vix = out.get("^GSPC"), out.get("^VIX")
    if spx and vix:
        good = spx["above50"] and vix["c"] < 20
        bad = (not spx["above50"] and not spx["above200"]) or vix["c"] >= 28
        out["regime"] = {"tone": "green" if good else "red" if bad else "yellow",
                         "label": "Rückenwind (Risk-on)" if good else "Gegenwind (Risk-off)" if bad else "gemischt"}
    return out


def _rel(levels: list[tuple[float, str]], close: float, tol: float = 0.015) -> list[dict]:
    """Nahe beieinander liegende Marken zusammenfassen (± 1,5 %), Quellen bündeln."""
    out: list[dict] = []
    for p, src in sorted(levels):
        if out and abs(p / out[-1]["p"] - 1) <= tol:
            g = out[-1]
            g["n"] += 1
            g["p"] = (g["p"] * (g["n"] - 1) + p) / g["n"]
            if src not in g["src"]:
                g["src"].append(src)
        else:
            out.append({"p": p, "src": [src], "n": 1})
    return out


def _prob_up(a: float, b: float, sigma: float, mu: float) -> float:
    if a <= 0:
        return 0.0
    if b <= 0:
        return 1.0
    k = 2 * mu / (sigma * sigma)
    if abs(k * (a + b)) < 1e-6:
        return a / (a + b)
    return float((1 - math.exp(-k * a)) / (1 - math.exp(-k * (a + b))))


def analyze(df: pd.DataFrame, res) -> dict:
    """Kompakte Analyse einer Aktie aus Long-Sicht."""
    f, z = res.flags, res.zone
    c, h, l = (df[k].to_numpy(float) for k in ("Close", "High", "Low"))
    n, close = len(c), float(c[-1])
    e20, e50, e200 = (ema(df["Close"], k).to_numpy(float) for k in (20, 50, 200))
    atr = float(f.get("atr") or (h[-14:] - l[-14:]).mean())
    dates = df.index

    # ---------- Marken ----------
    sup, resi = [], []
    look = max(0, n - 250)
    for i in pivot_lows(df["Low"], 3):
        if i >= look:
            (sup if l[i] < close else resi).append((float(l[i]), f"Tief {dates[i]:%d.%m.}"))
    for i in pivot_highs(df["High"], 3):
        if i >= look:
            (resi if h[i] > close else sup).append((float(h[i]), f"Hoch {dates[i]:%d.%m.}"))
    for v, name in ((e50[-1], "EMA 50"), (e200[-1], "EMA 200")):
        (sup if v < close else resi).append((float(v), name))
    hi52 = float(h[-250:].max())
    if hi52 > close:
        resi.append((hi52, "52-W.-Hoch"))
    fib = z.get("fib") or None
    if fib:
        for k, lab in (("0.382", "Fib 0,382"), ("0.618", "Fib 0,618"), ("0.79", "Fib 0,79")):
            v = fib["levels"].get(k)
            if v:
                (sup if v < close else resi).append((float(v), lab))
    if z.get("support") and z["support"]["center"] < close:
        sup.append((float(z["support"]["center"]), f"Support-Zone ({z['support']['touches']}×)"))
    sup_g = [g for g in _rel(sup, close) if close - g["p"] >= 0.3 * atr]
    res_g = [g for g in _rel(resi, close) if g["p"] - close >= 0.3 * atr]
    sup_g.sort(key=lambda g: -g["p"])
    res_g.sort(key=lambda g: g["p"])

    # Stop: unter der nächsten Unterstützung, die mind. 1 ATR entfernt ist (Rauschen nicht abfischen)
    s_cand = next((g for g in sup_g if close - g["p"] >= 1.0 * atr), None)
    stop = (s_cand["p"] - 0.25 * atr) if s_cand else close - 2.5 * atr
    stop_src = " + ".join(s_cand["src"][:2]) if s_cand else "2,5 × ATR"
    t_c = [g for g in res_g if g["p"] - close >= 1.0 * atr]
    tp1 = t_c[0] if t_c else None
    tp2 = next((g for g in t_c[1:] if g["p"] - tp1["p"] >= 1.0 * atr), None) if tp1 else None
    # Ziele aus der Fib-Extension, wenn oben keine Marke mehr liegt (z. B. am Allzeithoch)
    swing_lo = float(l[-120:].min())
    ext = lambda x: hi52 + (x - 1) * (hi52 - swing_lo)
    if not tp1:
        tp1 = {"p": max(ext(1.272), close + 2 * atr), "src": ["Fib-Extension 1,272"]}
    if not tp2:
        tp2 = {"p": max(ext(1.618), tp1["p"] + 1.5 * atr), "src": ["Fib-Extension 1,618"]}

    # ---------- Wahrscheinlichkeit & Dauer ----------
    rets = np.diff(np.log(c[-61:]))
    sigma = float(np.std(rets, ddof=1)) * close if len(rets) > 5 else atr / 1.4
    slope = (e50[-1] - e50[-21]) / 20
    mu = float(np.clip(0.3 * slope, -0.05 * sigma, 0.05 * sigma))   # höchstens ~ Sharpe 0,8 p. a.
    a = close - stop

    def target(g):
        b = g["p"] - close
        p = _prob_up(a, b, sigma, mu)
        return {"p": round(g["p"], 4), "src": " + ".join(g["src"][:2]), "pct": b / close, "prob": round(p, 2),
                "days": int(round(min(250, a * b / (sigma * sigma)))), "crv": round(b / a, 2) if a > 0 else None}

    # ---------- Faktoren ----------
    fac = []
    up = int(close > e20[-1]) + int(close > e50[-1]) + int(close > e200[-1]) + int(e50[-1] > e50[-21])
    fac.append({"k": "trend", "l": "Trend", "s": [-2, -1, 0, 1, 2][up],
                "t": {4: "Kurs über EMA 20/50/200, EMA 50 steigt", 3: "überwiegend aufwärts", 2: "gemischt",
                      1: "überwiegend abwärts", 0: "unter allen EMAs, EMA 50 fällt"}[up]})
    mh, rising = f.get("macd_hist") or 0, f.get("macd_rising")
    slope_up = (f.get("macd_slope") or 0) > 0
    fac.append({"k": "macd", "l": "MACD", "s": 1 if mh > 0 and slope_up else -1 if mh < 0 and not slope_up else 0,
                "t": ("Histogramm grün" if mh > 0 else "Histogramm rot") + (", steigt" if (f.get("macd_slope") or 0) > 0 else ", fällt")})
    r = f.get("rsi") or 50
    fac.append({"k": "rsi", "l": "RSI", "s": -1 if r >= 75 or r < 35 else 1 if 45 <= r <= 68 else 0,
                "t": f"{r:.0f} – " + ("überkauft, Rücksetzer-Gefahr" if r >= 75 else "heiß" if r >= 68 else
                                      "gesundes Momentum" if r >= 45 else "schwach" if r >= 35 else "überverkauft, Erholung möglich")})
    mbi_g, xa = f.get("mbi_green"), f.get("mbi_x_age")
    fac.append({"k": "mbi", "l": "MBI", "s": 1 if mbi_g else -1,
                "t": ("Kaufdruck überwiegt" if mbi_g else "Verkaufsdruck überwiegt")
                     + (f", grünes X vor {xa} T." if xa is not None and xa <= 15 else "")})
    dv = f.get("divergence")
    if dv:
        fac.append({"k": "div", "l": "RSI-Divergenz", "s": 1, "t": f"bullisch ({dv['kind']}) am {pd.Timestamp(dv['t2']):%d.%m.}"})
    H = z.get("H")
    if H and close < H:
        dd = (H - close) / H
        if fib and fib.get("retracement") is not None and dd >= 0.08:
            rt = fib["retracement"]
            fac.append({"k": "fib", "l": "Fibonacci", "s": 1 if 0.5 <= rt <= 0.79 and fib.get("valid") else -1 if rt > 0.886 else 0,
                        "t": f"{dd * 100:.0f} % unter dem Hoch, Retracement {rt:.2f}".replace(".", ",")
                             + (" – in der Kaufzone" if 0.618 <= rt <= 0.79 else " – unter 0,886, Impuls gebrochen" if rt > 0.886 else "")})
    vola = f.get("volatility")
    out = {"c": close, "atr": atr, "sigma": sigma, "vola": vola,
           "stop": {"p": round(stop, 4), "src": stop_src, "pct": (stop - close) / close},
           "tp": [target(tp1), target(tp2)], "fac": fac,
           "sup": [{"p": round(g["p"], 4), "src": " + ".join(g["src"][:2])} for g in sup_g[:3]],
           "res": [{"p": round(g["p"], 4), "src": " + ".join(g["src"][:2])} for g in res_g[:3]],
           "chg1m": _chg(c, 21), "chg3m": _chg(c, 63), "bench": benchmark_for(res.ticker)}
    return out


def add_context(a: dict, market: dict, sector: str | None, sector_hist: dict, earnings: str | None, today) -> None:
    """Relative Stärke, Branche, Markt und Termine als weitere Faktoren anhängen; Gesamturteil bilden."""
    b = market.get(a["bench"])
    if b and a.get("chg3m") is not None and b.get("chg3m") is not None:
        d = a["chg3m"] - b["chg3m"]
        a["fac"].append({"k": "rs", "l": "Relative Stärke", "s": 1 if d > 0.05 else -1 if d < -0.05 else 0,
                         "t": f"3 Mon. {_p(a['chg3m'])} vs. {b['name']} {_p(b['chg3m'])}"})
    etf = SECTOR_ETF.get(sector or "")
    sh = sector_hist.get(etf) if etf else None
    if sh is not None and len(sh) > 210:
        s = trend_state(sh)
        a["fac"].append({"k": "sector", "l": "Branche", "s": {"green": 1, "yellow": 0, "red": -1}[s["tone"]],
                         "t": f"{SECTOR_DE.get(sector, sector)} ({etf}): {s['label']}, 1 Mon. {_p(s['chg1m'])}"})
    reg = market.get("regime")
    if reg:
        a["fac"].append({"k": "market", "l": "Gesamtmarkt", "s": {"green": 1, "yellow": 0, "red": -1}[reg["tone"]],
                         "t": reg["label"] + (f", VIX {market['^VIX']['c']:.0f}" if "^VIX" in market else "")})
    if earnings:
        days = (pd.Timestamp(earnings).date() - today).days
        if 0 <= days <= 21:
            a["fac"].append({"k": "earn", "l": "Quartalszahlen", "s": -1 if days <= 7 else 0,
                             "t": f"in {days} Tagen ({pd.Timestamp(earnings):%d.%m.}) – Kurssprung möglich"})
        a["earn"] = earnings


def finalize(a: dict) -> None:
    """Gesamturteil 0–100 aus den gewichteten Faktoren (+1 / 0 / −1, Trend −2 … +2)."""
    weights = {"trend": 2.0, "macd": 1.0, "rsi": 0.75, "mbi": 1.0, "div": 0.75, "fib": 0.75, "rs": 1.0,
               "sector": 0.5, "market": 1.0, "earn": 0.5, "news": 0.5}
    tot = sum(weights.get(x["k"], 0.5) * x["s"] for x in a["fac"])
    mx = sum(weights.get(x["k"], 0.5) * (2 if x["k"] == "trend" else 1) for x in a["fac"])
    a["score"] = round(50 + 50 * tot / mx) if mx else 50


def news_tone(title: str) -> int:
    t = title.lower()
    return (1 if re.search(rf"\b({POS_WORDS})\b", t) else 0) - (1 if re.search(rf"\b({NEG_WORDS})\b", t) else 0)


def fetch_news(names: dict[str, str], per: int = 4) -> dict[str, list[dict]]:
    """Jüngste Schlagzeilen je Aktie {Ticker: Name} (Yahoo Finance). Nur Schlagzeilen, die die Firma nennen.
    Stimmung nur grob per Stichwort."""
    import yfinance as yf

    out, errors = {}, []
    for t, name in names.items():
        key = next((w for w in re.split(r"[\s,]+", name or "") if len(w) >= 3), t.split(".")[0]).lower()
        base = t.split(".")[0].lower()
        items = []
        for q in (t, name):                # 1. Ticker-News, 2. Suche nach dem Namen
            try:
                got = (yf.Ticker(t).get_news(count=10) if q == t else yf.Search(q, max_results=1, news_count=10).news) or []
            except Exception as exc:
                errors.append(f"{t}: {exc!r}"[:160])
                got = []
                time.sleep(1)
            items += got
        def title_of(it):
            return ((it.get("content") or it).get("title") or "")
        items = [it for it in items if re.search(rf"\b({re.escape(key)}|{re.escape(base)})\b", title_of(it).lower())]
        rows = []
        for it in items:
            cnt = it.get("content") or it
            title = cnt.get("title")
            if not title:
                continue
            date = cnt.get("pubDate") or cnt.get("displayTime") or it.get("providerPublishTime")
            if isinstance(date, (int, float)):
                date = pd.Timestamp(date, unit="s").isoformat()
            url = (cnt.get("canonicalUrl") or {}).get("url") or (cnt.get("clickThroughUrl") or {}).get("url") or it.get("link")
            pub = (cnt.get("provider") or {}).get("displayName") or it.get("publisher") or ""
            rows.append({"title": title, "date": str(date or "")[:10], "url": url, "pub": pub, "tone": news_tone(title)})
        rows = list({x["title"]: x for x in rows}.values())
        rows.sort(key=lambda x: x["date"], reverse=True)
        if rows:
            out[t] = rows[:per]
        time.sleep(0.3)
    if errors:
        print(f"Nachrichten: {len(errors)} Fehler, z. B. {errors[:3]}")
    return out


def add_news(a: dict, news: list[dict] | None) -> None:
    if not news:
        return
    a["news"] = news
    s = sum(x["tone"] for x in news)
    a["fac"].append({"k": "news", "l": "Nachrichten", "s": 1 if s >= 2 else -1 if s <= -2 else 0,
                     "t": f"{len(news)} Schlagzeilen, Ton " + ("eher positiv" if s >= 2 else "eher negativ" if s <= -2 else "gemischt/neutral")})
