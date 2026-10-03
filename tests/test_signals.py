import numpy as np
import pandas as pd

from aktienfinder.config import Config
from aktienfinder.signals import evaluate, find_divergences, macd_condition

CFG = Config(pivot_left=3, pivot_right=2, divergence_min_bars=5, divergence_max_bars=60)


def _frame(lows):
    idx = pd.bdate_range("2026-01-01", periods=len(lows))
    lows = np.asarray(lows, dtype=float)
    return pd.DataFrame({"Open": lows + 1, "High": lows + 2, "Low": lows, "Close": lows + 1,
                         "Volume": 1e6}, index=idx)


def _two_lows(price_lows, osc_lows):
    """Zwei V-förmige Tiefs bei Index 5 und 15 in Kurs und Oszillator."""
    shape = [4, 3, 2, 1, 0, -1, 0, 1, 2, 3]  # Tief an Position 5
    price, osc = [], []
    for p, o in zip(price_lows, osc_lows):
        price += [p + 1 + s for s in shape]
        osc += [o + 1 + s for s in shape]
    price += [price_lows[-1] + 5] * 3
    osc += [osc_lows[-1] + 5] * 3
    return _frame(price), pd.Series(osc, index=_frame(price).index, dtype=float)


def test_classic_divergence():
    df, osc = _two_lows(price_lows=[50, 45], osc_lows=[25, 32])
    divs = find_divergences(df, osc, CFG)
    assert [d.kind for d in divs] == ["klassisch"]
    assert divs[0].bars_between == 10


def test_hidden_divergence():
    df, osc = _two_lows(price_lows=[45, 50], osc_lows=[32, 25])
    assert [d.kind for d in find_divergences(df, osc, CFG)] == ["versteckt"]


def test_no_divergence_when_both_lower():
    df, osc = _two_lows(price_lows=[50, 45], osc_lows=[32, 25])
    assert find_divergences(df, osc, CFG) == []


def test_macd_condition_requires_shrinking_red_bars_near_zero():
    hist = pd.Series([-1, -4, -8, -6, -4, -3, -2, -1, 0.5])
    cond = macd_condition(hist, Config(macd_rising_bars=3, macd_near_zero=0.5))
    # Index 5: -3 (≥ -4 = 50 % von -8), 3 Tage steigend → True; Index 8 ist grün → False
    assert list(cond) == [False, False, False, False, False, True, True, True, False]


def test_evaluate_runs_on_random_walk():
    rng = np.random.default_rng(1)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, 500)))
    idx = pd.bdate_range("2024-01-01", periods=500)
    df = pd.DataFrame({"Open": close, "High": close * 1.01, "Low": close * 0.99,
                       "Close": close, "Volume": 2e6}, index=idx)
    res = evaluate(df)
    assert 0 <= res.rsi <= 100
    assert res.score == 0 or res.passed
    assert isinstance(res.to_dict(), dict)
