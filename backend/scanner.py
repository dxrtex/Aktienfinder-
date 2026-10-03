"""Prüft eine Aktie auf das Long-Reversal-Setup (Abschnitte 2.2–2.7 und 3 des Prompts).

`evaluate()` liefert für jedes Pflichtkriterium: erfüllt ja/nein, Messwert und Schwelle –
daraus entstehen Score, Trefferliste, Fast-Treffer und die Checkliste auf der Detailseite.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from types import SimpleNamespace

import numpy as np
import pandas as pd

from .config import CONFIG
from .indicators import atr, ema, macd, pivot_highs, pivot_lows, rsi, sma
from .mbi import momentum_bias_index
from .scoring import score_setup

FX_USD = {"USD": 1.0, "EUR": 1.10, "GBP": 1.30, "GBp": 0.013, "CHF": 1.15, "SEK": 0.095, "DKK": 0.15,
          "NOK": 0.095, "PLN": 0.25, "CZK": 0.044, "HUF": 0.0028}


def de(x: float | None, digits: int = 2) -> str:
    """Zahl im deutschen Format (Komma als Dezimaltrenner)."""
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "–"
    return f"{x:,.{digits}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def pct(x: float | None, digits: int = 1) -> str:
    return "–" if x is None else de(100 * x, digits) + " %"


@dataclass
class Criterion:
    key: str
    label: str
    ok: bool
    value: str
    threshold: str
    mandatory: bool = True


@dataclass
class Result:
    ticker: str
    date: str
    close: float
    criteria: list[Criterion] = field(default_factory=list)
    flags: dict = field(default_factory=dict)       # Bonus-Merkmale und Zusatzinfos
    zone: dict = field(default_factory=dict)        # Fib-Level / Supportzone
    plan: dict = field(default_factory=dict)        # Trade-Plan
    score: int = 0
    bonuses: list = field(default_factory=list)

    @property
    def missing(self) -> list[Criterion]:
        return [c for c in self.criteria if c.mandatory and not c.ok]

    @property
    def passed(self) -> bool:
        return not self.missing

    @property
    def fast_hit(self) -> bool:
        return len(self.missing) == 1


def find_rsi_divergence(low: pd.Series, r: np.ndarray, rc: SimpleNamespace):
    """Bullische RSI-Divergenz (2.4). Rückgabe: ((Art, T1, T2) oder None, jüngste Kurs-Tiefs ≤ 10 T.).

    Pivot-Tiefs des Kurses (Länge 3) der letzten 60 Tage; T2 = jüngstes Tief (max. 10 Tage alt),
    T1 = früheres Tief 10–60 Tage vor T2. Klassisch: Kurs T2 ≤ T1 × 1,01 und RSI T2 ≥ RSI T1 + 3.
    Versteckt: Kurs T2 > T1 und RSI T2 ≤ RSI T1 − 3. Klassisch hat Vorrang.
    """
    l = low.to_numpy(dtype=float)
    n = len(l)
    rp = [i for i in pivot_lows(low, rc.pivot_len) if n - 1 - i <= rc.lookback]
    recent = [i for i in rp if n - 1 - i <= rc.t2_max_age]
    div = None
    if recent:
        t2 = recent[-1]
        for t1 in reversed([i for i in rp if rc.t1_min_gap <= t2 - i <= rc.t1_max_gap]):
            if l[t2] <= l[t1] * rc.classic_price_tol and r[t2] >= r[t1] + rc.min_rsi_diff:
                return ("klassisch", t1, t2), recent
            if div is None and l[t2] > l[t1] and r[t2] <= r[t1] - rc.min_rsi_diff:
                div = ("versteckt", t1, t2)
    return div, recent


def evaluate(df: pd.DataFrame, info: dict | None = None, cfg: SimpleNamespace = CONFIG,
             ticker: str = "") -> Result:
    info = info or {}
    df = df.dropna(subset=["Open", "High", "Low", "Close"]).copy()
    o, h, l, c = (df[k].to_numpy(dtype=float) for k in ("Open", "High", "Low", "Close"))
    v = df["Volume"].fillna(0).to_numpy(dtype=float)
    n = len(df)
    close = float(c[-1])
    res = Result(ticker=ticker, date=str(df.index[-1].date()), close=close)
    add = lambda *a, **k: res.criteria.append(Criterion(*a, **k))

    e20 = ema(df["Close"], cfg.correction.ema_fast).to_numpy()
    e50 = ema(df["Close"], cfg.correction.ema_slow).to_numpy()
    e100 = ema(df["Close"], 100).to_numpy()
    e200 = ema(df["Close"], 200).to_numpy()
    a14 = atr(df, cfg.correction.atr_len).to_numpy()
    r = rsi(df["Close"], cfg.rsi.length).to_numpy()
    r_sma = sma(pd.Series(r), cfg.rsi.sma_len).to_numpy()
    m = macd(df["Close"], cfg.macd.fast, cfg.macd.slow, cfg.macd.signal)
    ml, ms, mh = (m[k].to_numpy() for k in ("macd", "signal", "hist"))
    mbi = momentum_bias_index(df["Close"], df["High"], df["Low"], cfg.mbi.momentum_length, cfg.mbi.bias_length,
                              cfg.mbi.smooth_length, cfg.mbi.impulse_length, cfg.mbi.std_mult)
    up_b, lo_b, bound = (mbi[k].to_numpy() for k in ("upper_bias", "lower_bias", "impulse_boundary"))
    gx = mbi["green_x"].to_numpy()
    res.flags.update(ema20=e20[-1], ema50=e50[-1], ema100=e100[-1], ema200=e200[-1], atr=a14[-1], rsi=r[-1])

    # ---------- 2.1 Universum ----------
    u = cfg.universe
    cur = info.get("currency") or "USD"
    fx = FX_USD.get(cur, 1.0)
    cap_usd = info.get("market_cap") * fx if info.get("market_cap") else None
    add("cap", "Marktkapitalisierung ≥ 2 Mrd. USD", cap_usd is None or cap_usd >= u.min_market_cap_usd,
        "unbekannt" if cap_usd is None else de(cap_usd / 1e9, 1) + " Mrd. USD", "≥ 2,0 Mrd. USD")
    dollar_vol = float(np.mean(v[-u.volume_avg_days:] * c[-u.volume_avg_days:])) * fx
    add("liquidity", "Liquidität (Ø Volumen 20 T. × Kurs)", dollar_vol >= u.min_dollar_volume,
        de(dollar_vol / 1e6, 1) + " Mio. USD", "≥ 5,0 Mio. USD")
    add("price", "Kurs ≥ 1", close >= u.min_price, de(close), "≥ 1,00")
    add("history", "Mindesthistorie", n >= cfg.history.min_bars, f"{n} Kerzen", f"≥ {cfg.history.min_bars}")
    res.flags.update(market_cap_usd=cap_usd, dollar_volume=dollar_vol, currency=cur)

    # ---------- 2.2 Korrektur ----------
    cc = cfg.correction
    pl = cfg.pivots.pivot_len
    ph_idx = pivot_highs(df["High"], pl)
    cand = [i for i in ph_idx if cc.swing_high_min_age <= n - 1 - i <= cc.swing_high_max_age]
    H = H_idx = None
    if cand:
        H_idx = max(cand, key=lambda i: h[i])
        H = float(h[H_idx])
    dd = (H - close) / H if H else None
    add("drawdown", "Rückgang vom Swing-High (20–180 T.)", dd is not None and dd >= cc.min_drawdown,
        "kein Swing-High" if dd is None else f"−{pct(dd)} (H {de(H)} am {df.index[H_idx].date():%d.%m.%Y})",
        "≥ 12 %")
    daily = c[-cc.crash_lookback:] / c[-cc.crash_lookback - 1:-1] - 1
    worst = float(daily.min())
    add("no_crash", "Pullback statt Crash (max. Tagesverlust 10 T.)", worst > -cc.crash_max_daily_loss,
        pct(worst), "> −25 %")
    below = close < e20[-1] and close < e50[-1]
    falling = e20[-1] < e20[-1 - cc.ema_fast_falling_days]
    add("structure", "Unter EMA 20 & 50, EMA 20 fällt", bool(below and falling),
        f"Kurs {de(close)} / EMA20 {de(e20[-1])} / EMA50 {de(e50[-1])}; EMA20 vor 5 T. {de(e20[-6])}",
        "Kurs < EMA20 und < EMA50, EMA20 fallend")

    # ---------- 2.3 Unterstützungszone ----------
    fz, sp = cfg.fib, cfg.support
    pl_idx = pivot_lows(df["Low"], pl)
    zone_a = zone_b = None
    if H_idx is not None:
        lows_before = [i for i in pl_idx if H_idx - fz.impulse_lookback <= i < H_idx]
        if lows_before:
            L_idx = min(lows_before, key=lambda i: l[i])
            L = float(l[L_idx])
            impulse = (H - L) / L
            lvl = lambda x: H - x * (H - L)
            recent_low = float(l[-fz.touch_bars:].min())
            in_zone = lambda lo_x, hi_x: (lvl(hi_x) <= close <= lvl(lo_x)) or (lvl(hi_x) <= recent_low <= lvl(lo_x))
            zone_a = {
                "L": L, "L_date": str(df.index[L_idx].date()), "impulse": impulse,
                "levels": {str(x): lvl(x) for x in (0, 0.382, 0.618, 0.706, 0.79, 0.886, 1)},
                "in_zone": in_zone(*fz.zone), "core": in_zone(*fz.core_zone),
                "valid": close >= lvl(fz.invalid_below),
                "retracement": (H - min(close, recent_low)) / (H - L),
            }
            zone_a["ok"] = impulse >= fz.min_impulse and zone_a["in_zone"] and zone_a["valid"]
            zone_a["band"] = (lvl(fz.invalid_below), lvl(fz.zone[0]))
    # Variante B: Cluster früherer Pivot-Lows / -Highs (± 3 %)
    start = max(0, n - sp.lookback)
    points = [(i, l[i]) for i in pl_idx if start <= i <= n - 1 - sp.exclude_recent]
    points += [(i, h[i]) for i in ph_idx if start <= i <= n - 1 - sp.exclude_recent]
    best = None
    for _, p in points:
        members = [(i, x) for i, x in points if abs(x / p - 1) <= sp.tolerance]
        if len(members) < sp.min_touches or n - 1 - min(i for i, _ in members) < sp.min_oldest_age:
            continue
        center = float(np.mean([x for _, x in members]))
        near = center * (1 - sp.max_below) <= close <= center * (1 + sp.max_above)
        broken = bool((c[-sp.break_days:] < center * (1 - sp.break_below)).any())
        if not near or broken:
            continue
        key = (len(members), -abs(close / center - 1))
        if best is None or key > best[0]:
            best = (key, center, members)
    if best:
        _, center, members = best
        zone_b = {"ok": True, "center": center, "touches": len(members),
                  "touch_dates": sorted(str(df.index[i].date()) for i, _ in members),
                  "band": (center * (1 - sp.tolerance), center * (1 + sp.tolerance))}
    zone_ok = bool((zone_a and zone_a["ok"]) or zone_b)
    parts = []
    if zone_a:
        parts.append(f"Fib: Retracement {de(zone_a['retracement'], 3)}, Impuls {pct(zone_a['impulse'])}"
                     + ("" if zone_a["valid"] else ", unter 0,886") + (" ✓" if zone_a["ok"] else ""))
    else:
        parts.append("Fib: kein Impuls")
    parts.append(f"Support: Mitte {de(zone_b['center'])}, {zone_b['touches']} Touches ✓" if zone_b
                 else "Support: kein gültiger Mehrfachboden")
    add("zone", "Unterstützungszone (Fib 0,618–0,79 oder Support)", zone_ok, "; ".join(parts),
        "Fib-Zone (Impuls ≥ 15 %, nicht unter 0,886) oder ≥ 2 Touches ± 3 %")
    res.zone = {"fib": zone_a, "support": zone_b, "H": H, "H_date": None if H_idx is None else str(df.index[H_idx].date())}
    bands = [z["band"] for z in (zone_a if zone_a and zone_a["ok"] else None, zone_b) if z]

    # Abflachung (2.2, braucht die Zone für die Lunten)
    k = cc.flat_days
    span = float(h[-k:].max() - l[-k:].min())
    limit = cc.flat_atr_mult * a14[-1] * math.sqrt(k)
    rng = h[-k:] - l[-k:]
    wick = np.minimum(o[-k:], c[-k:]) - l[-k:]
    in_band = lambda x: any(lo * 0.99 <= x <= hi * 1.01 for lo, hi in bands)
    wicks = int(sum(1 for i in range(k) if rng[i] > 0 and wick[i] >= cc.wick_min_ratio * rng[i] and in_band(l[-k + i])))
    add("flattening", "Abflachung der letzten 10 Kerzen", span < limit or wicks >= cc.wick_min_count,
        f"Spanne {de(span)} vs. Grenze {de(limit)}; {wicks} Lunten-Kerzen in der Zone",
        "Spanne < 1,5 × ATR × √10 oder ≥ 2 lange untere Lunten")

    # ---------- 2.4 RSI-Divergenz ----------
    rc = cfg.rsi
    div, recent = find_rsi_divergence(df["Low"], r, rc)
    if div:
        kind, t1, t2 = div
        dv = (f"{kind}: {df.index[t1].date():%d.%m.} Tief {de(l[t1])} / RSI {de(r[t1], 1)} → "
              f"{df.index[t2].date():%d.%m.} Tief {de(l[t2])} / RSI {de(r[t2], 1)}")
    else:
        dv = "keine (jüngstes Tief " + (f"vom {df.index[recent[-1]].date():%d.%m.}" if recent else "älter als 10 T.") + ")"
    add("rsi_div", "RSI bullische Divergenz (klassisch/versteckt)", div is not None, dv,
        "T2 ≤ 10 T. alt, T1 10–60 T. davor, RSI-Abstand ≥ 3 Punkte")
    add("rsi_range", "RSI aktuell 28–48", rc.current_min <= r[-1] <= rc.current_max, de(r[-1], 1), "28–48")
    res.flags["divergence"] = None if not div else {
        "kind": div[0], "t1": str(df.index[div[1]].date()), "t2": str(df.index[div[2]].date()),
        "price_t1": l[div[1]], "price_t2": l[div[2]], "rsi_t1": r[div[1]], "rsi_t2": r[div[2]]}
    res.flags["rsi_was_oversold"] = bool(np.nanmin(r[-rc.lookback:]) <= rc.oversold)
    cross_up = any(r[-i] > r_sma[-i] and r[-i - 1] <= r_sma[-i - 1] for i in range(1, rc.sma_cross_days + 1))
    res.flags["rsi_above_sma"] = bool(r[-1] > r_sma[-1] or cross_up)

    # ---------- 2.5 MACD ----------
    mc = cfg.macd
    below0 = ml[-1] < 0 and ms[-1] < 0
    add("macd_below0", "MACD-Linie und Signal unter 0", bool(below0), f"MACD {de(ml[-1], 3)} / Signal {de(ms[-1], 3)}", "beide < 0")
    crosses = [i for i in range(1, n) if mh[i - 1] <= 0 < mh[i]]
    cross_age = n - 1 - crosses[-1] if crosses else None
    a_ok = cross_age is not None and cross_age <= mc.cross_max_age
    rising = all(mh[-j] > mh[-j - 1] for j in range(1, mc.rising_bars + 1))
    trough = float(np.nanmin(mh[-mc.trough_lookback:]))
    ratio = abs(mh[-1]) / abs(trough) if trough < 0 else None
    b_ok = mh[-1] < 0 and rising and ratio is not None and ratio <= mc.trough_ratio
    failed = (cross_age is not None and cross_age <= mc.cross_max_age + mc.fail_bars and mh[-1] < 0
              and all(mh[-j] < mh[-j - 1] for j in range(1, mc.fail_bars + 1)))
    if a_ok:
        mv = f"bullisches Kreuz vor {cross_age} T."
    elif mh[-1] < 0:
        mv = f"Histogramm {'steigt seit ≥ 4 T.' if rising else 'steigt nicht seit 4 T.'}, |Hist| = {pct(ratio, 0)} des 30-T.-Tiefs"
    else:
        mv = f"Histogramm grün, letztes Kreuz vor {cross_age} T."
    if failed:
        mv += "; Fehlsignal (nach Kreuz wieder fallend)"
    add("macd_turn", "MACD dreht (Kreuz ≤ 7 T. oder Histogramm steigt Richtung 0)", bool((a_ok or b_ok) and not failed),
        mv, "(a) Kreuz ≤ 7 T. oder (b) ≥ 4 T. steigend und ≤ 25 % des Tiefs")
    res.flags.update(macd_cross_done=bool(a_ok), macd_cross_age=cross_age, macd_hist=mh[-1],
                     macd_divergence=bool(div and ml[div[2]] > ml[div[1]]))

    # ---------- 2.6 MBI ----------
    bc = cfg.mbi
    x_ok, xv = False, "kein grünes X in den letzten 15 Kerzen"
    for ix in reversed([i for i in range(max(2, n - bc.x_max_age), n) if gx[i]]):
        peak = float(lo_b[ix - 1])
        above_ref = peak > bound[ix - 1]
        fading = lo_b[-1] <= bc.max_peak_ratio * peak or up_b[-1] > lo_b[-1]
        new_peak = float(np.nanmax(lo_b[ix:])) > peak
        xv = (f"grünes X vor {n - 1 - ix} T., Spitze {de(peak, 0)} (Linie {de(bound[ix - 1], 0)}), "
              f"jetzt rot {de(lo_b[-1], 0)} / grün {de(up_b[-1], 0)}" + ("; neue höhere rote Spitze" if new_peak else ""))
        if above_ref and fading and not new_peak:
            x_ok = True
            break
    add("mbi", "MBI: grünes X auf roter Spitze, Verkaufsdruck läuft aus", x_ok, xv,
        "X ≤ 15 T., Spitze über Linie, rot ≤ 70 % der Spitze oder grün")
    res.flags["mbi_green"] = bool(up_b[-1] > lo_b[-1])
    res.flags["mbi_source"] = "Original (AlgoAlpha-Port)"

    # ---------- 3. Trade-Plan & 2.7 CRV ----------
    rk = cfg.risk
    entry = close
    stops = []
    if zone_a and zone_a["ok"]:
        s = zone_a["levels"]["0.886"]
        if entry - s < rk.stop_atr_fib * a14[-1]:
            s = zone_a["L"] * (1 - rk.stop_below_l)
        stops.append(s)
    if zone_b:
        stops.append(zone_b["band"][0] * (1 - rk.stop_below_zone))
    if stops and H:
        stop = min(min(stops), entry - rk.stop_min_atr * a14[-1])
        t1_cands = [x for x in (e50[-1], zone_a["levels"]["0.382"] if zone_a else None) if x and x > entry]
        target1 = min(t1_cands) if t1_cands else None
        crv = (H - entry) / (entry - stop) if entry > stop else None
        stop_pct = (entry - stop) / entry
        res.plan = {"entry": entry, "buy_stop": float(h[-rk.buy_stop_bars:].max()), "stop": stop,
                    "target1": target1, "target2": H, "crv": crv, "stop_pct": stop_pct,
                    "max_leverage": 1 / (stop_pct * rk.leverage_factor) if stop_pct > 0 else None}
    crv = res.plan.get("crv")
    add("crv", "Chance-Risiko (Ziel 2 / Stop) ≥ 2,0", crv is not None and crv >= rk.min_crv,
        "kein Trade-Plan (keine Zone)" if crv is None else de(crv, 2), "≥ 2,0")

    # Earnings (kein Ausschluss, nur Abzug)
    ed = info.get("earnings_date")
    soon = False
    if ed:
        days = int(np.busday_count(df.index[-1].date(), pd.Timestamp(ed).date()))
        soon = 0 <= days <= rk.earnings_days
    res.flags.update(earnings_date=ed, earnings_risk=soon)

    # Volumen-Climax: höchstes 20-T.-Volumen mit langer unterer Lunte in der Zone
    j = n - 20 + int(np.argmax(v[-20:]))
    rngj = h[j] - l[j]
    res.flags["volume_climax"] = bool(rngj > 0 and (min(o[j], c[j]) - l[j]) >= 0.5 * rngj and in_band(l[j]))
    res.flags["fib_core"] = bool(zone_a and zone_a["ok"] and zone_a["core"])
    res.flags["support_3_touches"] = bool(zone_b and zone_b["touches"] >= 3)
    res.flags["overlap"] = bool(zone_a and zone_a["ok"] and zone_b
                                and zone_a["levels"]["0.79"] * 0.97 <= zone_b["center"] <= zone_a["levels"]["0.618"] * 1.03)
    res.flags["ema200_in_zone"] = bool(bands and any(lo * 0.98 <= e200[-1] <= hi * 1.02 for lo, hi in bands))

    res.score, res.bonuses = score_setup(res, cfg)
    return res
