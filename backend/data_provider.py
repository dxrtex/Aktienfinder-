"""Datenschicht: Kurse, Börsenwert und Earnings-Termine hinter einer austauschbaren Schnittstelle.

`DataProvider` beschreibt, was der Scanner braucht. `YFinanceProvider` liefert es kostenlos über
Yahoo Finance; ein bezahlter Anbieter (FMP, Polygon, EODHD …) kann später dieselbe Schnittstelle
implementieren (API-Key per `.env`). Kurse werden in SQLite zwischengespeichert und täglich nur
inkrementell nachgeladen.
"""

from __future__ import annotations

import sqlite3
import time
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

from .config import ROOT

CACHE_PATH = ROOT / "data" / "cache.sqlite"


class DataProvider(ABC):
    @abstractmethod
    def history(self, tickers: list[str], period: str, end: str | None = None) -> dict[str, pd.DataFrame]:
        """Tageskerzen (Open, High, Low, Close, Volume) je Ticker; `end` exklusiv (ISO-Datum)."""

    @abstractmethod
    def info(self, ticker: str) -> dict:
        """Stammdaten: name, currency, market_cap, exchange, quote_type, earnings_date (ISO oder None)."""


class YFinanceProvider(DataProvider):
    def __init__(self, batch_size: int = 200, retries: int = 3, threads: int = 8):
        self.batch_size, self.retries, self.threads = batch_size, retries, threads

    def history(self, tickers, period, end=None):
        import yfinance as yf

        out = {}
        for start in range(0, len(tickers), self.batch_size):
            batch = tickers[start : start + self.batch_size]
            data = None
            for attempt in range(self.retries):
                try:
                    kw = {"period": period} if end is None else {"start": _period_start(end, period), "end": end}
                    data = yf.download(batch, interval="1d", group_by="ticker", auto_adjust=True,
                                       progress=False, threads=True, **kw)
                    break
                except Exception:   # Rate-Limit / Netzwerk: mit Backoff erneut versuchen
                    time.sleep(5 * 2 ** attempt)
            if data is None or data.empty:
                continue
            for t in batch:
                try:
                    df = data[t] if isinstance(data.columns, pd.MultiIndex) else data
                except KeyError:
                    continue
                df = df[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
                if len(df):
                    df.index = pd.to_datetime(df.index).tz_localize(None)
                    out[t] = df
        return out

    def info(self, ticker):
        import yfinance as yf

        tk = yf.Ticker(ticker)
        for attempt in range(self.retries):
            try:
                i = tk.info or {}
                return {
                    "name": i.get("longName") or i.get("shortName") or ticker,
                    "currency": i.get("currency"),
                    "market_cap": i.get("marketCap"),
                    "exchange": i.get("exchange"),
                    "quote_type": i.get("quoteType"),
                    "sector": i.get("sector"),
                    "earnings_date": _next_earnings(i),
                    "earnings_estimate": bool(i.get("isEarningsDateEstimate")),
                    "ex_dividend_date": _future_date(i.get("exDividendDate")),
                    "dividend_date": _future_date(i.get("dividendDate")),
                    "dividend_rate": i.get("dividendRate"),
                }
            except Exception:
                time.sleep(2 * (attempt + 1))
        return {"name": ticker}

    def infos(self, tickers: list[str]) -> dict[str, dict]:
        with ThreadPoolExecutor(max_workers=self.threads) as pool:
            return dict(zip(tickers, pool.map(self.info, tickers)))


def _period_start(end: str, period: str) -> str:
    years = {"1y": 1, "2y": 2, "3y": 3, "5y": 5}.get(period, 2)
    return str((pd.Timestamp(end) - pd.DateOffset(years=years)).date())


def _future_date(stamp) -> str | None:
    """Unix-Zeitstempel → ISO-Datum, nur wenn heute oder später."""
    if not isinstance(stamp, (int, float)):
        return None
    d = pd.Timestamp(stamp, unit="s", tz="UTC")
    return str(d.date()) if d >= pd.Timestamp.now(tz="UTC").normalize() else None


def _next_earnings(info: dict) -> str | None:
    today = pd.Timestamp.now(tz="UTC").normalize()
    stamps = [info.get(k) for k in ("earningsTimestampStart", "earningsTimestamp")]
    dates = sorted(pd.Timestamp(v, unit="s", tz="UTC") for v in stamps if isinstance(v, (int, float)))
    future = [d for d in dates if d >= today]
    return str(future[0].date()) if future else None


class CachedProvider(DataProvider):
    """Speichert Kurse in SQLite und lädt nur fehlende Tage nach."""

    def __init__(self, inner: DataProvider, path: Path | str = CACHE_PATH):
        self.inner = inner
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as con:
            con.execute("""CREATE TABLE IF NOT EXISTS bars (ticker TEXT, date TEXT, open REAL, high REAL,
                           low REAL, close REAL, volume REAL, PRIMARY KEY (ticker, date))""")

    def history(self, tickers, period, end=None):
        if end is not None:                       # feste Stichtage (Regression) immer frisch laden
            return self.inner.history(tickers, period, end)
        fresh = self.inner.history(tickers, period if not self._cached_any(tickers) else "1mo")
        with sqlite3.connect(self.path) as con:
            for t, df in fresh.items():
                con.executemany("INSERT OR REPLACE INTO bars VALUES (?,?,?,?,?,?,?)",
                                [(t, str(d.date()), *map(float, r)) for d, r in
                                 df[["Open", "High", "Low", "Close", "Volume"]].iterrows()])
            out = {}
            for t in tickers:
                rows = con.execute("SELECT date, open, high, low, close, volume FROM bars WHERE ticker=? ORDER BY date",
                                   (t,)).fetchall()
                if rows:
                    df = pd.DataFrame(rows, columns=["Date", "Open", "High", "Low", "Close", "Volume"])
                    out[t] = df.set_index(pd.to_datetime(df.pop("Date")))
        # Ticker, die noch gar nicht im Cache waren, komplett nachladen
        missing = [t for t in tickers if t not in out or len(out[t]) < 250]
        if missing and period != "1mo":
            full = self.inner.history(missing, period)
            out.update(full)
        return out

    def _cached_any(self, tickers) -> bool:
        with sqlite3.connect(self.path) as con:
            n = con.execute(f"SELECT COUNT(DISTINCT ticker) FROM bars WHERE ticker IN ({','.join('?' * len(tickers))})",
                            tickers).fetchone()[0]
        return n >= 0.8 * len(tickers)

    def info(self, ticker):
        return self.inner.info(ticker)
