import numpy as np
import pandas as pd

from aktienfinder.config import Config
import pytest

from aktienfinder.signals import evaluate, fib_retracement, find_cluster, find_divergences, macd_condition

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


def test_divergence_compares_with_older_lows_not_only_previous():
    # Drei Tiefs: das mittlere ist flach (kein Vergleichspartner), Divergenz zwischen 1. und 3.
    df, osc = _two_lows(price_lows=[50, 52], osc_lows=[25, 40])
    shape = [4, 3, 2, 1, 0, -1, 0, 1, 2, 3]
    extra_p = [44 + 1 + s for s in shape] + [49] * 3
    extra_o = [30 + 1 + s for s in shape] + [35] * 3
    lows = list(df["Low"]) + extra_p
    df3 = _frame(lows)
    osc3 = pd.Series(list(osc) + extra_o, index=df3.index, dtype=float)
    divs = find_divergences(df3, osc3, CFG)
    latest = [d for d in divs if d.pivot_date == str(df3.index[28].date())]
    kinds = {d.kind: d for d in latest}
    # gegen Tief 2 (52/40): Kurs tiefer, RSI tiefer → nichts; gegen Tief 1 (50/25): klassisch
    assert "klassisch" in kinds and kinds["klassisch"].prev_pivot_date == str(df3.index[5].date())


def test_find_cluster_requires_signals_close_together():
    cfg = Config(cluster_span=15, max_signal_age=30)
    assert find_cluster([5], [12], [18], cfg).span == 13
    assert find_cluster([2], [10], [25], cfg) is None          # 23 Tage auseinander
    assert find_cluster([35], [30], [28], cfg) is None         # zu alt
    c = find_cluster([3, 20], [8, 22], [5, 25], cfg)
    assert (c.divergence_age, c.macd_age, c.mbi_age) == (3, 8, 5)   # jüngstes Bündel


def test_fib_retracement():
    # Schwung von 50 auf 100, danach Rücksetzer bis 65 → (100-65)/(100-50) = 0.7
    up = list(np.linspace(50, 100, 40))
    down = list(np.linspace(99, 65, 20)) + [70, 72, 74]
    closes = np.array(up + down)
    idx = pd.bdate_range("2026-01-01", periods=len(closes))
    df = pd.DataFrame({"High": closes, "Low": closes, "Close": closes}, index=idx)
    assert fib_retracement(df) == pytest.approx(0.7)


def test_reversal_candle_at_fib_level():
    from aktienfinder.signals import reversal_candle
    # Schwung 50 → 100, Rücksetzer bis 61,8 (= 0,764 Retracement ≈ 0,79-Linie bei 60,5)
    up = np.linspace(50, 100, 40)
    down = np.linspace(99, 62, 20)
    closes = np.concatenate([up, down])
    idx = pd.bdate_range("2026-01-01", periods=len(closes) + 1)
    df = pd.DataFrame({"Open": np.append(closes, 61.0), "High": np.append(closes + 0.5, 66.0),
                       "Low": np.append(closes - 0.5, 60.6), "Close": np.append(closes, 65.5),
                       "Volume": 1e6}, index=idx)
    vol_ratio = pd.Series(1.0, index=idx)
    vol_ratio.iloc[-1] = 2.5
    assert reversal_candle(df, vol_ratio) == 0
    vol_ratio.iloc[-1] = 1.0                       # ohne Volumen keine Umkehrkerze
    assert reversal_candle(df, vol_ratio) is None


def test_macd_line_sideways_is_enough():
    hist = pd.Series([-1, -4, -8, -6, -4, -3, -2])
    falling = pd.Series([0, -1, -2, -3, -4, -5, -6.0])
    flat = pd.Series([0, -1, -2, -3, -3.1, -3.0, -3.0])
    cfg = Config(macd_rising_bars=3, macd_near_zero=0.5, macd_line_lookback=3)
    assert not macd_condition(hist, cfg, falling).iloc[-1]
    assert macd_condition(hist, cfg, flat).iloc[-1]
