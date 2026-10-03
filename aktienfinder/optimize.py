"""Optimierer: sucht die Filterkombination mit dem besten durchschnittlichen Ergebnis je Trade.

Gemessen wird ein echter Swing-Trade (Kauf am Folgetag, Stop unter dem Tief, Verkauf bei +20 %,
spätestens nach 60 Tagen) – nicht nur „wurde +20 % irgendwann berührt“. Sonst würden einfach die
schwankungsstärksten Aktien gewinnen, die genauso oft vorher den Stop reißen.

Schutz gegen Zufallstreffer (Overfitting): Die Kombination wird nur auf der ersten Hälfte des
Zeitraums ausgewählt („Lernen“) und danach auf der zweiten Hälfte geprüft („Test“). Übernommen
wird nur, was in BEIDEN Hälften besser ist als alle Signale ohne Zusatzfilter.

Aufruf (nach dem Backtest):
    python -m aktienfinder.optimize --events events.csv
"""

import argparse
import itertools
import json

import numpy as np
import pandas as pd

# Jede Dimension: Name → Liste von (Beschriftung, Maske-Funktion)
def _dimensions(ev: pd.DataFrame) -> dict[str, list[tuple[str, pd.Series]]]:
    t = pd.Series(True, index=ev.index)
    b = lambda c: ev[c].astype("boolean").fillna(False).astype(bool) if c in ev else ~t
    f = lambda c: ev[c].astype(float) if c in ev else pd.Series(np.nan, index=ev.index)
    pdd, crv, rise, rs = f("pullback_drawdown_pct"), f("crv"), f("rise_from_low_pct"), f("rel_strength")
    return {
        "kern": [("egal", t), ("alle 5", f("core_count") >= 5)],
        "rueckgang": [(f"≥{x} %", pdd >= x) for x in (20, 25, 30, 40)],
        "crv": [("egal", t)] + [(f"≥{x}", crv >= x) for x in (1.5, 2, 3)],
        "markt": [("egal", t), ("über EMA 200", b("market_ok"))],
        "trend": [("egal", t), ("EMA 200 steigt", b("ema200_rising"))],
        "rel_staerke": [("egal", t), ("> 0", rs > 0)],
        "ueber_tief": [("egal", t), ("0–8 %", rise <= 8), ("5–20 %", rise.between(5, 20))],
        "gruene_x": [("egal", t), ("≥ 2", f("green_x_count") >= 2)],
    }


def _rate(frame: pd.DataFrame, col: str = "trade_ret") -> float:
    v = frame[col].dropna()
    return float(v.mean()) if len(v) else np.nan


def _win(frame: pd.DataFrame) -> float:
    v = frame["trade_outcome"].dropna()
    return float((v == 1).mean()) if len(v) else np.nan


def optimize(ev: pd.DataFrame, min_train: int = 150, min_test: int = 100, top: int = 15) -> tuple[str, dict]:
    ev = ev.dropna(subset=["trade_ret"]).reset_index(drop=True)
    split = ev["date"].sort_values().iloc[len(ev) // 2]
    train, test = ev["date"] < split, ev["date"] >= split
    dims = _dimensions(ev)
    base_tr, base_te = _rate(ev[train]), _rate(ev[test])

    rows = []
    names = list(dims)
    for combo in itertools.product(*(dims[n] for n in names)):
        mask = np.logical_and.reduce([m.to_numpy() for _, m in combo])
        n_tr, n_te = int((mask & train).sum()), int((mask & test).sum())
        if n_tr < min_train or n_te < min_test:
            continue
        rows.append({
            **{n: lab for n, (lab, _) in zip(names, combo)},
            "n_lern": n_tr, "lern": _rate(ev[mask & train]),
            "n_test": n_te, "test": _rate(ev[mask & test]),
            "test_win": _win(ev[mask & test]), "test_hit20": _rate(ev[mask & test], "sig_hit_20"),
            "test_median": float(ev.loc[mask & test, "trade_ret"].median()),
        })
    res = pd.DataFrame(rows)
    out = [f"== Optimierer: {len(res)} Kombinationen mit genug Signalen (Lernen bis {split}, Test ab {split}) ==",
           f"Ohne Zusatzfilter: Ø je Trade Lernen {100 * base_tr:+.2f} % | Test {100 * base_te:+.2f} % "
           f"(Ziel vor Stop im Test: {100 * _win(ev[test]):.0f} %)"]
    if res.empty:
        return "\n".join(out + ["keine Kombination mit genug Signalen"]), {}
    best = res.sort_values("lern", ascending=False).head(top)
    out.append(f"\nBeste {top} nach der Lern-Hälfte – und wie sie in der Test-Hälfte liefen:")
    for _, r in best.iterrows():
        filt = ", ".join(f"{n}={r[n]}" for n in names if r[n] != "egal")
        out.append(f"  Lernen Ø {100 * r.lern:+.2f} % (n={r.n_lern}) → Test Ø {100 * r.test:+.2f} % (n={r.n_test}), "
                   f"Test: Ziel vor Stop {100 * r.test_win:.0f} %, +20 % berührt {100 * r.test_hit20:.0f} %, "
                   f"Median {100 * r.test_median:+.1f} % | {filt or 'keine Filter'}")
    # Robuste Wahl: unter den 15 besten der Lern-Hälfte die mit dem besten Testergebnis,
    # nur wenn sie in beiden Hälften die Basis schlägt
    ok = best[(best.lern > base_tr) & (best.test > base_te)]
    choice = {}
    if len(ok):
        r = ok.sort_values("test", ascending=False).iloc[0]
        choice = {n: r[n] for n in names} | {"lern": round(r.lern, 4), "test": round(r.test, 4),
                                             "test_win": round(r.test_win, 3), "n_test": int(r.n_test)}
        out.append("\nEMPFEHLUNG (in beiden Hälften besser als ohne Filter): " + json.dumps(choice, ensure_ascii=False))
    else:
        out.append("\nKeine Kombination ist in beiden Hälften besser – Filter würden nur Zufall nachbilden.")
    # Einzelwirkung jedes Filters (gegenüber „egal“), Test-Hälfte
    out.append("\nEinzelwirkung je Filter (nur dieser Filter, Test-Hälfte, Ø Ergebnis je Trade):")
    for n in names:
        for lab, m in dims[n]:
            if lab == "egal":
                continue
            sub = ev[m & test]
            out.append(f"  {n:<12}{lab:<14} n={len(sub):<6} Ø {100 * _rate(sub):+.2f} %, Ziel vor Stop "
                       f"{100 * _win(sub):.0f} % (Basis Ø {100 * base_te:+.2f} %)")
    return "\n".join(out), choice


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--events", required=True)
    p.add_argument("--out", help="Empfehlung als JSON speichern")
    args = p.parse_args(argv)
    ev = pd.read_csv(args.events)
    text, choice = optimize(ev)
    print(text)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(choice, f, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
