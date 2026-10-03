import itertools

import numpy as np
import pandas as pd

from aktienfinder import backtest
from aktienfinder.config import Config


def test_cluster_completions_matches_brute_force():
    rng = np.random.default_rng(3)
    cfg = Config(cluster_span=15)
    for _ in range(50):
        d = sorted(rng.choice(300, 4, replace=False))
        m = sorted(rng.choice(300, 12, replace=False))
        x = sorted(rng.choice(300, 4, replace=False))
        expected = set()
        for a, b in itertools.product(d, x):
            ok = [max(a, b, c) for c in m if max(a, b, c) - min(a, b, c) <= 15]
            if ok:
                expected.add(min(ok))
        assert backtest.cluster_completions(d, m, x, cfg) == sorted(expected)


def test_forward_returns_and_target_stop():
    idx = pd.bdate_range("2026-01-01", periods=60)
    close = np.full(60, 100.0)
    close[5:] = 112.0                     # +12 % ab Tag 5
    df = pd.DataFrame({"Open": 100.0, "High": close, "Low": close * 0.99, "Close": close}, index=idx)
    f = backtest._forward(df, 0)
    assert abs(f["ret_10"] - 0.12) < 1e-9 and f["target_first"] == 1.0
    df2 = df.assign(Low=np.where(np.arange(60) == 2, 90.0, 99.0))   # −10 % an Tag 2 → Stopp zuerst
    assert backtest._forward(df2, 0)["target_first"] == -1.0


def test_stock_events_and_summary_run():
    rng = np.random.default_rng(1)
    n = 900
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, n)))
    idx = pd.bdate_range("2023-01-02", periods=n)
    df = pd.DataFrame({"Open": c, "High": c * 1.01, "Low": c * 0.99, "Close": c, "Volume": 1e6}, index=idx)
    loose = Config(require_fib_zone=False, min_drawdown=0.0)   # Zufallskurs: Pflichtfilter lockern
    ev = backtest.stock_events("X", df, loose)
    assert ev, "auf 900 Tagen Zufallskurs sollte es Signale geben"
    assert all(e["score"] > 0 for e in ev)
    text = backtest.summarize(pd.DataFrame(ev), pd.DataFrame(backtest.baseline_returns(df)))
    assert "Fib-Zone" in text
    assert "Zufallseinstieg" in text and "Score" in text
