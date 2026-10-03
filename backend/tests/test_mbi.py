import numpy as np
import pandas as pd
import pytest

from backend.mbi import hma, momentum_bias_index, wma


def test_wma_weights_newest_most():
    s = pd.Series([1.0, 2.0, 3.0])
    assert wma(s, 3).iloc[-1] == pytest.approx((1 * 1 + 2 * 2 + 3 * 3) / 6)


def test_hma_matches_definition():
    s = pd.Series(np.arange(1, 31, dtype=float) ** 1.5)
    expected = wma(2 * wma(s, 5) - wma(s, 10), 3)
    pd.testing.assert_series_equal(hma(s, 10), expected)
    # Auf einer Geraden hinkt der HMA(10) nur 1/3 Balken hinterher (WMA(10) hinkt 3 Balken)
    line = pd.Series(np.arange(50, dtype=float))
    assert hma(line, 10).iloc[-1] == pytest.approx(49 - 1 / 3)


def _ohlc(close):
    close = pd.Series(close)
    return close, close + 0.5, close - 0.5


def test_mbi_green_x_after_strong_selloff():
    rng = np.random.default_rng(5)
    flat = 100 + rng.normal(0, 0.3, 120)
    crash = np.linspace(100, 70, 15)       # Tief bei Index 134
    rebound = np.linspace(70, 78, 25)
    close, high, low = _ohlc(np.concatenate([flat, crash, rebound]))
    mbi = momentum_bias_index(close, high, low)
    xs = np.flatnonzero(mbi["green_x"])
    assert any(134 <= x <= 145 for x in xs)
    assert not mbi["green_x"].iloc[:134].any()
    assert not mbi["red_x"].iloc[120:].any()
    # Werte wie im TradingView-Chart: Momentum in % der Tagesspanne → Hunderter/Tausender
    assert mbi["lower_bias"].max() > 1000


def test_mbi_no_signal_without_red_dominance():
    # Aufwärtstrend: rote Balken sind 0 → nie ein grünes X, aber rote X möglich
    rng = np.random.default_rng(2)
    close, high, low = _ohlc(np.linspace(50, 100, 200) + rng.normal(0, 0.5, 200))
    mbi = momentum_bias_index(close, high, low)
    assert not mbi["green_x"].iloc[40:].any()
