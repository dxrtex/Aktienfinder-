import numpy as np

from backend.hints import hint
from backend.scanner import evaluate
from backend.tests.test_scanner import _df


def test_hint_for_many_random_series():
    rng = np.random.default_rng(7)
    seen = set()
    for k in range(200):
        c = 50 * np.exp(np.cumsum(rng.normal(0, 0.025, 420)))
        res = evaluate(_df(c, k), {"currency": "USD", "market_cap": 5e9}, ticker=f"T{k}")
        h = hint(res)
        assert h["tone"] in {"green", "yellow", "orange", "red", "gray"}
        assert h["title"] and h["text"] and "None" not in h["text"]
        assert (h["tone"] == "green") == res.passed
        if h["days"] is not None:
            assert 0 <= h["days"] <= 15 and h["days_label"]
        seen.add(h["title"].split(" ·")[0].split(" –")[0])
    assert len(seen) >= 4


def test_hint_uptrend_and_crash():
    up = _df(np.linspace(50, 120, 420))
    assert hint(evaluate(up, {"currency": "USD", "market_cap": 5e9}))["tone"] == "gray"
    c = np.r_[np.linspace(50, 100, 380), np.full(35, 100.0), [60, 59, 58, 58, 57]]
    h = hint(evaluate(_df(c), {"currency": "USD", "market_cap": 5e9}))
    assert h["tone"] == "red" and h["days"] >= 1
