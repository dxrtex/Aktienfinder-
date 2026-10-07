"""Studie Trend-Rücksetzer v2: Lässt sich der Rücksetzer-Check verbessern?

Gleiche Signale und Zielgröße wie trend_study.py (neues Hoch vor Schluss unter 50 % Fibonacci, 60 Handelstage),
aber mehr Daten (bis 10 Jahre, mehr Aktien) und zusätzliche Merkmale am Signaltag:

  sup     Abstand zum alten Hoch (120–25 Tage zurück), wenn es UNTER dem Kurs liegt (Unterstützung); sonst 0,3
  rev     Umkehrkerze am Signaltag (Hammer oder bullisches Engulfing) – 0/1
  cpos    Lage des Schlusskurses in der Tagesspanne (0 = Tief, 1 = Hoch)
  g20     Abstand zur EMA 20
  sec50   Sektor-ETF über seiner EMA 50 (0/1, 0,5 = unbekannt)
  sec20   Sektor-ETF-Entwicklung 20 Tage

Verglichen werden drei Modelle, jeweils an fremden Aktien UND an späteren Jahren geprüft:
  L    linear (logistisch) mit den bisherigen Merkmalen        – Ausgangspunkt
  L+   linear mit allen Merkmalen
  B    „Bereichs-Modell“: jedes Merkmal in 5 Bereiche (Quintile), je Bereich ein Gewicht – erkennt Knicke/U-Formen,
       bleibt aber in der App als einfache Tabelle rechenbar
  GBM  Gradient Boosting (scikit-learn) – nur als Obergrenze dessen, was in den Daten steckt

    python -m backend.trend_study2 [--n 2500] [--period 10y]
"""

from __future__ import annotations

import argparse
import json
import math
import random
import time

import numpy as np
import pandas as pd

from . import trend_study as ts
from .config import ROOT
from .indicators import ema

OUT = ROOT / "data" / "trend_model_v2.json"
BASE = list(ts.LABELS)                       # Merkmale von v1
EXTRA = ["sup", "rev", "cpos", "g20", "sec50", "sec20"]
SECTOR_ETF = {"Technology": "XLK", "Financial Services": "XLF", "Healthcare": "XLV", "Consumer Cyclical": "XLY",
              "Consumer Defensive": "XLP", "Energy": "XLE", "Industrials": "XLI", "Basic Materials": "XLB",
              "Utilities": "XLU", "Real Estate": "XLRE", "Communication Services": "XLC"}


def extras(df: pd.DataFrame, i: int, sec: pd.DataFrame | None) -> dict:
    o, h, l, c = (df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
    lvl = float(np.max(h[max(0, i - 120):i - 24])) if i > 30 else np.nan
    sup = (c[i] - lvl) / c[i] if lvl == lvl and lvl < c[i] else 0.3
    rng = h[i] - l[i]
    body = abs(c[i] - o[i])
    lower = min(o[i], c[i]) - l[i]
    hammer = rng > 0 and lower >= 2 * body and (c[i] - l[i]) / rng >= .6
    engulf = c[i] > o[i] and c[i - 1] < o[i - 1] and c[i] >= o[i - 1] and o[i] <= c[i - 1]
    e20 = ema(df["Close"], 20).to_numpy(float)
    f = {"sup": float(min(.3, max(0, sup))), "rev": float(hammer or engulf), "cpos": float((c[i] - l[i]) / rng) if rng > 0 else .5,
         "g20": float(max(-.2, min(.2, c[i] / e20[i] - 1))), "sec50": .5, "sec20": 0.0}
    if sec is not None:
        d = df.index[i]
        row = sec.loc[:d].tail(1)
        if len(row):
            f["sec50"] = float(row["above50"].iloc[0])
            f["sec20"] = float(max(-.15, min(.15, row["ret20"].iloc[0])))
    return f


def _auc(p, y):
    return ts._auc(np.asarray(p), np.asarray(y))


def _std(X, mu=None, sd=None):
    mu = X.mean(0) if mu is None else mu
    sd = np.maximum(X.std(0), 1e-3) if sd is None else sd
    return np.c_[np.ones(len(X)), (X - mu) / sd], mu, sd


def _bins(X, edges=None):
    """One-hot je Merkmal und Quintil (Bereichs-Modell). Binäre Merkmale behalten 2 Stufen."""
    if edges is None:
        edges = []
        for j in range(X.shape[1]):
            u = np.unique(X[:, j])
            edges.append([] if len(u) <= 2 else list(np.unique(np.quantile(X[:, j], [.2, .4, .6, .8]))))
    cols = [np.ones(len(X))]
    for j, e in enumerate(edges):
        if not e:
            cols.append(X[:, j])
            continue
        k = np.searchsorted(e, X[:, j], side="right")
        for b in range(1, len(e) + 1):                       # Bereich 0 = Referenz
            cols.append((k == b).astype(float))
    return np.column_stack(cols), edges


def evaluate(ev: list[dict], names: list[str]) -> dict:
    X = np.array([[e["x"][f] for f in names] for e in ev], float)
    y = np.array([e["res"] == "ok" for e in ev], float)
    ticks = sorted({e["t"] for e in ev})
    te = np.array([e["t"] in set(ticks[1::2]) for e in ev])
    dmid = sorted(e["d"] for e in ev)[len(ev) // 2]
    late = np.array([e["d"] >= dmid for e in ev])
    out = {}
    for split, mask in (("aktien", te), ("zeit", late)):
        tr = ~mask
        Z, mu, sd = _std(X[tr]); w = ts._logit(Z, y[tr]); Zt, _, _ = _std(X[mask], mu, sd)
        pl = 1 / (1 + np.exp(-Zt @ w))
        Bt, edges = _bins(X[tr]); wb = ts._logit(Bt, y[tr], lam=3.0); Bv, _ = _bins(X[mask], edges)
        pb = 1 / (1 + np.exp(-Bv @ wb))
        r = {"linear": _auc(pl, y[mask]), "bereiche": _auc(pb, y[mask])}
        try:
            from sklearn.ensemble import HistGradientBoostingClassifier
            g = HistGradientBoostingClassifier(max_depth=3, learning_rate=.05, max_iter=300, l2_regularization=1.0, random_state=1)
            g.fit(X[tr], y[tr]); r["gbm"] = _auc(g.predict_proba(X[mask])[:, 1], y[mask])
        except Exception as exc:
            r["gbm"] = None; r["gbm_err"] = repr(exc)[:80]
        # Trennschärfe: Anteil „ok“ im schlechtesten/besten Fünftel (Bereichs-Modell)
        q = np.quantile(pb, [.2, .8])
        r["bereiche_q1_ok"] = round(float(y[mask][pb <= q[0]].mean()), 3); r["bereiche_q5_ok"] = round(float(y[mask][pb >= q[1]].mean()), 3)
        q = np.quantile(pl, [.2, .8])
        r["linear_q1_ok"] = round(float(y[mask][pl <= q[0]].mean()), 3); r["linear_q5_ok"] = round(float(y[mask][pl >= q[1]].mean()), 3)
        out[split] = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()}
    return out


def fit_final(ev, names):
    """Bereichs-Modell auf allen Daten (für die App): Kanten + Gewichte."""
    X = np.array([[e["x"][f] for f in names] for e in ev], float)
    y = np.array([e["res"] == "ok" for e in ev], float)
    B, edges = _bins(X); w = ts._logit(B, y, lam=3.0)
    p = 1 / (1 + np.exp(-B @ w))
    qs = np.quantile(p, [.2, .4, .6, .8, 1])
    quint = []
    lo = -1
    for q in qs:
        m = (p > lo) & (p <= q)
        sel = [ev[i] for i in np.where(m)[0]]
        quint.append({"p_hi": round(float(q), 3), "ok": round(float(y[m].mean()), 3), "korr": round(float(np.mean([e["res"] == "korr" for e in sel])), 3)})
        lo = q
    return {"type": "bins", "names": names, "edges": [[round(float(v), 5) for v in e] for e in edges], "w": [round(float(v), 5) for v in w], "quint": quint}


def study(n: int, period: str, seed: int = 21) -> dict:
    from .data_provider import YFinanceProvider
    from .universe import load as load_universe

    uni = load_universe()
    uni = uni[uni["region"].isin(["us", "europe"])]
    tickers = list(uni["ticker"]); random.Random(seed).shuffle(tickers); tickers = tickers[:n]
    sector = dict(zip(uni["ticker"], uni.get("sector", pd.Series([""] * len(uni)))))
    region = dict(zip(uni["ticker"], uni["region"]))
    prov = YFinanceProvider()
    idx = prov.history(["^GSPC", "^STOXX", "^VIX"] + sorted(set(SECTOR_ETF.values())), period)
    mk = {"us": ts._index_feats(idx["^GSPC"]), "europe": ts._index_feats(idx.get("^STOXX", idx["^GSPC"]))}
    vix = idx["^VIX"]["Close"]
    secs = {}
    for name, etf in SECTOR_ETF.items():
        if etf in idx:
            s = idx[etf]["Close"]
            secs[name] = pd.DataFrame({"above50": (s > ema(s, 50)).astype(float), "ret20": s / s.shift(20) - 1})
    data = prov.history(tickers, period)
    print(f"Kurse: {len(data)} von {len(tickers)}, Sektor-ETFs: {len(secs)}")
    ev, t0 = [], time.time()
    for k, (t, df) in enumerate(data.items()):
        try:
            sig = ts.signals(t, df, mk[region.get(t, "us")], vix)
            if sig:
                pos = {str(d.date()): j for j, d in enumerate(df.index)}
                sec = secs.get(sector.get(t) or "")
                for e in sig:
                    j = pos.get(e["d"])
                    if j is not None:
                        e["x"].update(extras(df, j, sec))
                        ev.append(e)
        except Exception as exc:
            print(f"  {t}: {exc!r}")
        if k % 250 == 0:
            print(f"  {k} Aktien, {len(ev)} Signale, {time.time() - t0:.0f} s")
    print(f"Signale: {len(ev)}")
    y = np.array([e["res"] == "ok" for e in ev], float)
    single = {}
    for f in EXTRA:
        vals = np.array([e["x"][f] for e in ev])
        if len(set(vals)) <= 3:
            single[f] = [{"v": float(v), "n": int((vals == v).sum()), "ok": round(float(y[vals == v].mean()), 3)} for v in sorted(set(vals))]
        else:
            qs = np.quantile(vals, [0, .2, .4, .6, .8, 1])
            single[f] = [{"lo": round(float(qs[q]), 4), "hi": round(float(qs[q + 1]), 4),
                          "ok": round(float(y[(vals >= qs[q]) & (vals <= qs[q + 1])].mean()), 3)} for q in range(5)]
    res = {"generated": time.strftime("%Y-%m-%d"), "period": period, "n_stocks": len(data), "n_signals": len(ev),
           "range": [min(e["d"] for e in ev), max(e["d"] for e in ev)], "base_ok": round(float(y.mean()), 3),
           "v1": evaluate(ev, BASE), "v2": evaluate(ev, BASE + EXTRA), "single_extra": single}
    res["model"] = fit_final(ev, BASE + EXTRA)
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=2500)
    ap.add_argument("--period", default="10y")
    a = ap.parse_args(argv)
    res = study(a.n, a.period)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("===BEGIN===")
    print(json.dumps({k: v for k, v in res.items() if k != "model"}, ensure_ascii=False, separators=(",", ":")))
    print("===MODEL===")
    print(json.dumps(res["model"], separators=(",", ":")))
    print("===END===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
