# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
#
# Python-Portierung des TradingView-Indikators "Momentum Bias Index [AlgoAlpha]",
# Original © AlgoAlpha (Pine Script, MPL 2.0).
"""Momentum Bias Index [AlgoAlpha] in Python."""

import numpy as np
import pandas as pd

from .indicators import ema


def wma(src: pd.Series, length: int) -> pd.Series:
    """Gewichteter Durchschnitt wie Pine `ta.wma` (jüngster Wert hat Gewicht `length`)."""
    weights = np.arange(1, length + 1, dtype=float)
    return src.rolling(length).apply(lambda x: np.dot(x, weights) / weights.sum(), raw=True)


def hma(src: pd.Series, length: int) -> pd.Series:
    """Hull Moving Average wie Pine `ta.hma`."""
    half = wma(src, length // 2)
    full = wma(src, length)
    return wma(2 * half - full, int(np.floor(np.sqrt(length))))


def momentum_bias_index(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    momentum_length: int = 10,
    bias_length: int = 5,
    smooth_length: int = 10,
    impulse_length: int = 30,
    std_mult: float = 3.0,
    smooth: bool = True,
) -> pd.DataFrame:
    """Momentum Bias Index [AlgoAlpha] – 1:1 nach dem Original-Pine-Script (MPL 2.0).

    - upper_bias: grüne Balken (Kaufdruck), lower_bias: rote Balken (Verkaufsdruck)
    - impulse_boundary: gepunktete Linie
    - green_x: "Bullish TP Signal" – roter Balken wird nach einer Spitze kleiner,
      liegt über der Linie und über dem grünen Balken
    - red_x: "Bearish TP Signal" – dasselbe für grüne Balken
    """
    momentum = close - close.shift(momentum_length)
    scaled = momentum / ema(high - low, momentum_length) * 100
    up = scaled.clip(lower=0)
    down = scaled.clip(upper=0)
    up_sum = up.rolling(bias_length).sum()
    down_sum = down.rolling(bias_length).sum()
    if smooth:
        upper = hma(up_sum, smooth_length).clip(lower=0)
        lower = hma(-down_sum, smooth_length).clip(lower=0)
    else:
        upper = up_sum
        lower = -down_sum
    average = (lower + upper) / 2
    boundary = ema(average, impulse_length) + average.rolling(impulse_length).std(ddof=0) * std_mult

    def crossunder_self(x: pd.Series) -> pd.Series:
        return (x < x.shift(1)) & (x.shift(1) >= x.shift(2))

    green_x = crossunder_self(lower) & (lower > boundary) & (lower > upper)
    red_x = crossunder_self(upper) & (upper > boundary) & (upper > lower)

    return pd.DataFrame(
        {
            "upper_bias": upper,
            "lower_bias": lower,
            "impulse_boundary": boundary,
            "green_x": green_x.fillna(False),
            "red_x": red_x.fillna(False),
        }
    )
