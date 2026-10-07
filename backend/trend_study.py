"""Studie Trend-Rücksetzer: Welche Rücksetzer bleiben kurz, welche werden zur richtigen Korrektur?

Für jedes historische Trend-Rücksetzer-Signal (gleiche Regeln wie trend.py, Kennzahlen vektorisiert) wird gemessen,
was in den nächsten 60 Handelstagen passiert:

  ok   = neues Hoch über dem letzten Hoch R, BEVOR der Kurs unter das 50-%-Fibonacci-Niveau des letzten Anstiegs schließt
  korr = Schluss unter dem 50-%-Niveau zuerst (richtige Korrektur)
  (weder noch in 60 Tagen → seitwärts, zählt als „nicht ok“)

Dann: Welche Merkmale AM SIGNALTAG unterscheiden die Gruppen? (Einzeltabellen + logistisches Modell, gelernt an einer
Hälfte der Aktien, geprüft an der anderen und zusätzlich zeitlich getrennt.) Außerdem drei Einstiegsvarianten:
  A sofort (Schlusskurs am Signaltag) · B Wendesignal (Schluss über dem Vortageshoch, max. 10 Tage)
  C Limit im Fibonacci-Bereich (50-%-Niveau, max. 20 Tage)

    python -m backend.trend_study [--n 900] [--period 7y]

Ergebnis: data/trend_model.json und eine Zusammenfassung im Log (zwischen ===BEGIN/END=== als JSON).
"""

from __future__ import annotations

import argparse
import json
import math
import random
import time

import numpy as np
import pandas as pd

from .config import CONFIG, ROOT
from .indicators import atr as atr_ind, ema, rsi as rsi_ind

OUT = ROOT / "data" / "trend_model.json"
HZ = 60

# Merkmal → Text für die App (Vorzeichen: positiv = spricht für „nur Rücksetzer“)
LABELS = {
    "g200": "Abstand zur EMA 200",
    "g50": "Abstand zur EMA 50",
    "rsi": "RSI",
    "rsi_drop": "RSI-Rückgang seit dem Hoch",
    "atrp": "Schwankung (ATR in % vom Kurs)",
    "retr": "bisherige Korrekturtiefe (Anteil des letzten Anstiegs)",
    "days": "Tage seit dem letzten Hoch",
    "speed": "Tempo des Rücksetzers",
    "leg": "Größe des letzten Anstiegs",
    "vol5": "Volumen der letzten 5 Tage vs. 50-Tage-Schnitt",
    "dnvol": "Volumen an roten vs. grünen Tagen (10 T.)",
    "red10": "Anzahl roter Tage (10 T.)",
    "worst": "größter Tagesverlust (10 T.)",
    "e50slope": "Steigung der EMA 50",
    "wk": "Wochentrend (EMA 100 steigt)",
    "vix": "VIX",
    "top": "Stufe „Top“",
}


def _ind(df: pd.DataFrame) -> dict:
    c, h, l, v = (df[k].to_numpy(float) for k in ("Close", "High", "Low", "Volume"))
    s = df["Close"]
    return {"c": c, "h": h, "l": l, "v": v, "e50": ema(s, 50).to_numpy(float), "e200": ema(s, 200).to_numpy(float),
            "e100": ema(s, 100).to_numpy(float), "rsi": rsi_ind(s, 14).to_numpy(float), "atr": atr_ind(df, 14).to_numpy(float)}


def _index_feats(idx: pd.DataFrame) -> pd.DataFrame:
    s = idx["Close"]
    return pd.DataFrame({"mkt50": (s > ema(s, 50)).astype(float), "mkt20": s / s.shift(20) - 1, "ret63": s / s.shift(63) - 1})


CLIP = {"dnvol": (0, 5), "leg": (0, 5), "speed": (0, 10), "vol5": (0, 4), "atrp": (0, .2), "worst": (-.3, 0), "vix": (9, 60)}


def leg_at(h: np.ndarray, l: np.ndarray, i: int):
    """Letztes Hoch R (30 T.) und das Tief L davor (120 T.) – der zuletzt gelaufene Anstieg."""
    j0 = max(0, i - 29)
    ri = j0 + int(np.argmax(h[j0:i + 1]))
    li = max(0, ri - 120) + int(np.argmin(l[max(0, ri - 120):ri + 1]))
    return ri, float(h[ri]), float(l[li])


def feats_at(x: dict, i: int, ri: int, R: float, L: float, top: bool, vix: float) -> dict:
    c, v, r = x["c"], x["v"], x["rsi"]
    chg = c[i - 9:i + 1] / c[i - 10:i] - 1
    vv = v[i - 9:i + 1]
    upv = float(np.sum(vv[chg > 0]))
    dnv = float(np.sum(vv[chg < 0]))
    days = i - ri
    f = {
        "g200": c[i] / x["e200"][i] - 1, "g50": c[i] / x["e50"][i] - 1, "rsi": float(r[i]),
        "rsi_drop": float(np.nanmax(r[max(0, ri - 2):ri + 3]) - r[i]),
        "atrp": float(x["atr"][i] / c[i]), "retr": (R - c[i]) / (R - L), "days": float(days),
        "speed": (R - c[i]) / R / max(days, 1) * 100, "leg": R / L - 1,
        "vol5": float(np.mean(v[i - 4:i + 1]) / (np.mean(v[i - 49:i + 1]) or 1)),
        "dnvol": dnv / upv if upv > 0 else 5.0, "red10": float(np.sum(chg < 0)), "worst": float(np.min(chg)),
        "e50slope": x["e50"][i] / x["e50"][i - 10] - 1, "wk": float(x["e100"][i] > x["e100"][i - 10]),
        "vix": vix, "top": float(top),
    }
    for k, (lo, hi) in CLIP.items():
        f[k] = float(min(hi, max(lo, f[k])))
    return {k: float(val) for k, val in f.items()}


def signals(t: str, df: pd.DataFrame, mk: pd.DataFrame, vix: pd.Series) -> list[dict]:
    tc = CONFIG.trend
    if len(df) < 320:
        return []
    x = _ind(df)
    c, h, l, v, e50, e200, r, a = x["c"], x["h"], x["l"], x["v"], x["e50"], x["e200"], x["rsi"], x["atr"]
    n = len(c)
    dates = df.index
    g200 = c / e200 - 1
    g50 = c / e50 - 1
    cond = (g200 >= tc.min_above_ema200) & (g50 >= tc.dip_min) & (g50 <= tc.dip_max) & (r >= tc.rsi_min) & (r <= tc.rsi_max)
    dv = c * v
    out, last = [], -99
    mk = mk.reindex(dates).ffill()
    vx = vix.reindex(dates).ffill().to_numpy(float)
    for i in range(260, n - 1):
        if not cond[i] or cond[i - 1] or i - last < 15:
            continue
        if c[i] < 1 or np.nanmean(dv[i - 19:i + 1]) < 5e6:          # Grundfilter grob wie im Scanner (Liquidität, Kurs)
            continue
        last = i
        # letztes Hoch R (30 T.) und Tief L davor (120 T.) → Fibonacci des letzten Anstiegs
        ri, R, L = leg_at(h, l, i)
        if R <= L:
            continue
        f50, f618, f786 = R - .5 * (R - L), R - .618 * (R - L), R - .786 * (R - L)
        # Swing-High wie im Scanner (Alter 20–180 T.) für „Top“
        H = float(np.max(h[max(0, i - 180):i - 19])) if i - 19 > 0 else R
        dd = (H - c[i]) / H if H else None
        atrp = a[i] / c[i]
        tt = tc.top
        top = bool(dd is not None and dd < tt.max_from_high and atrp < tt.max_atr_pct and g200[i] < tt.max_above_ema200)
        # ----- Ergebnis: neues Hoch vor Schluss unter 50 % ?
        end = min(n, i + 1 + HZ)
        res = "side"
        for k in range(i + 1, end):
            if c[k] < f50:
                res = "korr"; break
            if h[k] > R:
                res = "ok"; break
        if end - i - 1 < 20:
            continue
        # ----- Einstiegsvarianten (Ziel = R, Ausstieg spätestens nach 60 T. zum Schluss)
        def trade(e_i, entry, stop):
            risk = entry - stop
            if risk <= 0:
                return None
            for k in range(e_i + 1, min(n, e_i + 1 + HZ)):
                if l[k] <= stop:
                    return -1.0
                if h[k] >= R:
                    return (R - entry) / risk
            k = min(n, e_i + 1 + HZ) - 1
            return (c[k] - entry) / risk
        stopA = min(float(np.min(l[i - 9:i + 1])) - .25 * a[i], c[i] - a[i])
        A = trade(i, c[i], stopA)
        B = None
        for k in range(i + 1, min(n, i + 11)):
            if l[k] <= stopA:
                break                                               # vorher ausgestoppt → kein Einstieg (vermieden)
            if c[k] > h[k - 1]:
                st = min(float(np.min(l[k - 9:k + 1])) - .25 * a[k], c[k] - a[k])
                B = trade(k, c[k], st)
                break
        C = None
        stC = f786 - .25 * a[i]
        if c[i] <= f50:
            C = trade(i, c[i], min(stC, c[i] - a[i]))
        else:
            for k in range(i + 1, min(n, i + 21)):
                if h[k] >= R:
                    break                                           # vorher neues Hoch → verpasst
                if l[k] <= f50:
                    ent = min(f50, float(df["Open"].iloc[k]))
                    C = trade(k, ent, min(stC, ent - a[k]))
                    break
        ret60 = c[min(n - 1, i + HZ)] / c[i] - 1
        # ----- Turbo ohne Stop (nur K.-o.): Ausstieg am Ziel R oder nach 60 T.; Ergebnis in % des Turbo-Einsatzes
        def turbo(ko):
            if ko >= c[i] or ko <= 0:
                return None
            for k in range(i + 1, min(n, i + 1 + HZ)):
                if l[k] <= ko:
                    return -1.0
                if h[k] >= R:
                    return (R - ko) / (c[i] - ko) - 1
            k = min(n, i + 1 + HZ) - 1
            return (c[k] - ko) / (c[i] - ko) - 1
        ko_std = stopA - a[i]                                       # App-Vorschlag: 1 ATR unter dem Stop
        ko_wide = min(ko_std, f618 - .25 * a[i])                    # unter das 61,8-%-Niveau
        TS, TW = turbo(ko_std), turbo(ko_wide)
        feat = feats_at(x, i, ri, R, L, top, float(vx[i]) if not math.isnan(vx[i]) else 20.0)
        if any(isinstance(val, float) and (math.isnan(val) or math.isinf(val)) for val in feat.values()):
            continue
        out.append({"t": t, "d": str(dates[i].date()), "res": res, "A": A, "B": B, "C": C, "ret60": ret60, "TS": TS, "TW": TW, "lev_s": c[i] / (c[i] - ko_std), "lev_w": c[i] / (c[i] - ko_wide), "x": feat})
    return out


# Gründe für die App aus den gemessenen Quoten der Studie (Einzelmerkmale): (Text, Wert-Format)
REASON = {
    "retr": lambda f: f"Rücksetzer bisher {f['retr'] * 100:.0f} % des letzten Anstiegs",
    "speed": lambda f: "langsamer Rücksetzer" if f["speed"] < 1 else "schneller Abverkauf",
    "worst": lambda f: f"größter Tagesverlust zuletzt {f['worst'] * 100:.0f} %".replace(".", ","),
    "atrp": lambda f: f"Tagesschwankung (ATR) {f['atrp'] * 100:.1f} %".replace(".", ","),
    "rsi_drop": lambda f: f"RSI seit dem Hoch um {f['rsi_drop']:.0f} Punkte gefallen",
    "e50slope": lambda f: "EMA 50 steigt sehr steil – Trend überhitzt" if f["e50slope"] > .0357 else "EMA 50 steigt gleichmäßig",
    "vix": lambda f: f"VIX bei {f['vix']:.0f}" + (" – Angst im Markt" if f["vix"] > 24 else ""),
    "g50": lambda f: f"Kurs {abs(f['g50']) * 100:.1f} % unter der EMA 50".replace(".", ","),
    "wk": lambda f: "Wochentrend intakt" if f["wk"] else "Wochentrend dreht nach unten",
}


def predict(df: pd.DataFrame, top: bool, vix: float | None, model: dict | None = None) -> dict | None:
    """Rücksetzer-Check für das aktuelle Signal: Wahrscheinlichkeit „nur Rücksetzer“ + wichtigste Gründe."""
    model = model or load_model()
    if not model or len(df) < 260:
        return None
    x = _ind(df)
    i = len(x["c"]) - 1
    ri, R, L = leg_at(x["h"], x["l"], i)
    if R <= L:
        return None
    f = feats_at(x, i, ri, R, L, top, vix if vix else 20.0)
    names, mu, sd, w = model["names"], np.array(model["mu"]), np.maximum(np.array(model["sd"]), 1e-3), np.array(model["w"])
    z = (np.array([f[k] for k in names]) - mu) / sd
    contrib = w[1:] * z
    p = float(1 / (1 + np.exp(-(w[0] + contrib.sum()))))
    base = model.get("base_ok", .46)
    pro, con = [], []
    for k, bins in (model.get("single") or {}).items():
        if k not in REASON or k not in f:
            continue
        v = f[k]
        if k == "g50" and v > 0:
            continue
        hit = next((g for g in bins if ("bin" in g and v == g["bin"]) or ("lo" in g and g["lo"] <= v <= g["hi"])),
                   None if "bin" in bins[0] else (bins[0] if v < bins[0]["lo"] else bins[-1]))
        if not hit or abs(hit["ok"] - base) < .06:
            continue
        item = (abs(hit["ok"] - base), f"{REASON[k](f)} – in der Studie {hit['ok'] * 100:.0f} % reine Rücksetzer")
        (pro if hit["ok"] > base else con).append(item)
    pro = [t for _, t in sorted(pro, reverse=True)]
    con = [t for _, t in sorted(con, reverse=True)]
    q = model.get("quint") or []
    grp = next((g for g in q if p <= g["p_hi"]), q[-1] if q else None)
    return {"p": round(p, 3), "pro": pro[:3], "con": con[:3], "fib50": round(R - .5 * (R - L), 4), "hi": round(R, 4),
            "korr": grp and grp.get("korr"), "ok": grp and grp.get("ok")}


_MODEL = None


def load_model() -> dict | None:
    global _MODEL
    if _MODEL is None:
        try:
            _MODEL = json.loads(OUT.read_text(encoding="utf-8")).get("model") or {}
        except Exception:
            _MODEL = {}
    return _MODEL or None


def _auc(p, y):
    o = np.argsort(p)
    ranks = np.empty(len(p)); ranks[o] = np.arange(1, len(p) + 1)
    n1 = y.sum(); n0 = len(y) - n1
    return float((ranks[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)) if n1 and n0 else None


def _logit(X, y, lam=1.0, it=400):
    w = np.zeros(X.shape[1])
    for _ in range(it):                                             # Newton-Verfahren mit L2
        p = 1 / (1 + np.exp(-X @ w))
        g = X.T @ (p - y) + lam * np.r_[0, w[1:]]
        H = (X * (p * (1 - p))[:, None]).T @ X + lam * np.diag(np.r_[0, np.ones(len(w) - 1)])
        step = np.linalg.solve(H, g)
        w -= step
        if np.abs(step).max() < 1e-7:
            break
    return w


def _var(rows, key):
    xs = [r[key] for r in rows if r[key] is not None]
    taken = len(xs)
    return {"n": len(rows), "taken": taken, "miss": round(1 - taken / len(rows), 3) if rows else None,
            "avgR_taken": round(float(np.mean(xs)), 3) if xs else None,
            "avgR_signal": round(float(np.sum(xs)) / len(rows), 3) if rows else None,
            "win": round(float(np.mean([x > 0 for x in xs])), 3) if xs else None,
            "stopped": round(float(np.mean([x == -1.0 for x in xs])), 3) if xs else None}


def study(n: int, period: str, seed: int = 11) -> dict:
    from .data_provider import YFinanceProvider
    from .universe import load as load_universe

    uni = load_universe()
    uni = uni[uni["region"].isin(["us", "europe"])]
    tickers = list(uni["ticker"])
    random.Random(seed).shuffle(tickers)
    tickers = tickers[:n]
    prov = YFinanceProvider()
    idx = prov.history(["^GSPC", "^STOXX", "^VIX"], period)
    region = dict(zip(uni["ticker"], uni["region"]))
    mk = {"us": _index_feats(idx["^GSPC"]), "europe": _index_feats(idx.get("^STOXX", idx["^GSPC"]))}
    vix = idx["^VIX"]["Close"]
    data = prov.history(tickers, period)
    print(f"Kurse: {len(data)} von {len(tickers)}")
    ev, t0 = [], time.time()
    for k, (t, df) in enumerate(data.items()):
        try:
            ev += signals(t, df, mk[region.get(t, "us")], vix)
        except Exception as exc:
            print(f"  {t}: {exc!r}")
        if k % 100 == 0:
            print(f"  {k} Aktien, {len(ev)} Signale, {time.time() - t0:.0f} s")
    print(f"Signale: {len(ev)}")
    names = list(LABELS)
    y = np.array([e["res"] == "ok" for e in ev], float)
    base = {"n": len(ev), "ok": round(float(y.mean()), 3), "korr": round(float(np.mean([e["res"] == "korr" for e in ev])), 3),
            "side": round(float(np.mean([e["res"] == "side" for e in ev])), 3),
            "ret60": round(float(np.mean([e["ret60"] for e in ev])), 4)}
    top = [e for e in ev if e["x"]["top"]]
    base_top = {"n": len(top), "ok": round(float(np.mean([e["res"] == "ok" for e in top])), 3) if top else None,
                "korr": round(float(np.mean([e["res"] == "korr" for e in top])), 3) if top else None}
    # Einzelmerkmale: Quintile → Anteil „ok“
    single = {}
    for f in names:
        vals = np.array([e["x"][f] for e in ev])
        if len(set(vals)) <= 2:
            groups = [(lv, vals == lv) for lv in sorted(set(vals))]
            single[f] = [{"bin": float(lv), "n": int(m.sum()), "ok": round(float(y[m].mean()), 3)} for lv, m in groups]
        else:
            qs = np.quantile(vals, [0, .2, .4, .6, .8, 1])
            rows = []
            for q in range(5):
                m = (vals >= qs[q]) & ((vals < qs[q + 1]) if q < 4 else (vals <= qs[q + 1]))
                rows.append({"lo": round(float(qs[q]), 4), "hi": round(float(qs[q + 1]), 4), "n": int(m.sum()), "ok": round(float(y[m].mean()), 3) if m.any() else None})
            single[f] = rows
    # Modell: Hälfte der Aktien lernen, andere Hälfte prüfen; zusätzlich zeitlich (vor/nach Mitte)
    X = np.array([[e["x"][f] for f in names] for e in ev], float)
    mu, sd = X.mean(0), np.maximum(X.std(0), 1e-3)
    Z = np.c_[np.ones(len(X)), (X - mu) / sd]
    ticks = sorted({e["t"] for e in ev})
    test_t = set(ticks[1::2])
    te = np.array([e["t"] in test_t for e in ev])
    w = _logit(Z[~te], y[~te])
    p = 1 / (1 + np.exp(-Z @ w))
    dmid = sorted(e["d"] for e in ev)[len(ev) // 2]
    late = np.array([e["d"] >= dmid for e in ev])
    w_time = _logit(Z[~late], y[~late])
    p_time = 1 / (1 + np.exp(-Z @ w_time))

    def calib(pp, mask):
        qs = np.quantile(pp[mask], [0, .2, .4, .6, .8, 1])
        out = []
        for q in range(5):
            m = mask & (pp >= qs[q]) & ((pp < qs[q + 1]) if q < 4 else (pp <= qs[q + 1]))
            sel = [ev[i] for i in np.where(m)[0]]
            out.append({"p_lo": round(float(qs[q]), 3), "p_hi": round(float(qs[q + 1]), 3), "n": int(m.sum()),
                        "ok": round(float(y[m].mean()), 3) if m.any() else None,
                        "korr": round(float(np.mean([e["res"] == "korr" for e in sel])), 3) if sel else None,
                        "A": _var(sel, "A")["avgR_signal"], "B": _var(sel, "B")["avgR_signal"], "C": _var(sel, "C")["avgR_signal"],
                        "ret60": round(float(np.mean([e["ret60"] for e in sel])), 4) if sel else None})
        return out

    model = {"names": names, "mu": mu.round(6).tolist(), "sd": sd.round(6).tolist(), "w": w.round(5).tolist(),
             "labels": LABELS, "horizon": HZ,
             "auc_train": _auc(p[~te], y[~te]), "auc_test": _auc(p[te], y[te]),
             "auc_time_test": _auc(p_time[late], y[late]), "split_date": dmid,
             "calib_test": calib(p, te), "calib_time_test": calib(p_time, late),
             "quint": [{"p_hi": q["p_hi"], "ok": q["ok"], "korr": q["korr"]} for q in calib(p, te)],
             "base_ok": base["ok"], "single": {k: single[k] for k in REASON if k in single},
             "coef": sorted([[f, round(float(wi), 3)] for f, wi in zip(names, w[1:])], key=lambda z: -abs(z[1]))}
    def tstats(sel, key):
        xs = [e[key] for e in sel if e[key] is not None]
        lk = "lev_s" if key == "TS" else "lev_w"
        ex = [e[key] / e[lk] for e in sel if e[key] is not None]      # bezogen auf gleich viel Aktien-Gegenwert
        return {"n": len(xs), "avg": round(float(np.mean(xs)), 4) if xs else None, "exp": round(float(np.mean(ex)), 4) if ex else None, "ko": round(float(np.mean([x == -1.0 for x in xs])), 3) if xs else None,
                "lev": round(float(np.median([e["lev_s" if key == "TS" else "lev_w"] for e in sel])), 2) if sel else None}

    def turbo_eval(pp, mask, cut):
        sel = [ev[i] for i in np.where(mask)[0]]
        pr = {id(ev[i]): pp[i] for i in np.where(mask)[0]}
        qs = np.quantile(pp[mask], [0, .2, .4, .6, .8, 1])
        quint = []
        for q in range(5):
            m = mask & (pp >= qs[q]) & ((pp < qs[q + 1]) if q < 4 else (pp <= qs[q + 1]))
            ss = [ev[i] for i in np.where(m)[0]]
            quint.append({"p_hi": round(float(qs[q + 1]), 3), "std": tstats(ss, "TS"), "wide": tstats(ss, "TW")})
        mix = [e["TW"] if pr[id(e)] < cut else e["TS"] for e in sel if e["TS"] is not None and e["TW"] is not None]
        mix_exp = [(e["TW"] / e["lev_w"]) if pr[id(e)] < cut else (e["TS"] / e["lev_s"]) for e in sel if e["TS"] is not None and e["TW"] is not None]
        skip = [e["TS"] if pr[id(e)] >= cut else 0.0 for e in sel if e["TS"] is not None]
        return {"all_std": tstats(sel, "TS"), "all_wide": tstats(sel, "TW"),
                "mix_wide_if_red": round(float(np.mean(mix)), 4) if mix else None, "mix_exp": round(float(np.mean(mix_exp)), 4) if mix_exp else None,
                "skip_red_std": round(float(np.mean(skip)), 4) if skip else None, "cut": cut, "quint": quint}

    turbo_res = {"test": turbo_eval(p, te, .4), "time_test": turbo_eval(p_time, late, .4)}
    entries = {k: _var(ev, k) for k in ("A", "B", "C")}
    entries_top = {k: _var(top, k) for k in ("A", "B", "C")}
    return {"generated": time.strftime("%Y-%m-%d"), "period": period, "n_stocks": len(data),
            "range": [min(e["d"] for e in ev), max(e["d"] for e in ev)], "base": base, "base_top": base_top,
            "entries": entries, "entries_top": entries_top, "turbo": turbo_res, "single": single, "model": model}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=900)
    ap.add_argument("--period", default="7y")
    a = ap.parse_args(argv)
    res = study(a.n, a.period)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("===BEGIN===")
    print(json.dumps(res, ensure_ascii=False, separators=(",", ":")))
    print("===END===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
