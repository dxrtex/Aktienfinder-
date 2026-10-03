"""Diagnose-Bericht nach einem Scan (für das Workflow-Log).

Aufruf:
    python -m aktienfinder.report --universe universe.csv --results site/data/results.json \
        --refs QBTS,RKLB,IFX.DE,UBER,TUI1.DE
"""

import argparse
import collections
import json

import numpy as np
import pandas as pd


def _hist(values, bins) -> str:
    counts = collections.Counter(np.digitize(values, bins))
    labels = [f"<{bins[0]}"] + [f"{a}-{b}" for a, b in zip(bins, bins[1:])] + [f">={bins[-1]}"]
    return ", ".join(f"{labels[i]}: {counts.get(i, 0)}" for i in range(len(labels)))


def _min_rsi(row: dict) -> float:
    """Tiefster RSI-Wert der Divergenzen, die zum Signal-Bündel gehören."""
    age = row["cluster"]["divergence_age"]
    divs = [d for d in row["divergences"] if d["age"] == age] or row["divergences"]
    return min(min(d["rsi_low"], d["prev_rsi_low"]) for d in divs)


def report(universe: pd.DataFrame, data: dict, refs: list[str]) -> str:
    out = []
    out.append("== Universum ==")
    out += data.get("universe_log", [])
    out.append("Je Region: " + str(dict(collections.Counter(universe["region"]))))
    out.append(f"Stats: {data['stats']}")

    res = [r for r in data["results"] if r["passed"]]
    liquid = data["stats"].get("liquid", 0) or 1
    out.append(f"\n== Treffer: {len(res)} ({100 * len(res) / liquid:.0f} % der liquiden) ==")
    out.append("Je Region: " + str(dict(collections.Counter(r["region"] for r in res))))
    if res:
        out.append("Score: " + _hist([r["score"] for r in res], [40, 50, 60, 70, 80]))
        out.append("Bündel-Spanne (T.): " + _hist([r["cluster"]["span"] for r in res], [5, 10, 15]))
        newest = [min(r["cluster"]["divergence_age"], r["cluster"]["macd_age"], r["cluster"]["mbi_age"]) for r in res]
        oldest = [max(r["cluster"]["divergence_age"], r["cluster"]["macd_age"], r["cluster"]["mbi_age"]) for r in res]
        out.append("Jüngstes Signal (T.): " + _hist(newest, [5, 10, 20, 30]))
        out.append("Ältestes Signal (T.): " + _hist(oldest, [10, 20, 30, 40]))
        rsis = [_min_rsi(r) for r in res]
        out.append("Tiefster RSI der Divergenz: " + _hist(rsis, [30, 35, 40, 45, 50]))
        out.append("Abstand zum Hoch (%): " + _hist([r["drawdown_pct"] for r in res], [10, 15, 20, 30]))
        kinds = collections.Counter("+".join(sorted({d["kind"] for d in r["divergences"]})) for r in res)
        out.append("Divergenzarten: " + str(dict(kinds)))
        out.append("Treffer, wenn zusätzlich verlangt würde …")
        for lim in (30, 35, 40):
            out.append(f"  RSI-Tief <= {lim}: {sum(x <= lim for x in rsis)}")
        for lim in (10, 15, 20):
            out.append(f"  Abstand zum Hoch >= {lim} %: {sum(r['drawdown_pct'] >= lim for r in res)}")
        out.append(f"  RSI-Tief <= 35 und Abstand >= 15 %: "
                   f"{sum(x <= 35 and r['drawdown_pct'] >= 15 for x, r in zip(rsis, res))}")

    out.append("\n== Referenz-Aktien ==")
    by_ticker = {r["ticker"]: r for r in data["results"]}
    uni = universe.set_index("ticker")
    for t in refs:
        if t not in uni.index:
            out.append(f"{t}: NICHT im Universum")
            continue
        cap = uni.loc[t, "market_cap_usd"] if "market_cap_usd" in uni.columns else None
        r = by_ticker.get(t)
        if r is None:
            out.append(f"{t}: im Universum (Börsenwert {cap}), aber kein Treffer")
        else:
            out.append(f"{t}: Score {r['score']}, Bündel {r['cluster']}, RSI-Tief {_min_rsi(r)}, "
                       f"Abstand {r['drawdown_pct']} %")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--universe", required=True)
    p.add_argument("--results", required=True)
    p.add_argument("--refs", default="")
    args = p.parse_args(argv)
    universe = pd.read_csv(args.universe, dtype={"ticker": str})
    with open(args.results, encoding="utf-8") as f:
        data = json.load(f)
    print(report(universe, data, [t for t in args.refs.split(",") if t]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
