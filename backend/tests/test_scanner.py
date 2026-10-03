import numpy as np
import pandas as pd

from backend.scanner import de, evaluate


def _df(close, seed=0):
    rng = np.random.default_rng(seed)
    c = np.asarray(close, dtype=float)
    o = c * (1 + rng.normal(0, 0.003, len(c)))
    return pd.DataFrame({"Open": o, "High": np.maximum(o, c) * 1.01, "Low": np.minimum(o, c) * 0.99,
                         "Close": c, "Volume": 2e6}, index=pd.bdate_range("2025-01-01", periods=len(c)))


def test_evaluate_reports_every_criterion_and_scores_only_full_setups():
    rng = np.random.default_rng(1)
    for k in range(30):
        c = 50 * np.exp(np.cumsum(rng.normal(0, 0.02, 420)))
        res = evaluate(_df(c, k), {"currency": "USD", "market_cap": 5e9}, ticker=f"T{k}")
        keys = [x.key for x in res.criteria]
        for need in ("drawdown", "no_crash", "structure", "flattening", "zone", "rsi_div", "rsi_range",
                     "macd_below0", "macd_turn", "mbi", "crv"):
            assert need in keys
        assert (res.score > 0) == res.passed
        assert 0 <= res.score <= 100


def test_german_number_format():
    assert de(1234.5) == "1.234,50" and de(0.125, 3) == "0,125"
