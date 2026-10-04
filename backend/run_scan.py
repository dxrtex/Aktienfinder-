"""Täglicher Scan: Universum laden, jede Aktie prüfen, Ergebnisse für die Website schreiben.

Ausgabe:
  site/data/results.json        Treffer + Fast-Treffer (Kriterien, Score, Trade-Plan, Zone)
  site/data/charts/<TICKER>.json Chartdaten je Treffer/Fast-Treffer (Kerzen, EMAs, RSI, MACD, MBI)
  site/data/search.json         Suchindex: alle geprüften Aktien mit Kurz-Hinweis (backend/hints.py)

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
    return _clean({"t": res.ticker, "n": meta.get("name") or res.ticker, "r": meta.get("region") or region_of(res.ticker),
                   "x": meta.get("exchange") or "", "c": round(res.close, 4), "cur": res.flags.get("currency"),
                   "s": "hit" if res.passed else "fast" if res.fast_hit else "",
                   "m": sum(c.ok for c in res.criteria if c.key not in ("cap", "liquidity", "price", "history")),
                   "tone": h["tone"], "title": h["title"], "text": h["text"], "d": h["days"], "dl": h["days_label"]})


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
    yf = YFinanceProvider()
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
    rows = []
    (SITE / "charts").mkdir(parents=True, exist_ok=True)
    for old in (SITE / "charts").glob("*.json"):
        old.unlink()
    for t, df, res in results:
        i = infos.get(t, {})
        m = meta.get(t, {})
        info = {"currency": m.get("currency") or i.get("currency"), "market_cap_usd": m.get("market_cap_usd"),
                "market_cap": i.get("market_cap"), "earnings_date": i.get("earnings_date")}
        res = evaluate(df, info, ticker=t)            # mit Earnings-Termin neu bewerten
        m = {**m, "name": m.get("name") or i.get("name"), "sector": m.get("sector") or i.get("sector") or "",
             "region": m.get("region") or region_of(t), "exchange": m.get("exchange") or i.get("exchange") or ""}
        rows.append(result_row(res, m))
        search[t] = {**search_row(res, m, rows[-1]["hint"]), "detail": 1}
        with open(SITE / "charts" / f"{t}.json", "w", encoding="utf-8") as f:
            json.dump(_clean(chart_payload(df)), f, separators=(",", ":"))
    rows.sort(key=lambda r: (r["passed"], r["score"], r["crv"] or 0), reverse=True)
    stats.update(hits=sum(r["passed"] for r in rows), fast_hits=sum(r["fast_hit"] for r in rows),
                 watchlist=sum(r["in_watchlist"] for r in rows),
                 duration_s=round(time.time() - started))
    out = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "stats": stats,
           "config": as_dict(CONFIG), "results": rows}
    SITE.mkdir(parents=True, exist_ok=True)
    with open(SITE / "results.json", "w", encoding="utf-8") as f:
        json.dump(_clean(out), f, ensure_ascii=False, separators=(",", ":"))
    with open(SITE / "search.json", "w", encoding="utf-8") as f:
        json.dump({"generated": out["generated"], "rows": sorted(search.values(), key=lambda r: r["n"].lower())},
                  f, ensure_ascii=False, separators=(",", ":"))
    print(f"Treffer: {stats['hits']}, Fast-Treffer: {stats['fast_hits']}, Fehler: {stats['errors']}, "
          f"Dauer {stats['duration_s']} s")
    for r in rows[:30]:
        print(f"  {r['ticker']:<10} Score {r['score']:>3}  {'TREFFER' if r['passed'] else 'fehlt: ' + r['missing'][0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
