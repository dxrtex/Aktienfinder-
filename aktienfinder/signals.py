"""Signal-Erkennung und Scoring für eine einzelne Aktie."""

from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

from .config import DEFAULT, Config
from .indicators import ema, macd, pivot_low, rsi
from .mbi import momentum_bias_index


@dataclass
class Divergence:
    kind: str            # "klassisch" oder "versteckt"
    pivot_date: str      # Datum des jüngeren Tiefs
    prev_pivot_date: str # Datum des Vergleichstiefs
    confirmed_date: str  # Datum, an dem das jüngere Tief bestätigt war
    age: int             # Handelstage seit Bestätigung
    price_low: float
    prev_price_low: float
    rsi_low: float
    prev_rsi_low: float
    bars_between: int


@dataclass
class Cluster:
    """Das Bündel aus den drei Pflichtsignalen."""
    divergence_age: int
    macd_age: int
    mbi_age: int
    span: int            # Abstand zwischen ältestem und jüngstem Signal (Handelstage)


@dataclass
class Result:
    passed: bool
    score: float
    close: float
    rsi: float
    drawdown_pct: float
    divergences: list = field(default_factory=list)
    cluster: Cluster | None = None
    macd_status: str = ""
    mbi_status: str = ""
    fib_retracement: float | None = None   # tiefster Rücksetzer des letzten Schwungs (0–1)
    fib_zone: bool = False
    ema_breakout_age: int | None = None    # Tage seit Ausbruch über die EMA 20
    volume_spike: bool = False
    volume_breakout: bool = False
    dollar_volume: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


def find_divergences(df: pd.DataFrame, osc: pd.Series, cfg: Config = DEFAULT) -> list[Divergence]:
    """Bullische Divergenzen auf Basis der Pivot-Tiefs im RSI.

    Jedes Tief wird mit allen früheren Tiefs im Abstand von
    `divergence_min_bars`–`divergence_max_bars` verglichen (nicht nur mit dem direkt
    vorherigen), weil man im Chart auch gegen das markante Tief Wochen vorher vergleicht.
    Pro Tief und Art wird die stärkste Divergenz (größte RSI-Differenz) behalten.

    Klassisch: Kurs tieferes Tief, RSI höheres Tief.
    Versteckt: Kurs höheres Tief, RSI tieferes Tief.
    """
    found = np.flatnonzero(pivot_low(osc, cfg.pivot_left, cfg.pivot_right).to_numpy())
    low = df["Low"].to_numpy(dtype=float)
    o = osc.to_numpy(dtype=float)
    idx = df.index
    n = len(df)
    r = cfg.pivot_right

    out = []
    for k, i in enumerate(found):
        best: dict[str, tuple[float, int]] = {}
        for j in found[:k]:
            between = i - j
            if not cfg.divergence_min_bars <= between <= cfg.divergence_max_bars:
                continue
            c, p = i - r, j - r
            if low[c] < low[p] and o[c] > o[p]:
                kind = "klassisch"
            elif low[c] > low[p] and o[c] < o[p]:
                kind = "versteckt"
            else:
                continue
            strength = abs(o[c] - o[p])
            if kind not in best or strength > best[kind][0]:
                best[kind] = (strength, j)
        for kind, (_, j) in best.items():
            c, p = i - r, j - r
            out.append(
                Divergence(
                    kind=kind,
                    pivot_date=str(idx[c].date()),
                    prev_pivot_date=str(idx[p].date()),
                    confirmed_date=str(idx[i].date()),
                    age=int(n - 1 - i),
                    price_low=round(low[c], 4),
                    prev_price_low=round(low[p], 4),
                    rsi_low=round(o[c], 2),
                    prev_rsi_low=round(o[p], 2),
                    bars_between=int(i - j),
                )
            )
    return out


def macd_condition(hist: pd.Series, cfg: Config = DEFAULT) -> pd.Series:
    """Rote Balken, die seit `macd_rising_bars` Tagen kleiner werden und nahe null sind."""
    rising = pd.Series(True, index=hist.index)
    for k in range(cfg.macd_rising_bars):
        rising &= hist.shift(k) > hist.shift(k + 1)
    trough = hist.rolling(cfg.macd_trough_lookback, min_periods=1).min()
    near_zero = hist >= trough * cfg.macd_near_zero
    return (hist < 0) & rising & near_zero & (trough < 0)


def find_cluster(div_ages: list[int], macd_ages: list[int], mbi_ages: list[int],
                 cfg: Config = DEFAULT) -> Cluster | None:
    """Sucht das jüngste Bündel, in dem alle drei Signale ≤ `cluster_span` auseinanderliegen.

    Alter in Handelstagen (0 = heute); alle Signale müssen ≤ `max_signal_age` sein.
    """
    best = None
    macd_sorted = sorted(a for a in macd_ages if a <= cfg.max_signal_age)
    for d in (a for a in div_ages if a <= cfg.max_signal_age):
        for x in (a for a in mbi_ages if a <= cfg.max_signal_age):
            # MACD-Signal so wählen, dass die Spanne minimal und das Bündel möglichst jung ist
            lo_bound = max(d, x) - cfg.cluster_span
            hi_bound = min(d, x) + cfg.cluster_span
            for m in macd_sorted:
                if lo_bound <= m <= hi_bound:
                    ages = (d, m, x)
                    span = max(ages) - min(ages)
                    if span > cfg.cluster_span:
                        continue
                    key = (max(ages), span)
                    if best is None or key < best[0]:
                        best = (key, Cluster(d, m, x, span))
    return best[1] if best else None


def _ages(mask: pd.Series) -> list[int]:
    arr = mask.to_numpy()
    return [int(len(arr) - 1 - i) for i in np.flatnonzero(arr)]


def fib_retracement(df: pd.DataFrame, cfg: Config = DEFAULT) -> float | None:
    """Wie tief ist der Kurs seit dem letzten Hoch in den vorherigen Aufwärtsschwung zurückgelaufen?

    0 = am Hoch, 0.618/0.786 = klassische Fibonacci-Zone, 1 = zurück am Schwungtief.
    Grundlage ist das höchste Hoch der letzten `fib_lookback` Tage und das tiefste Tief davor.
    """
    window = df.iloc[-cfg.fib_lookback :]
    highs = window["High"].to_numpy(dtype=float)
    lows = window["Low"].to_numpy(dtype=float)
    hi_pos = int(np.argmax(highs))
    if hi_pos < 5 or hi_pos >= len(window) - 3:
        return None
    swing_low = lows[:hi_pos].min()
    swing_high = highs[hi_pos]
    if swing_high <= swing_low:
        return None
    pullback_low = lows[hi_pos + 1 :].min()
    return float((swing_high - pullback_low) / (swing_high - swing_low))


def evaluate(df: pd.DataFrame, cfg: Config = DEFAULT) -> Result:
    """Prüft eine Aktie (OHLCV-DataFrame mit Tageskerzen) auf alle Kriterien."""
    df = df.dropna(subset=["Close", "Low", "High"])
    close = df["Close"]

    # Pflicht 1: RSI-Divergenz
    r = rsi(close, cfg.rsi_length)
    divs = [d for d in find_divergences(df, r, cfg) if d.age <= cfg.max_signal_age]

    # Pflicht 2: MACD-Histogramm rot, aber kleiner werdend
    hist = macd(close, cfg.macd_fast, cfg.macd_slow, cfg.macd_signal)["hist"]
    macd_ok = macd_condition(hist, cfg)
    last_hist = float(hist.iloc[-1])
    if last_hist < 0:
        macd_status = "rot, schrumpfend" if hist.iloc[-1] > hist.iloc[-2] else "rot"
        macd_green_days = 0
    else:
        macd_green_days = 0
        for v in reversed(hist.to_numpy()):
            if v < 0:
                break
            macd_green_days += 1
        macd_status = f"grün seit {macd_green_days} T."

    # Pflicht 3: grünes X im Momentum Bias Index
    mbi = momentum_bias_index(
        close,
        df["High"],
        df["Low"],
        cfg.mbi_momentum_length,
        cfg.mbi_bias_length,
        cfg.mbi_smooth_length,
        cfg.mbi_impulse_length,
        cfg.mbi_std_mult,
    )
    buyers_lead = bool(mbi["upper_bias"].iloc[-1] > mbi["lower_bias"].iloc[-1])
    mbi_status = "grün" if buyers_lead else "rot"

    cluster = find_cluster([d.age for d in divs], _ages(macd_ok), _ages(mbi["green_x"]), cfg)
    passed = cluster is not None
    if cluster:
        mbi_status = f"X vor {cluster.mbi_age} T., jetzt {mbi_status}"

    # Weich: Abstand zum Hoch
    high = df["High"].rolling(cfg.drawdown_lookback, min_periods=1).max()
    drawdown = float(1 - close.iloc[-1] / high.iloc[-1])

    # Weich: Fibonacci-Zone
    fib = fib_retracement(df, cfg)
    lo_z, hi_z = cfg.fib_zone
    fib_zone = fib is not None and lo_z - cfg.fib_tolerance <= fib <= hi_z + cfg.fib_tolerance

    # Weich: Ausbruch über die EMA 20 (Einstiegs-Trigger)
    e20 = ema(close, cfg.ema_trigger_length)
    above = (close > e20).to_numpy()
    breakout_age = None
    if above[-1]:
        k = 0
        while k + 1 < len(above) and above[-(k + 2)]:
            k += 1
        breakout_age = k  # 0 = heute ausgebrochen

    # Weich: Volumen
    vol = df["Volume"].astype(float) if "Volume" in df else pd.Series(0.0, index=df.index)
    vol_avg = vol.rolling(cfg.volume_avg_length, min_periods=1).mean().shift(1)
    vol_ratio = (vol / vol_avg).replace([np.inf, -np.inf], np.nan)
    volume_spike = False
    if divs:
        pivot_pos = df.index.get_loc(pd.Timestamp(divs[-1].pivot_date))
        near = vol_ratio.iloc[max(0, pivot_pos - 2) : pivot_pos + 3]
        volume_spike = bool(near.max() >= cfg.volume_spike)
    volume_breakout = bool(vol_ratio.iloc[-cfg.trigger_max_age :].max() >= cfg.volume_spike)

    dollar_volume = float((close * vol).iloc[-cfg.volume_avg_length :].mean())

    score = 0.0
    if passed:
        kinds = {d.kind for d in divs}
        score += 15 if "klassisch" in kinds else 12
        newest = min(cluster.divergence_age, cluster.macd_age, cluster.mbi_age)
        score += 7.5 * (1 - cluster.span / cfg.cluster_span)
        score += 7.5 * (1 - newest / cfg.max_signal_age)
        if last_hist < 0 and hist.iloc[-1] > hist.iloc[-2]:
            score += 10          # Lieblings-Einstieg: rot, kurz vor Grün
        elif 0 < macd_green_days <= 10:
            score += 8
        else:
            score += 4
        score += 5 * buyers_lead
        span = cfg.drawdown_full - cfg.drawdown_min
        score += 15 * float(np.clip((drawdown - cfg.drawdown_min) / span, 0, 1))
        score += 15 * fib_zone
        if breakout_age is not None and breakout_age < cfg.trigger_max_age:
            score += 15
        elif breakout_age is not None:
            score += 7
        score += 5 * volume_spike + 5 * volume_breakout

    return Result(
        passed=passed,
        score=round(score, 1),
        close=round(float(close.iloc[-1]), 4),
        rsi=round(float(r.iloc[-1]), 2),
        drawdown_pct=round(drawdown * 100, 1),
        divergences=divs,
        cluster=cluster,
        macd_status=macd_status,
        mbi_status=mbi_status,
        fib_retracement=None if fib is None else round(fib, 3),
        fib_zone=bool(fib_zone),
        ema_breakout_age=breakout_age,
        volume_spike=volume_spike,
        volume_breakout=volume_breakout,
        dollar_volume=round(dollar_volume, 0),
    )
