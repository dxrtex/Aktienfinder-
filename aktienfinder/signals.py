"""Signal-Erkennung und Scoring für eine einzelne Aktie."""

from dataclasses import dataclass, asdict, field

import numpy as np
import pandas as pd

from .config import Config, DEFAULT
from .indicators import macd, momentum_bias_index, pivot_low, rsi


@dataclass
class Divergence:
    kind: str            # "klassisch" oder "versteckt"
    pivot_date: str      # Datum des zweiten (jüngeren) Tiefs
    confirmed_date: str  # Datum, an dem das Tief bestätigt war
    age: int             # Handelstage seit Bestätigung
    price_low: float
    prev_price_low: float
    rsi_low: float
    prev_rsi_low: float
    bars_between: int


@dataclass
class Result:
    passed: bool
    score: float
    close: float
    rsi: float
    drawdown_pct: float
    divergences: list = field(default_factory=list)
    macd_age: int | None = None
    macd_status: str = ""
    mbi_age: int | None = None
    volume_spike: bool = False
    volume_recovery: bool = False
    dollar_volume: float = 0.0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["divergences"] = [asdict(x) if not isinstance(x, dict) else x for x in self.divergences]
        return d


def find_divergences(df: pd.DataFrame, osc: pd.Series, cfg: Config = DEFAULT) -> list[Divergence]:
    """Bullische Divergenzen wie im TradingView-RSI (Pivot-Tiefs auf dem RSI).

    Klassisch: Kurs tieferes Tief, RSI höheres Tief.
    Versteckt: Kurs höheres Tief, RSI tieferes Tief.
    """
    found = pivot_low(osc, cfg.pivot_left, cfg.pivot_right).to_numpy()
    low = df["Low"].to_numpy(dtype=float)
    o = osc.to_numpy(dtype=float)
    idx = df.index
    n = len(df)
    r = cfg.pivot_right

    out = []
    prev = None
    for i in np.flatnonzero(found):
        if prev is not None:
            between = i - prev
            if cfg.divergence_min_bars <= between <= cfg.divergence_max_bars:
                c, p = i - r, prev - r
                kind = None
                if low[c] < low[p] and o[c] > o[p]:
                    kind = "klassisch"
                elif low[c] > low[p] and o[c] < o[p]:
                    kind = "versteckt"
                if kind:
                    out.append(
                        Divergence(
                            kind=kind,
                            pivot_date=str(idx[c].date()),
                            confirmed_date=str(idx[i].date()),
                            age=n - 1 - i,
                            price_low=round(low[c], 4),
                            prev_price_low=round(low[p], 4),
                            rsi_low=round(o[c], 2),
                            prev_rsi_low=round(o[p], 2),
                            bars_between=int(between),
                        )
                    )
        prev = i
    return out


def macd_condition(hist: pd.Series, cfg: Config = DEFAULT) -> pd.Series:
    """Rote Balken, die seit `macd_rising_bars` Tagen kleiner werden und nahe null sind."""
    rising = pd.Series(True, index=hist.index)
    for k in range(cfg.macd_rising_bars):
        rising &= hist.shift(k) > hist.shift(k + 1)
    trough = hist.rolling(cfg.macd_trough_lookback, min_periods=1).min()
    near_zero = hist >= trough * cfg.macd_near_zero
    return (hist < 0) & rising & near_zero & (trough < 0)


def _last_true_age(s: pd.Series, window: int) -> int | None:
    """Alter (in Handelstagen) des letzten True innerhalb des Fensters, sonst None."""
    tail = s.to_numpy()[-window:]
    hits = np.flatnonzero(tail)
    if len(hits) == 0:
        return None
    return int(len(tail) - 1 - hits[-1])


def evaluate(df: pd.DataFrame, cfg: Config = DEFAULT) -> Result:
    """Prüft eine Aktie (OHLCV-DataFrame mit Tageskerzen) auf alle Kriterien."""
    df = df.dropna(subset=["Close", "Low", "High"])
    close = df["Close"]
    w = cfg.signal_window

    # Pflicht 1: RSI-Divergenz im Zeitfenster
    r = rsi(close, cfg.rsi_length)
    divs = [d for d in find_divergences(df, r, cfg) if d.age < w]

    # Pflicht 2: MACD-Histogramm rot, aber kleiner werdend
    hist = macd(close, cfg.macd_fast, cfg.macd_slow, cfg.macd_signal)["hist"]
    macd_age = _last_true_age(macd_condition(hist, cfg), w)
    last_hist = float(hist.iloc[-1])
    if last_hist < 0:
        macd_status = "rot, steigend" if hist.iloc[-1] > hist.iloc[-2] else "rot"
    else:
        green_days = 0
        for v in reversed(hist.to_numpy()):
            if v < 0:
                break
            green_days += 1
        macd_status = f"grün seit {green_days} T."

    # Pflicht 3: grünes X im Momentum Bias Index
    mbi = momentum_bias_index(
        close,
        cfg.mbi_momentum_length,
        cfg.mbi_bias_length,
        cfg.mbi_smooth_length,
        cfg.mbi_impulse_length,
        cfg.mbi_std_mult,
    )
    mbi_age = _last_true_age(mbi["green_x"], w)

    passed = bool(divs) and macd_age is not None and mbi_age is not None

    # Weich: Abstand zum Hoch
    high = df["High"].rolling(cfg.drawdown_lookback, min_periods=1).max()
    drawdown = float(1 - close.iloc[-1] / high.iloc[-1])

    # Weich: Volumen
    vol = df["Volume"].astype(float) if "Volume" in df else pd.Series(0.0, index=df.index)
    vol_avg = vol.rolling(cfg.volume_avg_length, min_periods=1).mean().shift(1)
    volume_spike = False
    if divs:
        pivot_pos = df.index.get_loc(pd.Timestamp(divs[-1].pivot_date))
        lo, hi = max(0, pivot_pos - 2), min(len(df), pivot_pos + 3)
        ratio = (vol.iloc[lo:hi] / vol_avg.iloc[lo:hi]).max()
        volume_spike = bool(ratio >= cfg.volume_spike)
    recent = df.iloc[-5:]
    up_days = recent["Close"] > recent["Open"] if "Open" in recent else recent["Close"].diff() > 0
    volume_recovery = bool(
        up_days.any() and vol.iloc[-5:][up_days].mean() > vol_avg.iloc[-1]
    )

    dollar_volume = float((close * vol).iloc[-cfg.volume_avg_length :].mean())

    score = 0.0
    if passed:
        kinds = {d.kind for d in divs}
        score += 25 if len(kinds) == 2 else (20 if "klassisch" in kinds else 15)
        ages = [min(d.age for d in divs), macd_age, mbi_age]
        score += 15 * (1 - np.mean(ages) / w)
        score += 10 if last_hist < 0 else 5
        span = cfg.drawdown_full - cfg.drawdown_min
        score += 30 * float(np.clip((drawdown - cfg.drawdown_min) / span, 0, 1))
        score += 10 * volume_spike + 10 * volume_recovery

    return Result(
        passed=passed,
        score=round(score, 1),
        close=round(float(close.iloc[-1]), 4),
        rsi=round(float(r.iloc[-1]), 2),
        drawdown_pct=round(drawdown * 100, 1),
        divergences=divs,
        macd_age=macd_age,
        macd_status=macd_status,
        mbi_age=mbi_age,
        volume_spike=volume_spike,
        volume_recovery=volume_recovery,
        dollar_volume=round(dollar_volume, 0),
    )
