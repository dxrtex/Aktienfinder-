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
    pullback_drawdown_pct: float = 0.0     # Rücksetzer-Tief unter dem 52-Wochen-Hoch
    signals_ok: bool = False               # die drei Indikator-Signale allein erfüllt
    divergences: list = field(default_factory=list)
    cluster: Cluster | None = None
    macd_status: str = ""
    mbi_status: str = ""
    fib_retracement: float | None = None   # tiefster Rücksetzer des letzten Schwungs (0–1)
    fib_zone: bool = False
    ema_breakout_age: int | None = None    # Tage seit Ausbruch über die EMA 20
    volume_spike: bool = False
    volume_breakout: bool = False
    reversal_candle_age: int | None = None # bullische Umkehrkerze mit Volumen an Fib-Linie
    green_x_count: int = 0                 # grüne MBI-X in den letzten 30 Tagen
    rise_from_low_pct: float = 0.0         # Kurs über dem jüngsten Tief (30 T.) in %
    still_falling: bool = False            # neues Tief in den letzten 2 Tagen
    criteria: dict = field(default_factory=dict)   # Einzelkriterien erfüllt ja/nein
    status: str = "kein_setup"             # bereit | abwarten | gelaufen | kein_setup
    core_met: list = field(default_factory=list)   # erfüllte Kernkriterien des Gesamtpakets
    divergence_forming: str | None = None  # Divergenz in Bildung (letztes Tief noch unbestätigt)
    stop_price: float | None = None        # Stop knapp unter dem Rücksetzer-Tief
    target_price_fib: float | None = None  # technisches Ziel: Fib 0,382 des Schwungs (bzw. Hoch)
    chance_pct: float | None = None
    risk_pct: float | None = None
    crv: float | None = None               # Chance/Risiko-Verhältnis
    macd_closeness: float = 0.0            # rotes Histogramm: Anteil des tiefsten Balkens aufgeholt (1 = an 0)
    rsi_signal_gap: float = 0.0            # RSI minus gelbe Signallinie (≥ −2: „fast darauf“)
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


def macd_condition(hist: pd.Series, cfg: Config = DEFAULT, line: pd.Series | None = None) -> pd.Series:
    """Rote Balken, die seit `macd_rising_bars` Tagen kleiner werden und nahe null sind.

    Mit `line` (MACD-Linie) und `cfg.macd_line_rising` darf die Linie zusätzlich nicht mehr
    fallen (seitwärts oder steigend, wie bei Uber am 2.10.2026).
    """
    rising = pd.Series(True, index=hist.index)
    for k in range(cfg.macd_rising_bars):
        rising &= hist.shift(k) > hist.shift(k + 1)
    trough = hist.rolling(cfg.macd_trough_lookback, min_periods=1).min()
    near_zero = hist >= trough * cfg.macd_near_zero
    cond = (hist < 0) & rising & near_zero & (trough < 0)
    if line is not None and cfg.macd_line_rising:
        # Linie fällt nicht mehr: heute (fast) so hoch wie vor `macd_line_lookback` Tagen
        scale = line.abs().rolling(60, min_periods=1).max()
        cond &= line >= line.shift(cfg.macd_line_lookback) - cfg.macd_line_tolerance * scale
    return cond


def forming_divergence(df: pd.DataFrame, osc: pd.Series, cfg: Config = DEFAULT) -> str | None:
    """Divergenz in Bildung (noch unbestätigt): Das Tief der letzten Kerzen ist noch nicht durch
    `pivot_right` Folgekerzen bestätigt, bildet aber mit einem früheren bestätigten RSI-Tief bereits
    eine Divergenz. Liefert "klassisch", "versteckt" oder None."""
    n = len(df)
    r, left = cfg.pivot_right, cfg.pivot_left
    if n < left + r + 5:
        return None
    low = df["Low"].to_numpy(dtype=float)
    o = osc.to_numpy(dtype=float)
    c = n - r + int(np.argmin(low[n - r :]))          # tiefste der noch unbestätigten Kerzen
    if low[c] > low[max(0, c - 10) : c].min() or not np.isfinite(o[c]):
        return None                                   # kein neues Tief der letzten 2 Wochen
    pivots = np.flatnonzero(pivot_low(osc, left, r).to_numpy()) - r
    best = None
    for p in pivots[::-1]:
        if not cfg.divergence_min_bars <= c - p <= cfg.divergence_max_bars:
            continue
        if low[c] < low[p] and o[c] > o[p] + 2:      # mind. 2 RSI-Punkte höher
            return "klassisch"
        if best is None and low[c] > low[p] and o[c] < o[p] - 2:
            best = "versteckt"
    return best


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


def _swing_candidates(df: pd.DataFrame, cfg: Config) -> list[tuple[float, float, float]]:
    """Aufwärtsschwünge zum Hoch der letzten `fib_lookback` Tage: kurzer Schwung (Tief im selben
    Fenster) und großer Schwung (Tief bis `fib_low_lookback` Tage vor dem Hoch – so wie man die
    Fibonacci in TradingView vom Tief der ganzen Aufwärtsbewegung zieht)."""
    n = len(df)
    start = max(0, n - cfg.fib_lookback)
    highs = df["High"].to_numpy(dtype=float)
    lows = df["Low"].to_numpy(dtype=float)
    hi_pos = start + int(np.argmax(highs[start:]))
    if hi_pos - start < 5 or hi_pos >= n - 3:
        return []
    swing_high = float(highs[hi_pos])
    pullback_low = float(lows[hi_pos + 1 :].min())
    out = []
    for lo_start in (start, max(0, hi_pos - cfg.fib_low_lookback)):
        swing_low = float(lows[lo_start:hi_pos].min())
        if swing_high > swing_low and (swing_high, swing_low, pullback_low) not in out:
            out.append((swing_high, swing_low, pullback_low))
    return out


def fib_swing(df: pd.DataFrame, cfg: Config = DEFAULT) -> tuple[float, float, float] | None:
    """Maßgeblicher Aufwärtsschwung: (Schwunghoch, Schwungtief, tiefster Kurs seit dem Hoch).

    Bevorzugt den Schwung, in dessen Fibonacci-Bereich (0,618 … Schwungtief) der Rücksetzer liegt;
    passt keiner, den kurzen Schwung.
    """
    cands = _swing_candidates(df, cfg)
    if not cands:
        return None
    lo_r, hi_r = cfg.fib_required
    for high, low, pb in cands:
        if lo_r - cfg.fib_tolerance <= (high - pb) / (high - low) <= hi_r + cfg.fib_tolerance:
            return high, low, pb
    return cands[0]


def fib_retracement(df: pd.DataFrame, cfg: Config = DEFAULT) -> float | None:
    """Wie tief ist der Kurs seit dem letzten Hoch in den vorherigen Aufwärtsschwung zurückgelaufen?

    0 = am Hoch, 0.618/0.786 = klassische Fibonacci-Zone, 1 = zurück am Schwungtief.
    """
    swing = fib_swing(df, cfg)
    if swing is None:
        return None
    high, low, pullback_low = swing
    return (high - pullback_low) / (high - low)


def reversal_candle(df: pd.DataFrame, vol_ratio: pd.Series, cfg: Config = DEFAULT) -> int | None:
    """Alter (Tage) der jüngsten bullischen Umkehrkerze an einer Fibonacci-Linie, sonst None.

    Bedingungen: grüne Kerze, Schluss im oberen Drittel der Spanne, Volumen ≥ `volume_spike` ×
    Durchschnitt und Kerzentief höchstens `fib_level_tolerance` (Anteil der Schwunghöhe) neben
    einer Fibonacci-Linie des letzten Aufwärtsschwungs.
    """
    swing = fib_swing(df, cfg)
    if swing is None:
        return None
    high, low, _ = swing
    levels = [high - lvl * (high - low) for lvl in cfg.fib_levels]
    tol = cfg.fib_level_tolerance * (high - low)
    n = len(df)
    for age in range(min(cfg.reversal_lookback, n)):
        row = df.iloc[n - 1 - age]
        rng = row["High"] - row["Low"]
        if not (rng > 0 and row["Close"] > row["Open"]):
            continue
        if (row["Close"] - row["Low"]) / rng < 2 / 3:
            continue
        if not vol_ratio.iloc[n - 1 - age] >= cfg.volume_spike:
            continue
        if any(abs(row["Low"] - lvl) <= tol for lvl in levels):
            return age
    return None


def evaluate(df: pd.DataFrame, cfg: Config = DEFAULT) -> Result:
    """Prüft eine Aktie (OHLCV-DataFrame mit Tageskerzen) auf alle Kriterien."""
    df = df.dropna(subset=["Close", "Low", "High"])
    close = df["Close"]

    # Pflicht 1: RSI-Divergenz
    r = rsi(close, cfg.rsi_length)
    divs = [d for d in find_divergences(df, r, cfg) if d.age <= cfg.max_signal_age]
    rsi_ma = r.rolling(cfg.rsi_signal_length).mean()
    rsi_gap = float(r.iloc[-1] - rsi_ma.iloc[-1])   # > 0: RSI über seiner Signallinie

    # Pflicht 2: MACD-Histogramm rot, aber kleiner werdend
    m = macd(close, cfg.macd_fast, cfg.macd_slow, cfg.macd_signal)
    hist = m["hist"]
    macd_ok = macd_condition(hist, cfg, m["macd"])
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
    if cluster:
        mbi_status = f"X vor {cluster.mbi_age} T., jetzt {mbi_status}"

    # Pflicht 4: starker Rückgang – Rücksetzer-Tief mind. `min_drawdown` unter dem 52-Wochen-Hoch
    high = df["High"].rolling(cfg.drawdown_lookback, min_periods=1).max()
    drawdown = float(1 - close.iloc[-1] / high.iloc[-1])
    recent_low = float(df["Low"].iloc[-cfg.max_signal_age :].min())
    pullback_drawdown = float(1 - recent_low / high.iloc[-1])

    # Pflicht 5: Fibonacci – Rücksetzer hat mind. die Golden Zone erreicht, nicht das Schwungtief gebrochen
    fib = fib_retracement(df, cfg)
    lo_z, hi_z = cfg.fib_zone
    fib_zone = fib is not None and lo_z - cfg.fib_tolerance <= fib <= hi_z + cfg.fib_tolerance
    lo_r, hi_r = cfg.fib_required
    fib_ok = fib is not None and lo_r - cfg.fib_tolerance <= fib <= hi_r + cfg.fib_tolerance

    signals_ok = cluster is not None
    passed = (signals_ok and pullback_drawdown >= cfg.min_drawdown
              and (fib_ok or not cfg.require_fib_zone))

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
    reversal_age = reversal_candle(df, vol_ratio, cfg) if "Open" in df else None

    dollar_volume = float((close * vol).iloc[-cfg.volume_avg_length :].mean())

    # Einstiegsnähe: Abstand zum jüngsten Tief, fällt der Kurs noch?
    rise_from_low = float(close.iloc[-1] / recent_low - 1)
    still_falling = bool(df["Low"].iloc[-2:].min() <= recent_low)   # Tief der letzten 30 T. in den letzten 2 T.

    green_x_count = int(mbi["green_x"].iloc[-cfg.max_signal_age :].sum())
    sellers_fading = bool(mbi["lower_bias"].iloc[-1] < mbi["lower_bias"].iloc[-2])
    macd_red_shrinking = last_hist < 0 and hist.iloc[-1] > hist.iloc[-2]

    # Einzelkriterien (für die Watchlist-Ampel; auch ohne vollständiges Setup)
    criteria = {
        "rueckgang": pullback_drawdown >= cfg.min_drawdown,
        "fibonacci": bool(fib_ok),
        "divergenz": bool(divs),
        "macd": bool(macd_ok.iloc[-cfg.max_signal_age :].any()),
        "mbi": green_x_count > 0,
        "buendel": signals_ok,
    }

    # MACD-Nähe zur Nulllinie: wie viel des tiefsten roten Balkens (20 T.) ist schon aufgeholt?
    trough = float(hist.iloc[-cfg.macd_trough_lookback :].min())
    macd_closeness = float(np.clip(1 - last_hist / trough, 0, 1)) if trough < 0 and last_hist < 0 else 0.0
    line = m["macd"]
    scale = float(line.abs().iloc[-60:].max() or 1)
    macd_lines_ok = bool(line.iloc[-1] >= line.iloc[-1 - cfg.macd_line_lookback] - cfg.macd_line_tolerance * scale)

    # Divergenz in Bildung (unbestätigt) – nur als Vorab-Hinweis, zählt nicht als Kernkriterium
    forming = forming_divergence(df, r, cfg)

    # Chance/Risiko: Stop knapp unter dem Rücksetzer-Tief, Ziel = Fib 0,382 des Schwungs (max. Hoch)
    stop_price = target_fib = chance = risk = crv = None
    swing = fib_swing(df, cfg)
    last = float(close.iloc[-1])
    if swing is not None:
        s_high, s_low, s_pb = swing
        stop_price = min(s_pb, recent_low) * (1 - cfg.stop_buffer)
        target_fib = s_high - 0.382 * (s_high - s_low)
        if target_fib <= last * 1.02:
            target_fib = s_high
        if stop_price < last < target_fib:
            chance = target_fib / last - 1
            risk = 1 - stop_price / last
            crv = chance / risk if risk > 0 else None

    # Score (0–100): das Gesamtpaket zählt am meisten – erst wenn alle Kernkriterien erfüllt sind,
    # gibt es die hohen Punkte; MACD nahe 0 (noch rot) und Einstiegsnähe heben danach die Besten heraus
    kinds = {d.kind for d in divs}
    core = [
        pullback_drawdown >= cfg.min_drawdown,       # Rückgang ≥ 20 %
        fib_ok,                                      # Fibonacci (Golden Zone bis Schwungtief)
        bool(kinds),                                 # bullische RSI-Divergenz (klassisch/versteckt)
        macd_red_shrinking and macd_lines_ok,        # Histogramm rot & schrumpfend, Linien fallen nicht mehr
        green_x_count >= 1,                          # grünes MBI-X
    ]
    core_names = ("rueckgang", "fibonacci", "divergenz", "macd_jetzt", "mbi_x")
    core_met = [n for n, ok in zip(core_names, core) if ok]
    score = 5.0 * sum(core) + 16 * all(core)         # Gesamtpaket: bis 41
    if macd_red_shrinking:
        score += 12 * macd_closeness                 # je näher das rote Histogramm an 0, desto besser
    elif 0 < macd_green_days <= 3:
        score += 3                                   # schon grün – etwas spät
    span = cfg.entry_zero - cfg.entry_full
    score += 10 * float(np.clip((cfg.entry_zero - rise_from_low) / span, 0, 1))   # Einstiegsnähe
    score += 3 * ("klassisch" in kinds)
    if forming and not kinds:
        score += 4                                   # Divergenz bildet sich gerade (unbestätigt)
    score += 4 * (green_x_count >= 2)
    score += 4 * sellers_fading                      # rote MBI-Balken rückläufig
    score += 6 * (reversal_age is not None)          # Umkehrkerze mit Volumen an Fib-Linie
    score += 6 * (-cfg.rsi_signal_gap <= rsi_gap <= 5)   # RSI (fast) auf der Signallinie
    score += 3 * fib_zone                            # in der Golden Zone (statt darunter)
    score += 6 * (pullback_drawdown >= 0.30)        # Backtest: tiefer Rücksetzer → +20 % deutlich häufiger
    if cluster:
        newest = min(cluster.divergence_age, cluster.macd_age, cluster.mbi_age)
        score += 5 * (1 - newest / cfg.max_signal_age)

    # Setup-Status (regelbasiert, keine Kursprognose)
    if not passed:
        status = "abwarten" if sum(criteria.values()) >= 3 else "kein_setup"
    elif rise_from_low >= cfg.status_ran_rise or macd_green_days > cfg.status_ran_green_days:
        status = "gelaufen"
    elif (rise_from_low <= cfg.status_ready_max_rise and not still_falling
          and macd_red_shrinking and macd_lines_ok          # Histogramm noch rot, Linien fallen nicht mehr
          and (sellers_fading or buyers_lead)):
        status = "bereit"
    else:
        status = "abwarten"

    return Result(
        passed=passed,
        score=round(score, 1),
        close=round(float(close.iloc[-1]), 4),
        rsi=round(float(r.iloc[-1]), 2),
        drawdown_pct=round(drawdown * 100, 1),
        pullback_drawdown_pct=round(pullback_drawdown * 100, 1),
        signals_ok=signals_ok,
        divergences=divs,
        cluster=cluster,
        macd_status=macd_status,
        mbi_status=mbi_status,
        fib_retracement=None if fib is None else round(fib, 3),
        fib_zone=bool(fib_zone),
        ema_breakout_age=breakout_age,
        volume_spike=volume_spike,
        volume_breakout=volume_breakout,
        reversal_candle_age=reversal_age,
        green_x_count=green_x_count,
        rsi_signal_gap=round(rsi_gap, 2),
        dollar_volume=round(dollar_volume, 0),
        rise_from_low_pct=round(rise_from_low * 100, 1),
        still_falling=still_falling,
        criteria=criteria,
        status=status,
        macd_closeness=round(macd_closeness, 2),
        core_met=core_met,
        divergence_forming=forming,
        stop_price=None if stop_price is None else round(stop_price, 4),
        target_price_fib=None if target_fib is None else round(target_fib, 4),
        chance_pct=None if chance is None else round(100 * chance, 1),
        risk_pct=None if risk is None else round(100 * risk, 1),
        crv=None if crv is None else round(crv, 2),
    )
