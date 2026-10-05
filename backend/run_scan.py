"""Täglicher Scan: Universum laden, jede Aktie prüfen, Ergebnisse für die Website schreiben.

Ausgabe:
  site/data/results.json        Treffer + Fast-Treffer (Kriterien, Score, Trade-Plan, Zone)
  site/data/charts/<TICKER>.json Chartdaten je Treffer/Fast-Treffer (Kerzen, EMAs, RSI, MACD, MBI)
  site/data/search.json         Suchindex: alle geprüften Aktien mit Kurz-Hinweis (backend/hints.py),
                                technische Eckdaten fürs Depot und Wechselkurse in EUR
  site/data/calendar.json       Termine: Quartalszahlen, Dividenden, Notenbanken, großer Verfall

Aufruf:  python -m backend.run_scan [--tickers UBER,TUI1.DE] [--end 2026-10-03]
"""

from __future__ import annotations

import argparse
import json
import math
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from .config import CONFIG, ROOT, as_dict
from .data_provider import CachedProvider, YFinanceProvider
from .hints import hint
from .macro import fetch_macro_events
from . import company, sentiment
from .analysis import MARKET, SECTOR_DE, SECTOR_ETF, add_context, analyze, finalize, market_context, trend_state
from .indicators import ema, macd, rsi, sma
from .mbi import momentum_bias_index
from .scanner import evaluate
from .universe import ASIA, load as load_universe

_ASIA_SUFFIXES = {suf for sufs, _, _ in ASIA.values() for suf in sufs}


def region_of(ticker: str) -> str:
    if "." not in ticker or ticker.endswith(".TO"):
        return "us"
    return "asia" if "." + ticker.rsplit(".", 1)[1] in _ASIA_SUFFIXES else "europe"

SITE = ROOT / "site" / "data"
CHART_BARS = 260


def _clean(x):
    """JSON-taugliche Werte (NaN → None, numpy → Python)."""
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if isinstance(x, (np.floating, float)):
        return None if math.isnan(x) or math.isinf(x) else round(float(x), 6)
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, np.bool_):
        return bool(x)
    return x


def chart_payload(df: pd.DataFrame, cfg=CONFIG) -> dict:
    """Zeitreihen für TradingView Lightweight Charts (letzte ~260 Kerzen)."""
    c = df["Close"]
    m = macd(c, cfg.macd.fast, cfg.macd.slow, cfg.macd.signal)
    r = rsi(c, cfg.rsi.length)
    mbi = momentum_bias_index(c, df["High"], df["Low"], cfg.mbi.momentum_length, cfg.mbi.bias_length,
                              cfg.mbi.smooth_length, cfg.mbi.impulse_length, cfg.mbi.std_mult)
    series = pd.DataFrame({
        "o": df["Open"], "h": df["High"], "l": df["Low"], "c": c, "v": df["Volume"],
        "e20": ema(c, 20), "e50": ema(c, 50), "e100": ema(c, 100), "e200": ema(c, 200),
        "rsi": r, "rsi_sma": sma(r, cfg.rsi.sma_len),
        "macd": m["macd"], "sig": m["signal"], "hist": m["hist"],
        "mbi_up": mbi["upper_bias"], "mbi_lo": mbi["lower_bias"], "mbi_ref": mbi["impulse_boundary"],
        "gx": mbi["green_x"].astype(int), "rx": mbi["red_x"].astype(int),
    }).iloc[-CHART_BARS:]
    out = {"t": [d.strftime("%Y-%m-%d") for d in series.index]}
    for col in series.columns:
        digits = 0 if col == "v" else 4
        out[col] = [None if pd.isna(v) else (int(v) if col in ("gx", "rx", "v") else round(float(v), digits))
                    for v in series[col]]
    return out


def load_watchlist() -> dict[str, str]:
    """Watchlist aus data/watchlist.json → {Ticker: Name}; je Aktie zählt der erste (Heimat-)Ticker."""
    path = ROOT / "data" / "watchlist.json"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return {tickers[0]: name for name, tickers in raw.items() if not name.startswith("_") and tickers}


def search_row(res, meta: dict, h: dict) -> dict:
    """Kompakte Zeile für den Suchindex (alle Aktien)."""
    f = res.flags
    return _clean({"t": res.ticker, "n": meta.get("name") or res.ticker, "r": meta.get("region") or region_of(res.ticker),
                   "x": meta.get("exchange") or "", "c": round(res.close, 4), "cur": res.flags.get("currency"),
                   "s": "hit" if res.passed else "fast" if res.fast_hit else "",
                   "m": sum(c.ok for c in res.criteria if c.key not in ("cap", "liquidity", "price", "history")),
                   "tone": h["tone"], "title": h["title"], "text": h["text"], "d": h["days"], "dl": h["days_label"],
                   # technische Eckdaten für die Depot-Einschätzung
                   "e20": f.get("ema20"), "e50": f.get("ema50"), "e200": f.get("ema200"), "atr": f.get("atr"),
                   "rsi": f.get("rsi"), "mh": f.get("macd_hist"), "e20f": f.get("ema20_falling"), "H": res.zone.get("H"),
                   "vola": f.get("volatility")})


def ticker_calendar(t: str) -> dict:
    """Ersatzquelle für einzelne Aktien: yfinance Ticker.calendar (Quartalszahlen, Dividenden)."""
    import yfinance as yf

    today = pd.Timestamp.now().normalize()
    for attempt in range(3):
        try:
            cal = yf.Ticker(t).calendar or {}
            break
        except Exception:
            time.sleep(3 * (attempt + 1))
    else:
        return {}
    def first_future(v):
        vals = v if isinstance(v, (list, tuple)) else [v]
        ds = sorted(pd.Timestamp(x) for x in vals if x is not None and not (isinstance(x, float) and math.isnan(x)))
        ds = [d for d in ds if d.tz_localize(None) >= today] if ds else []
        return str(ds[0].date()) if ds else None
    try:
        return {"earnings_date": first_future(cal.get("Earnings Date")),
                "ex_dividend_date": first_future(cal.get("Ex-Dividend Date")), "dividend_date": first_future(cal.get("Dividend Date"))}
    except Exception:
        return {}


def big_expiry_dates(start: pd.Timestamp, days: int = 120) -> list[str]:
    """Großer Verfall: dritter Freitag im März, Juni, September und Dezember."""
    out = []
    for y in (start.year, start.year + 1):
        for mth in (3, 6, 9, 12):
            first = pd.Timestamp(year=y, month=mth, day=1)
            third_friday = first + pd.Timedelta(days=(4 - first.weekday()) % 7 + 14)
            if start <= third_friday <= start + pd.Timedelta(days=days):
                out.append(str(third_friday.date()))
    return out


def build_calendar(rows: list[dict], infos: dict) -> dict:
    """Termine der geprüften Watchlist-/Treffer-Aktien + Notenbanken + großer Verfall (nächste ~4 Monate)."""
    today = pd.Timestamp.now().normalize()
    horizon = today + pd.Timedelta(days=120)
    events = []
    for r in rows:
        i = infos.get(r["ticker"], {})
        base = {"ticker": r["ticker"], "name": r["name"], "region": r.get("region"), "watch": r.get("in_watchlist", False)}
        for kind, date, extra in (("earnings", i.get("earnings_date"), {"estimate": i.get("earnings_estimate")}),
                                  ("exdiv", i.get("ex_dividend_date"), {"rate": i.get("dividend_rate")}),
                                  ("dividend", i.get("dividend_date"), {"rate": i.get("dividend_rate")})):
            if date and today <= pd.Timestamp(date) <= horizon:
                events.append({**base, "kind": kind, "date": date, **extra})
    macro, stats = fetch_macro_events()
    print(f"Markt-Termine automatisch: {stats}")
    macro_path = ROOT / "data" / "macro_events.json"
    if macro_path.exists():                       # von Hand gepflegte Termine als Ersatz/Ergänzung
        with open(macro_path, encoding="utf-8") as f:
            manual = json.load(f).get("events", [])
        have = {e["title"] for e in macro}
        macro += [e for e in manual if e["title"] not in have]
    seen = set()
    for e in sorted(macro, key=lambda e: e["date"]):
        if (e["date"], e["title"]) in seen or not today <= pd.Timestamp(e["date"]) <= horizon:
            continue
        seen.add((e["date"], e["title"]))
        events.append({"kind": "macro", "date": e["date"], "title": e["title"], "region": e.get("region", "all")})
    for d in big_expiry_dates(today):
        events.append({"kind": "expiry", "date": d, "title": "Großer Verfall (Optionen & Futures)", "region": "all"})
    events.sort(key=lambda e: (e["date"], e["kind"], e.get("name", "")))
    return {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "events": _clean(events)}


def fx_to_eur(currencies: set[str]) -> dict[str, float]:
    """Wechselkurse: 1 Einheit Währung = x EUR (für die Depot-Bewertung in Euro)."""
    out = {"EUR": 1.0}
    pairs = {c: f"EUR{c}=X" for c in currencies if c and c not in ("EUR", "GBp", "GBX")}
    if "GBp" in currencies or "GBX" in currencies:
        pairs.setdefault("GBP", "EURGBP=X")
    try:
        data = YFinanceProvider().history(list(pairs.values()), "5d")
    except Exception as exc:
        print(f"Wechselkurse: Fehler {exc!r}")
        data = {}
    for cur, sym in pairs.items():
        df = data.get(sym)
        if df is not None and len(df) and df["Close"].iloc[-1] > 0:
            out[cur] = round(1 / float(df["Close"].iloc[-1]), 6)
    if "GBP" in out:
        out["GBp"] = out["GBX"] = round(out["GBP"] / 100, 8)
    return out


def result_row(res, meta: dict) -> dict:
    div = res.flags.get("divergence") or {}
    fib, sup = res.zone.get("fib"), res.zone.get("support")
    zone_type = "+".join(z for z, ok in (("Fib", fib and fib.get("ok")), ("Support", sup)) if ok) or "–"
    return _clean({
        "ticker": res.ticker, "name": meta.get("name", res.ticker), "exchange": meta.get("exchange", ""),
        "region": meta.get("region", ""), "country": meta.get("country", ""), "sector": meta.get("sector", ""),
        "currency": res.flags.get("currency"), "market_cap_usd": res.flags.get("market_cap_usd"),
        "date": res.date, "close": res.close, "score": res.score, "passed": res.passed, "fast_hit": res.fast_hit,
        "missing": [c.label for c in res.missing], "in_watchlist": bool(meta.get("in_watchlist")),
        "met": sum(c.ok for c in res.criteria if c.key not in ("cap", "liquidity", "price", "history")),
        "total": sum(1 for c in res.criteria if c.key not in ("cap", "liquidity", "price", "history")),
        "drawdown": None if not res.zone.get("H") else (res.zone["H"] - res.close) / res.zone["H"],
        "zone_type": zone_type, "rsi": res.flags.get("rsi"), "divergence": div.get("kind"),
        "macd_status": ("Kreuz vor %d T." % res.flags["macd_cross_age"]) if res.flags.get("macd_cross_done")
                       else ("Histogramm steigt" if res.flags.get("macd_hist", 0) < 0 else "grün"),
        "mbi_status": "grün" if res.flags.get("mbi_green") else "rot, X gesetzt",
        "volatility": res.flags.get("volatility"), "atr_pct": res.flags.get("atr_pct"),
        "crv": res.plan.get("crv"), "earnings_date": res.flags.get("earnings_date"),
        "earnings_risk": res.flags.get("earnings_risk"),
        "criteria": [{"key": c.key, "label": c.label, "ok": c.ok, "value": c.value, "threshold": c.threshold}
                     for c in res.criteria],
        "bonuses": [{"label": k, "points": v} for k, v in res.bonuses],
        "hint": hint(res), "plan": res.plan, "zone": res.zone, "flags": {k: v for k, v in res.flags.items() if k != "divergence"},
        "div": div,
    })


TREND_DAYS = 10


def score_trend(df: pd.DataFrame, info: dict, ticker: str, res) -> dict:
    """Erfüllte Kriterien (und Score) der letzten TREND_DAYS Handelstage – wohin bewegt sich die Aktie?

    Richtung: steigend, wenn in den letzten 6 Tagen im Schnitt ≥ 0,25 Kriterien/Tag dazukamen oder ≥ 2 in 5 Tagen;
    fallend entsprechend umgekehrt; sonst seitwärts."""
    def met_of(r):
        return sum(c.ok for c in r.criteria if c.key not in ("cap", "liquidity", "price", "history"))
    met, score = [], []
    for k in range(TREND_DAYS, 0, -1):
        try:
            r = evaluate(df.iloc[:-k], info, ticker=ticker)
            met.append(met_of(r)); score.append(r.score)
        except Exception:
            met.append(None); score.append(None)
    met.append(met_of(res)); score.append(res.score)
    last = [m for m in met[-6:] if m is not None]
    slope = float(np.polyfit(range(len(last)), last, 1)[0]) if len(last) >= 3 else 0.0
    d5 = None if met[-6] is None else met[-1] - met[-6]
    direction = "up" if slope >= 0.25 or (d5 or 0) >= 2 else "down" if slope <= -0.25 or (d5 or 0) <= -2 else "flat"
    peak = max((m for m in met if m is not None), default=met[-1])
    return {"met": met, "score": score, "d5": d5, "slope": round(slope, 2), "dir": direction, "peak": peak}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", help="nur diese Ticker (kommagetrennt), sonst ganzes Universum")
    ap.add_argument("--end", help="Stichtag (exklusiv, ISO), sonst bis heute")
    args = ap.parse_args(argv)
    started = time.time()
    uni = load_universe()
    if args.tickers:
        wanted = [t.strip() for t in args.tickers.split(",") if t.strip()]
        uni = pd.concat([uni[uni["ticker"].isin(wanted)],
                         pd.DataFrame({"ticker": [t for t in wanted if t not in set(uni["ticker"])]})], ignore_index=True)
    meta = {r["ticker"]: {k: (None if pd.isna(v) else v) for k, v in r.items()} for r in uni.to_dict("records")}
    watch = load_watchlist()
    for t, name in watch.items():                    # Watchlist-Aktien immer prüfen
        meta.setdefault(t, {"ticker": t, "name": name})
        meta[t]["in_watchlist"] = True
        meta[t]["name"] = meta[t].get("name") or name
    tickers = list(meta)
    print(f"Universum: {len(tickers)} Aktien")
    # Termine der Watchlist zuerst holen: nach dem Massen-Download blockt Yahoo Einzelabfragen oft
    # Unternehmensbeschreibungen (Watchlist + Tabelle vom letzten Scan), vor dem großen Download
    about = company.load()
    if not args.end:
        n_new = company.fetch(list(watch) + list(about.get("_want", [])), about)
        print(f"Unternehmensbeschreibungen: {n_new} neu, {len(about) - ('_want' in about)} im Cache")
    # Marktstimmung (Analysten, Kursziel, Schlagzeilen) – ebenfalls vor dem großen Download
    senti = sentiment.load()
    if not args.end:
        try:
            n_s = sentiment.fetch(list(watch) + list(senti.get("_want", [])), senti,
                                  names={t: (meta.get(t) or {}).get("name") for t in meta})
            print(f"Marktstimmung: {n_s} aktualisiert, {len(senti) - ('_want' in senti)} im Cache")
        except Exception as exc:
            print(f"Marktstimmung: Fehler {exc!r}")
    watch_dates = {}
    if not args.end:
        for t in watch:
            watch_dates[t] = ticker_calendar(t)
            time.sleep(0.3)
        print(f"Watchlist-Termine: {sum(1 for d in watch_dates.values() if d.get('earnings_date'))} von {len(watch)} mit Quartalstermin")
    yf = YFinanceProvider()
    # Allzeithochs der Watchlist (komplette Historie) – für die Take-Profit-Zonen im Depot
    aths = {}
    if not args.end:
        for t, df in yf.history(list(watch), "max").items():
            if df is not None and len(df):
                hi = df["Close"]
                aths[t] = {"p": float(hi.max()), "date": str(hi.idxmax().date()), "full": True}
        print(f"Allzeithochs: {len(aths)} von {len(watch)} Watchlist-Aktien")
    ctx_hist = yf.history([t for t, _ in MARKET] + sorted(set(SECTOR_ETF.values())), CONFIG.history.period, end=args.end)
    market = market_context(ctx_hist)
    lage = ", ".join(v["name"] + " " + v["label"] for k, v in market.items() if k != "regime")
    print(f"Markt: {lage}; Lage: {market.get('regime', {}).get('label', '?')}")
    sec_cache: dict = {}

    def sector_state(sector):
        etf = SECTOR_ETF.get(sector or "")
        if not etf:
            return None
        if etf not in sec_cache:
            sh = ctx_hist.get(etf)
            st = trend_state(sh) if sh is not None and len(sh) > 210 else None
            sec_cache[etf] = st and {"n": SECTOR_DE.get(sector, sector), "etf": etf, "tone": st["tone"], "label": st["label"],
                                     "m1": st["chg1m"]}
        return sec_cache[etf]
    prov = CachedProvider(yf) if not args.end else yf
    data = prov.history(tickers, CONFIG.history.period, end=args.end)
    print(f"Kurse geladen: {len(data)}")

    results, stats = [], {"universe": len(tickers), "loaded": len(data), "errors": 0}
    search = {}
    for t, df in data.items():
        m = meta.get(t, {})
        info = {"currency": m.get("currency"), "market_cap_usd": m.get("market_cap_usd")}
        try:
            res = evaluate(df, info, ticker=t)
        except Exception as exc:                       # einzelne kaputte Reihen überspringen
            stats["errors"] += 1
            print(f"{t}: Fehler {exc!r}")
            continue
        try:
            search[t] = search_row(res, m, hint(res))
        except Exception as exc:
            print(f"{t}: Hinweis-Fehler {exc!r}")
        if res.passed or res.fast_hit or m.get("in_watchlist"):
            results.append((t, df, res))
    # Earnings-Termin, Name und Sektor nur für Treffer/Fast-Treffer abfragen (eine Anfrage je Aktie)
    infos = yf.infos([t for t, _, _ in results])
    rows, final = [], {}
    (SITE / "charts").mkdir(parents=True, exist_ok=True)
    for old in (SITE / "charts").glob("*.json"):
        old.unlink()
    for t, df, res in results:
        i = infos.get(t, {})
        m = meta.get(t, {})
        info = {"currency": m.get("currency") or i.get("currency"), "market_cap_usd": m.get("market_cap_usd"),
                "market_cap": i.get("market_cap"), "earnings_date": i.get("earnings_date") or m.get("earnings_date")}
        res = evaluate(df, info, ticker=t)            # mit Earnings-Termin neu bewerten
        m = {**m, "name": m.get("name") or i.get("name"), "sector": m.get("sector") or i.get("sector") or "",
             "region": m.get("region") or region_of(t), "exchange": m.get("exchange") or i.get("exchange") or ""}
        rows.append(result_row(res, m))
        rows[-1]["trend"] = score_trend(df, info, t, res)
        if about.get(t):
            rows[-1]["about"] = about[t]
        try:
            st = sentiment.summary(senti.get(t), res.close, sector_state(m.get("sector")), market.get("regime"))
            if st:
                rows[-1]["senti"] = st
        except Exception as exc:
            print(f"{t}: Stimmungs-Fehler {exc!r}")
        final[t] = (df, res, m)
        search[t] = {**search_row(res, m, rows[-1]["hint"]), "detail": 1}
        with open(SITE / "charts" / f"{t}.json", "w", encoding="utf-8") as f:
            json.dump(_clean(chart_payload(df)), f, separators=(",", ":"))
    rows.sort(key=lambda r: (r["passed"], r["score"], r["crv"] or 0), reverse=True)
    if not args.end:
        about["_want"] = [r["ticker"] for r in rows if r["ticker"] not in about]
        company.save(about)
        senti["_want"] = [r["ticker"] for r in rows]
        sentiment.save(senti)
    stats.update(hits=sum(r["passed"] for r in rows), fast_hits=sum(r["fast_hit"] for r in rows),
                 watchlist=sum(r["in_watchlist"] for r in rows),
                 duration_s=round(time.time() - started))
    out = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "stats": stats,
           "config": as_dict(CONFIG), "results": rows}
    SITE.mkdir(parents=True, exist_ok=True)
    with open(SITE / "results.json", "w", encoding="utf-8") as f:
        json.dump(_clean(out), f, ensure_ascii=False, separators=(",", ":"))
    fx = fx_to_eur({r.get("cur") for r in search.values()})
    with open(SITE / "search.json", "w", encoding="utf-8") as f:
        json.dump({"generated": out["generated"], "fx_eur": fx,
                   "rows": sorted(search.values(), key=lambda r: r["n"].lower())},
                  f, ensure_ascii=False, separators=(",", ":"))
    # Termine: Einzelabfrage (.info) zuerst, sonst aus dem Screener (Universum-Liste)
    dated = {}
    for r in rows:
        i, m = dict(infos.get(r["ticker"], {})), meta.get(r["ticker"], {})
        for k in ("earnings_date", "earnings_estimate", "ex_dividend_date", "dividend_date", "dividend_rate"):
            if not i.get(k) and m.get(k) not in (None, "", False):
                i[k] = m[k]
        for k, v in watch_dates.get(r["ticker"], {}).items():
            if v and not i.get(k):
                i[k] = v
        dated[r["ticker"]] = i
    missing = [r["ticker"] for r in rows if r.get("in_watchlist") and not dated[r["ticker"]].get("earnings_date")]
    for t in missing:                            # Watchlist: fehlende Quartalstermine einzeln nachholen
        cal = ticker_calendar(t)
        dated[t].update({k: v for k, v in cal.items() if v and not dated[t].get(k)})
    still = [t for t in missing if not dated[t].get("earnings_date")]
    print(f"Watchlist ohne Quartalstermin: {len(missing)} → nachgeholt {len(missing) - len(still)}, offen: {', '.join(still) or '–'}")
    print(f"Termine: {sum(1 for i in infos.values() if i.get('earnings_date'))} Earnings aus .info, "
          f"{sum(1 for i in dated.values() if i.get('earnings_date'))} insgesamt")
    # Positions-Analyse (Depot): alle Aktien mit Detailseite
    today = pd.Timestamp.now().date()
    ana = {}
    for t, (df, res, m) in final.items():
        try:
            a = analyze(df, res, aths.get(t))
            add_context(a, market, m.get("sector"), ctx_hist, dated.get(t, {}).get("earnings_date"), today)
            finalize(a)
            ana[t] = _clean(a)
        except Exception as exc:
            print(f"{t}: Analyse-Fehler {exc!r}")
    with open(SITE / "analysis.json", "w", encoding="utf-8") as f:
        json.dump(_clean({"generated": out["generated"], "market": market, "tickers": ana}), f, ensure_ascii=False, separators=(",", ":"))
    print(f"Analyse: {len(ana)} Aktien")
    cal = build_calendar(rows, dated)
    with open(SITE / "calendar.json", "w", encoding="utf-8") as f:
        json.dump(cal, f, ensure_ascii=False, separators=(",", ":"))
    print(f"Kalender: {len(cal['events'])} Termine, Wechselkurse: {fx}")
    print(f"Treffer: {stats['hits']}, Fast-Treffer: {stats['fast_hits']}, Fehler: {stats['errors']}, "
          f"Dauer {stats['duration_s']} s")
    for r in rows[:30]:
        print(f"  {r['ticker']:<10} Score {r['score']:>3}  {'TREFFER' if r['passed'] else 'fehlt: ' + r['missing'][0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
