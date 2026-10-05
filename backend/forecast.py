"""Prognose: Wohin bewegt sich die Zahl der erfüllten Setup-Kriterien in den NÄCHSTEN 5 Handelstagen?

Merkmale aus dem aktuellen Scan-Ergebnis (Zeitfenster, die bald ablaufen, Signale kurz vor dem Eintreten,
RSI-/MACD-Dynamik, Abstand zur EMA 20, Verlauf der letzten 5 Tage) → lineares Modell (Ridge-Regression) auf die
Veränderung der erfüllten Kriterien in 5 Tagen. Gewichte und Schwellen werden mit echten Kursdaten geschätzt:

    python -m backend.forecast --fit [--n 250]      # lädt Kurse, rechnet Backtest, schreibt data/forecast_model.json

Das Modell wird an einer Hälfte der Aktien geschätzt und an der anderen geprüft (Trefferquote in der Datei).
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
from .indicators import rsi as rsi_ind

MODEL_PATH = ROOT / "data" / "forecast_model.json"
HORIZON = 5
UNI = ("cap", "liquidity", "price", "history")
CRIT = ("drawdown", "no_crash", "structure", "flattening", "zone", "rsi_div", "rsi_range", "macd_below0", "macd_turn", "mbi", "crv")

# Merkmal → Begründung für die App (positiv = spricht für mehr erfüllte Kriterien)
LABELS = {
    "mbi_exp": "grünes MBI-X läuft bald aus dem 15-Tage-Fenster",
    "cross_exp": "MACD-Kreuz läuft bald aus dem 7-Tage-Fenster",
    "div_exp": "RSI-Divergenz läuft bald aus dem 10-Tage-Fenster",
    "macd_eta": "MACD-Kreuz in wenigen Tagen erwartet",
    "flat_eta": "Abflachung bald erreicht, wenn der Kurs seitwärts läuft",
    "rsi_hi": "RSI nahe der Obergrenze 48",
    "rsi_lo": "RSI unter 28, dreht aber nach oben",
    "rsi_mom": "RSI-Dynamik",
    "near_e20": "Kurs nahe an der EMA 20 – Ausbruch würde die Struktur beenden",
    "mbi_pend": "grünes MBI-X da – Bestätigung durch nachlassenden Verkaufsdruck oft kurz bevor",
    "crv_edge": "CRV nur knapp über 2",
    "crv_near": "CRV knapp unter 2",
    "d5": ("zuletzt Kriterien verloren – das gleicht sich oft wieder aus", "zuletzt viele Kriterien dazugewonnen – oft folgt eine Gegenbewegung"),
    "met": ("erst wenige Kriterien erfüllt – Luft nach oben", "schon viele Kriterien erfüllt – oft fällt eines wieder weg"),
    "macd_mom": "MACD-Histogramm-Dynamik",
}


def met_of(res) -> int:
    return sum(c.ok for c in res.criteria if c.key not in UNI)


def features(res, rsi_prev: float | None, met_hist: list | None) -> dict:
    """Merkmale aus einem evaluate()-Ergebnis. rsi_prev = RSI vor 3 Tagen, met_hist = erfüllte Kriterien der Vortage."""
    f = res.flags
    ok = {c.key: bool(c.ok) for c in res.criteria}
    met = met_of(res)
    atr = f.get("atr") or 0
    rsi = f.get("rsi") or 50
    e20 = f.get("ema20")
    crv = res.plan.get("crv") if res.plan else None
    h, slope = f.get("macd_hist"), f.get("macd_slope")
    eta = math.ceil(-h / slope) if h is not None and slope and h < 0 and slope > 0 else None
    d5 = 0
    if met_hist and len(met_hist) >= 6 and met_hist[-6] is not None:
        d5 = met - met_hist[-6]
    dr = (rsi - rsi_prev) if rsi_prev is not None else 0
    x = {
        "met": (met - 6) / 3,
        "d5": max(-3, min(3, d5)) / 3,
        "mbi_exp": float(ok.get("mbi", False) and (f.get("mbi_x_age") or 0) >= 11),
        "cross_exp": float(ok.get("macd_turn", False) and bool(f.get("macd_cross_done")) and (f.get("macd_cross_age") or 0) >= 3),
        "div_exp": float(ok.get("rsi_div", False) and (f.get("div_t2_age") or 0) >= 6),
        "macd_eta": float(not ok.get("macd_turn", True) and eta is not None and eta <= HORIZON),
        "flat_eta": float(not ok.get("flattening", True) and (f.get("flat_eta") or 99) <= HORIZON),
        "rsi_hi": float(ok.get("rsi_range", False) and rsi >= 44),
        "rsi_lo": float(rsi < 28 and dr > 0),
        "rsi_mom": max(-2, min(2, dr / 10)),
        "near_e20": float(ok.get("structure", False) and e20 is not None and atr > 0 and (e20 - res.close) / atr < 0.6),
        "mbi_pend": float(not ok.get("mbi", True) and f.get("mbi_x_age") is not None and f["mbi_x_age"] <= 10
                          and f.get("mbi_above_ref", False) and not f.get("mbi_new_peak", False)),
        "crv_edge": float(ok.get("crv", False) and crv is not None and crv < 2.4),
        "crv_near": float(not ok.get("crv", True) and crv is not None and 1.6 <= crv < 2),
        "macd_mom": max(-2, min(2, (slope or 0) / atr * 10)) if atr else 0,
    }
    for k in CRIT:
        x["ok_" + k] = float(ok.get(k, False))
    return x


def _vec(x: dict, names: list) -> np.ndarray:
    return np.array([1.0] + [x.get(n, 0.0) for n in names])


def load_model() -> dict | None:
    try:
        return json.loads(MODEL_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def predict(x: dict, model: dict | None) -> dict:
    """→ {dir: up|down|flat, d: erwartete Veränderung, why: [[±1, Text], …]}"""
    if not model:
        return {"dir": "flat", "d": 0.0, "why": []}
    names, w = model["names"], np.array(model["w"])
    contrib = w * _vec(x, names)
    d = float(contrib.sum())
    lo, hi = model["thr"]
    direction = "up" if d >= hi else "down" if d <= lo else "flat"
    parts = sorted(((float(c), n) for c, n in zip(contrib[1:], names) if n in LABELS and abs(c) >= 0.15),
                   key=lambda t: -abs(t[0]))
    lab = lambda n, c: LABELS[n] if isinstance(LABELS[n], str) else LABELS[n][0 if c > 0 else 1]
    why = [[1 if c > 0 else -1, lab(n, c)] for c, n in parts[:3]]
    return {"dir": direction, "d": round(d, 2), "why": why}


# ---------------- Schätzung mit echten Kursdaten ----------------
def _samples(df: pd.DataFrame, step: int = 2, start: int = 260):
    from .scanner import evaluate

    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    n = len(df)
    if n < start + 30:
        return []
    r = rsi_ind(df["Close"], CONFIG.rsi.length).to_numpy(float)
    met, res_at = {}, {}
    for i in range(start - 5, n):          # erfüllte Kriterien an jedem Tag
        try:
            res = evaluate(df.iloc[: i + 1])
        except Exception:
            continue
        met[i] = met_of(res)
        res_at[i] = res
    out = []
    for i in range(start, n - HORIZON, step):
        if i not in res_at or i + HORIZON not in met:
            continue
        hist = [met.get(j) for j in range(i - 5, i + 1)]
        x = features(res_at[i], r[i - 3] if i >= 3 else None, hist)
        out.append((x, met[i + HORIZON] - met[i], hist[-1]))
    return out


def fit(n: int = 250, seed: int = 7, budget_s: float = 2400) -> dict:
    from .data_provider import YFinanceProvider
    from .universe import load as load_universe

    uni = load_universe()
    tickers = list(uni["ticker"])
    random.Random(seed).shuffle(tickers)
    tickers = tickers[:n]
    data = YFinanceProvider().history(tickers, CONFIG.history.period)
    print(f"Kurse: {len(data)} von {len(tickers)}")
    rows, t0 = [], time.time()
    for k, (t, df) in enumerate(data.items()):
        if time.time() - t0 > budget_s:
            print(f"Zeitbudget erreicht nach {k} Aktien")
            break
        for x, y, m in _samples(df):
            rows.append((t, x, y, m))
        if k % 25 == 0:
            print(f"  {k} Aktien, {len(rows)} Fälle, {time.time() - t0:.0f} s")
    names = sorted(rows[0][1].keys())
    ticks = sorted({r[0] for r in rows})
    test_t = set(ticks[1::2])
    tr = [r for r in rows if r[0] not in test_t]
    te = [r for r in rows if r[0] in test_t]
    X = np.array([_vec(r[1], names) for r in tr])
    y = np.array([r[2] for r in tr], float)
    lam = 1.0
    w = np.linalg.solve(X.T @ X + lam * np.eye(X.shape[1]), X.T @ y)

    def cls(v):
        return np.where(v >= 1, 1, np.where(v <= -1, -1, 0))

    def score(pred_d, ys, lo, hi):
        p = np.where(pred_d >= hi, 1, np.where(pred_d <= lo, -1, 0))
        a = cls(ys)
        acc = float((p == a).mean())
        dirs = p != 0
        hit = float((p[dirs] == a[dirs]).mean()) if dirs.any() else 0.0
        right_way = float((np.sign(ys[dirs]) == p[dirs]).mean()) if dirs.any() else 0.0
        return acc, hit, right_way, float(dirs.mean())

    pd_tr = X @ w
    best = None
    for hi in np.arange(0.3, 1.6, 0.05):
        for lo in np.arange(-1.6, -0.25, 0.05):
            acc, hit, rw, cov = score(pd_tr, y, lo, hi)
            key = acc + 0.15 * min(cov, 0.5)        # Genauigkeit, aber nicht nur „seitwärts“ vorhersagen
            if best is None or key > best[0]:
                best = (key, round(float(lo), 2), round(float(hi), 2))
    _, lo, hi = best
    Xt = np.array([_vec(r[1], names) for r in te])
    yt = np.array([r[2] for r in te], float)
    pdt = Xt @ w
    acc, hit, rw, cov = score(pdt, yt, lo, hi)
    # Vergleich: „Trend der letzten 5 Tage setzt sich fort“ und „immer seitwärts“
    d5t = np.array([r[1]["d5"] * 3 for r in te])
    acc_pers = float((np.where(d5t >= 2, 1, np.where(d5t <= -2, -1, 0)) == cls(yt)).mean())
    acc_flat = float((cls(yt) == 0).mean())
    near = np.array([r[3] >= 7 for r in te])
    acc_near = score(pdt[near], yt[near], lo, hi)
    model = {"names": names, "w": [round(float(v), 4) for v in w], "thr": [lo, hi], "horizon": HORIZON,
             "fitted": time.strftime("%Y-%m-%d"), "n_train": len(tr), "n_test": len(te),
             "test": {"acc": round(acc, 3), "dir_hit": round(hit, 3), "right_way": round(rw, 3), "coverage": round(cov, 3),
                      "acc_persistence": round(acc_pers, 3), "acc_always_flat": round(acc_flat, 3),
                      "near_acc": round(acc_near[0], 3), "near_dir_hit": round(acc_near[1], 3), "near_right_way": round(acc_near[2], 3),
                      "n_near": int(near.sum())}}
    return model


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fit", action="store_true")
    ap.add_argument("--n", type=int, default=250)
    a = ap.parse_args(argv)
    if a.fit:
        m = fit(a.n)
        MODEL_PATH.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
        print("TEST " + json.dumps(m["test"]))
        print("MODEL " + json.dumps(m, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
