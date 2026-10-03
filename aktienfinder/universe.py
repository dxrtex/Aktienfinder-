"""Stellt die Liste der zu scannenden Aktien zusammen (USA, Europa, global).

Grundlage ist der Yahoo-Finance-Screener: je Land alle Aktien an der Heimatbörse mit einem
Börsenwert von mindestens `MIN_MARKET_CAP_USD` (Mid und Large Caps, keine Small Caps).
Zweitlistings an Nebenbörsen (z. B. Frankfurt/Stuttgart statt XETRA) und OTC-Werte werden
verworfen. Fällt der Screener für die USA aus, dient das NASDAQ-Trader-Verzeichnis als
Ersatz (dann ohne Börsenwert-Filter; der Liquiditätsfilter im Scanner greift weiterhin).

Aufruf:
    python -m aktienfinder.universe --out universe.csv [--regions us,europe,global] [--min-cap 2e9]
"""

import argparse
import io
import re
import sys

import pandas as pd
import requests

from .markets import MARKETS, market_cap_usd

MIN_MARKET_CAP_USD = 2_000_000_000   # ab 2 Mrd. $ = Mid Cap
COLUMNS = ["ticker", "name", "region", "source", "market_cap_usd"]

HEADERS = {"User-Agent": "Mozilla/5.0 (Aktienfinder; +https://github.com/dxrtex/Aktienfinder-)"}
NASDAQ_TRADED = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqtraded.txt"
OTC_EXCHANGES = {"PNK", "OQB", "OQX", "OEM", "OTC", "OBB"}

# Namensbestandteile, die keine Stammaktien sind
_NON_COMMON = re.compile(
    r"(?:\b(?:warrants?|units?|rights?|preferred|notes due|debentures|subordinated)\b|%)",
    re.IGNORECASE,
)


def _get(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text


def us_all() -> pd.DataFrame:
    """Ersatzquelle: alle Stammaktien an US-Börsen (ohne ETFs, Test-Symbole, Optionsscheine …)."""
    df = pd.read_csv(io.StringIO(_get(NASDAQ_TRADED)), sep="|", dtype=str)
    df = df[df["Symbol"].notna() & ~df["Symbol"].str.startswith("File Creation", na=False)]
    df = df[(df["ETF"] == "N") & (df["Test Issue"] == "N")]
    df = df[~df["Security Name"].fillna("").str.contains(_NON_COMMON)]
    df = df[~df["Symbol"].str.contains(r"[\$\^]", regex=True)]
    tickers = df["Symbol"].str.replace(".", "-", regex=False)
    return pd.DataFrame({"ticker": tickers, "name": df["Security Name"], "region": "us",
                         "source": "NASDAQ Trader", "market_cap_usd": None})[COLUMNS]


def _is_home_listing(symbol: str, quote: dict, suffixes: tuple) -> bool:
    if suffixes == ("",):   # USA: kein Suffix, keine OTC-Werte
        return "." not in symbol and quote.get("exchange", "") not in OTC_EXCHANGES
    return symbol.endswith(suffixes)


def screener(region: str, min_cap_usd: float = MIN_MARKET_CAP_USD, page_size: int = 250) -> pd.DataFrame:
    """Yahoo-Screener: je Land alle Aktien der Heimatbörse ab `min_cap_usd` Börsenwert.

    Die Treffer kommen nach Börsenwert absteigend sortiert; sobald ein Wert unter die
    Schwelle fällt, ist das Land abgeschlossen.
    """
    import yfinance as yf
    from yfinance import EquityQuery

    rows = []
    for m in (m for m in MARKETS if m.region == region):
        query = EquityQuery("eq", ["region", m.country])
        found, offset, done = 0, 0, False
        while not done:
            res = yf.screen(query, offset=offset, size=page_size, sortField="intradaymarketcap", sortAsc=False)
            quotes = res.get("quotes", [])
            for q in quotes:
                cap = market_cap_usd(q.get("marketCap"), q.get("currency"))
                if cap is not None and cap < min_cap_usd:
                    done = True
                    break
                sym = q.get("symbol", "")
                if (cap is not None and q.get("quoteType", "EQUITY") == "EQUITY"
                        and _is_home_listing(sym, q, m.suffixes)):
                    rows.append((sym, q.get("longName") or q.get("shortName", ""), region,
                                 f"Yahoo-Screener {m.country}", round(cap)))
                    found += 1
                    if found >= m.top_n:
                        done = True
                        break
            offset += len(quotes)
            if not quotes or offset >= res.get("total", 0):
                done = True
    return pd.DataFrame(rows, columns=COLUMNS)


def build(regions: list[str], min_cap_usd: float = MIN_MARKET_CAP_USD) -> tuple[pd.DataFrame, list[str]]:
    """Baut das Universum. Gibt (Tabelle, Protokollzeilen) zurück."""
    frames, log = [], []

    def add(label: str, fn) -> bool:
        try:
            df = fn()
            frames.append(df)
            log.append(f"{label}: {len(df)} Aktien")
            return len(df) > 0
        except Exception as exc:  # eine kaputte Quelle soll den Scan nicht verhindern
            log.append(f"{label}: FEHLER {type(exc).__name__}: {exc}")
            return False

    labels = {"us": "USA", "europe": "Europa", "global": "Rest der Welt"}
    for region in ("us", "europe", "global"):
        if region not in regions:
            continue
        ok = add(f"{labels[region]} (Yahoo-Screener, ab {min_cap_usd / 1e9:g} Mrd. $)",
                 lambda r=region: screener(r, min_cap_usd))
        if not ok and region == "us":
            add("USA Ersatz (NASDAQ Trader, ohne Börsenwert-Filter)", us_all)

    if not frames:
        return pd.DataFrame(columns=COLUMNS), log
    df = pd.concat(frames, ignore_index=True)
    df["ticker"] = df["ticker"].str.strip()
    df = df[df["ticker"].str.len() > 0].drop_duplicates("ticker", keep="first")
    log.append(f"GESAMT: {len(df)} Aktien")
    return df.reset_index(drop=True), log


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Ticker-Universum zusammenstellen")
    p.add_argument("--out", required=True)
    p.add_argument("--regions", default="us,europe,global")
    p.add_argument("--min-cap", type=float, default=MIN_MARKET_CAP_USD, help="Mindest-Börsenwert in US-Dollar")
    args = p.parse_args(argv)
    df, log = build([r.strip() for r in args.regions.split(",")], args.min_cap)
    print("\n".join(log))
    df.to_csv(args.out, index=False)
    with open(args.out + ".log", "w", encoding="utf-8") as f:
        f.write("\n".join(log) + "\n")
    return 0 if len(df) else 1


if __name__ == "__main__":
    sys.exit(main())
