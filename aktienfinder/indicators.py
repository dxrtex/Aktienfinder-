"""Indikatoren, so nah wie möglich an der TradingView/Pine-Script-Berechnung."""

import numpy as np
import pandas as pd


def rma(src: pd.Series, length: int) -> pd.Series:
    """Wilder-Glättung wie Pine `ta.rma`: Start mit SMA, danach alpha = 1/length."""
    values = src.to_numpy(dtype=float)
    out = np.full(len(values), np.nan)
    alpha = 1.0 / length
    prev = np.nan
    start = None
    for i, v in enumerate(values):
        if np.isnan(v):
            continue
        if start is None:
            start = i
        if np.isnan(prev):
            if i - start + 1 >= length:
                window = values[i - length + 1 : i + 1]
                if not np.isnan(window).any():
                    prev = window.mean()
                    out[i] = prev
            continue
        prev = alpha * v + (1 - alpha) * prev
        out[i] = prev
    return pd.Series(out, index=src.index)


def ema(src: pd.Series, length: int) -> pd.Series:
    """Exponentieller Durchschnitt wie Pine `ta.ema` (Start mit dem ersten Wert)."""
    return src.ewm(span=length, adjust=False).mean()


def rsi(close: pd.Series, length: int = 14) -> pd.Series:
    """RSI wie Pine `ta.rsi`."""
    change = close.diff()
    up = rma(change.clip(lower=0), length)
    down = rma((-change).clip(lower=0), length)
    rs = up / down
    out = 100 - 100 / (1 + rs)
    out = out.where(down != 0, 100.0)
    out = out.where(up != 0, 0.0).where(~(up.isna() | down.isna()))
    return out


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """MACD-Linie, Signallinie und Histogramm wie Pine `ta.macd`."""
    line = ema(close, fast) - ema(close, slow)
    sig = ema(line, signal)
    return pd.DataFrame({"macd": line, "signal": sig, "hist": line - sig})


def pivot_low(src: pd.Series, left: int, right: int) -> pd.Series:
    """Pine `ta.pivotlow`: True am Bestätigungsbalken (Tief liegt `right` Balken zurück).

    Das Tief muss tiefer sein als die `left` Balken davor und nicht höher als die
    `right` Balken danach.
    """
    values = src.to_numpy(dtype=float)
    n = len(values)
    found = np.zeros(n, dtype=bool)
    for i in range(left + right, n):
        c = i - right
        center = values[c]
        if np.isnan(center):
            continue
        left_win = values[c - left : c]
        right_win = values[c + 1 : i + 1]
        if np.isnan(left_win).any() or np.isnan(right_win).any():
            continue
        if center < left_win.min() and center <= right_win.min():
            found[i] = True
    return pd.Series(found, index=src.index)


def momentum_bias_index(
    close: pd.Series,
    momentum_length: int = 10,
    bias_length: int = 5,
    smooth_length: int = 10,
    impulse_length: int = 30,
    std_mult: float = 3.0,
) -> pd.DataFrame:
    """Momentum Bias Index nach AlgoAlpha – VORLÄUFIGE Rekonstruktion.

    Das Original-Pine-Skript war aus dieser Umgebung nicht abrufbar. Nachgebaut
    ist das dokumentierte Prinzip: das normierte Momentum wird in einen positiven
    und einen negativen Anteil zerlegt, beide werden über `bias_length`
    aufsummiert und geglättet. Das grüne X (Take-Profit für Shorts bzw. "der
    Verkaufsdruck lässt nach") erscheint, wenn der negative Bias dominiert und
    von seinem Hochpunkt abdreht.

    Sobald der Original-Code vorliegt, wird diese Funktion 1:1 ersetzt.
    """
    momentum = close.diff(momentum_length)
    std = momentum.rolling(momentum_length).std(ddof=0)
    norm = (momentum / std).where(std != 0, 0.0)

    positive = norm.clip(lower=0).rolling(bias_length).sum() / bias_length
    negative = (-norm).clip(lower=0).rolling(bias_length).sum() / bias_length
    upper = ema(positive, smooth_length)
    lower = ema(negative, smooth_length)

    dominant = pd.concat([upper, lower], axis=1).max(axis=1)
    boundary = ema(dominant, impulse_length) + dominant.rolling(impulse_length).std(ddof=0) * std_mult

    lower_turns_down = (lower < lower.shift(1)) & (lower.shift(1) >= lower.shift(2))
    upper_turns_down = (upper < upper.shift(1)) & (upper.shift(1) >= upper.shift(2))
    green_x = lower_turns_down & (lower > upper)
    red_x = upper_turns_down & (upper > lower)

    return pd.DataFrame(
        {
            "upper_bias": upper,
            "lower_bias": lower,
            "impulse_boundary": boundary,
            "green_x": green_x.fillna(False),
            "red_x": red_x.fillna(False),
        }
    )
