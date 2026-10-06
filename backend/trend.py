"""Zweites Einstiegs-Setup: Rücksetzer im Aufwärtstrend („Trend-Rücksetzer“).

Idee: Aktien, die langfristig klar steigen (Kurs deutlich über der EMA 200), bei einer kurzen Verschnaufpause an der
EMA 50 kaufen – Wette auf die Fortsetzung des Trends (Kairo dagegen: Wende nach einer Korrektur).
Grundlage: 6-Jahres-Analyse (Überrendite gegenüber zufälligen Aktien derselben Woche, Lernen und Prüfen getrennt).
Schwellen in config.yaml (Abschnitt trend). Grundfilter (Börsenwert, Liquidität, Kurs, Historie) wie bei Kairo.
"""

from __future__ import annotations

import pandas as pd

from .config import CONFIG
from .scanner import Criterion, Result, de, pct

UNIVERSE = ("cap", "liquidity", "price", "history")


def evaluate_trend(df: pd.DataFrame, kairo: Result, cfg=CONFIG) -> Result:
    """Prüft das Trend-Setup. Nutzt die Indikatoren, die Kairo schon berechnet hat (kairo.flags)."""
    from .analysis import swing_levels

    tc = cfg.trend
    f = kairo.flags
    close = kairo.close
    res = Result(ticker=kairo.ticker, date=kairo.date, close=close, flags=dict(f), zone={})
    res.criteria = [c for c in kairo.criteria if c.key in UNIVERSE]
    add = lambda *a, **k: res.criteria.append(Criterion(*a, **k))
    e50, e200, r, atr = f.get("ema50"), f.get("ema200"), f.get("rsi"), f.get("atr") or 0
    g200 = close / e200 - 1 if e200 else None
    g50 = close / e50 - 1 if e50 else None
    add("t_trend", f"Aufwärtstrend: Kurs ≥ {pct(tc.min_above_ema200, 0)} über der EMA 200", bool(g200 is not None and g200 >= tc.min_above_ema200),
        "–" if g200 is None else f"{'+' if g200 >= 0 else ''}{pct(g200)} (EMA 200 {de(e200)})", f"≥ +{pct(tc.min_above_ema200, 0)}")
    add("t_dip", f"Rücksetzer an die EMA 50 (0 bis −{pct(-tc.dip_min, 0)})", bool(g50 is not None and tc.dip_min <= g50 <= tc.dip_max),
        "–" if g50 is None else f"{pct(g50)} (EMA 50 {de(e50)})", f"{pct(tc.dip_min, 0)} … {pct(tc.dip_max, 0)}")
    add("t_rsi", f"RSI {tc.rsi_min}–{tc.rsi_max} (Verschnaufpause, nicht überverkauft)", bool(r is not None and tc.rsi_min <= r <= tc.rsi_max),
        "–" if r is None else de(r, 1), f"{tc.rsi_min}–{tc.rsi_max}")
    if getattr(tc, "ema50_over_200", False):
        add("t_order", "EMA 50 über EMA 200", bool(e50 and e200 and e50 > e200), f"{de(e50)} / {de(e200)}", "EMA 50 > EMA 200")
    # Trade-Plan: Stop unter dem 10-Tage-Tief (mind. 1 ATR), Ziele = relevante Hochs darüber
    lows = df["Low"].dropna().to_numpy(float)
    stop = min(float(lows[-10:].min()) - 0.25 * atr, close - atr) if atr else float(lows[-10:].min())
    try:
        lv = swing_levels(df, close, atr)
    except Exception:
        lv = []
    t1 = lv[0]["p"] if lv else close + 2 * atr
    t2 = lv[1]["p"] if len(lv) > 1 else (f.get("hi52") or close + 3 * atr)
    risk = close - stop
    res.plan = {"entry": close, "buy_stop": close, "stop": stop, "target1": t1, "target2": max(t2, t1),
                "crv": (max(t2, t1) - close) / risk if risk > 0 else None, "stop_pct": risk / close if close else None,
                "max_leverage": None}
    res.flags["setup"] = "trend"
    # Qualitätsstufe „Top“ (6-Jahres-Analyse): nah am Hoch, ruhigere Aktie, Trend nicht überdehnt
    H = (kairo.zone or {}).get("H")
    dd = (H - close) / H if H else None
    atrp = atr / close if close else None
    tt = getattr(tc, "top", None)
    res.flags["trend_top"] = bool(tt and dd is not None and atrp is not None and g200 is not None
                                  and dd < tt.max_from_high and atrp < tt.max_atr_pct and g200 < tt.max_above_ema200)
    res.flags["trend_dd"], res.flags["trend_atrp"] = dd, atrp
    res.score = 0
    return res
