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

from .markets import FX_USD, MARKETS, market_cap_usd

MIN_MARKET_CAP_USD = 2_000_000_000   # ab 2 Mrd. $ = Mid Cap
COLUMNS = ["ticker", "name", "region", "source", "market_cap_usd"]

HEADERS = {"User-Agent": "Mozilla/5.0 (Aktienfinder; +https://github.com/dxrtex/Aktienfinder-)"}
NASDAQ_TRADED = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqtraded.txt"
OTC_EXCHANGES = {"PNK", "OQB", "OQX", "OEM", "OTC", "OBB"}
US_EXCHANGES = ["NMS", "NYQ", "NGM", "NCM", "ASE", "BTS"]   # NASDAQ, NYSE, NYSE American, Cboe
MAX_PAGES = 80

# Namensbestandteile, die keine Stammaktien sind
_NON_COMMON = re.compile(
    r"(?:\b(?:warrants?|units?|rights?|preferred|notes due|debentures|subordinated)\b|%)",
    re.IGNORECASE,
)


# Fonds/Trusts statt Unternehmen (z. B. "Sprott Physical Uranium Trust")
_NOT_A_COMPANY = re.compile(r"\b(?:trust|fund|etf|etn)\b", re.IGNORECASE)
_LEGAL_FORMS = re.compile(
    r"\b(?:inc|incorporated|corp|corporation|co|company|plc|ltd|limited|ag|se|sa|nv|n\.v|asa|ab|"
    r"oyj|spa|s\.p\.a|holdings?|group|the|class [a-z])\b\.?", re.IGNORECASE)


def company_key(name: str) -> str:
    """Vereinfachter Firmenname, um dieselbe Firma an mehreren Börsen zu erkennen."""
    key = _LEGAL_FORMS.sub(" ", str(name).lower())
    return re.sub(r"[^a-z0-9]+", "", key)


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

    Yahoo filtert den Börsenwert in der Landeswährung; die Schwelle wird deshalb je Land
    umgerechnet. Zusätzlich wird jeder Treffer einzeln in US-Dollar geprüft, weil an
    manchen Börsen auch Auslandswerte in Fremdwährung notieren (z. B. Toyota in London).
    """
    import yfinance as yf
    from yfinance import EquityQuery

    rows = []
    for m in (m for m in MARKETS if m.region == region):
        parts = [EquityQuery("eq", ["region", m.country]),
                 EquityQuery("gte", ["intradaymarketcap", min_cap_usd / FX_USD[m.currency]])]
        if m.country == "us":
            parts.append(EquityQuery("is-in", ["exchange", *US_EXCHANGES]))
        query = EquityQuery("and", parts)
        offset = 0
        for _ in range(MAX_PAGES):
            try:   # ein Land, das Yahoo (zeitweise) nicht liefert, soll die anderen nicht stoppen
                res = yf.screen(query, offset=offset, size=page_size, sortField="intradaymarketcap", sortAsc=False)
            except Exception as exc:
                print(f"  Screener {m.country}: Fehler {exc!r}")
                break
            quotes = res.get("quotes", [])
            for q in quotes:
                cap = market_cap_usd(q.get("marketCap"), q.get("currency"))
                sym = q.get("symbol", "")
                name = q.get("longName") or q.get("shortName", "")
                if (cap is not None and cap >= min_cap_usd and q.get("quoteType", "EQUITY") == "EQUITY"
                        and _is_home_listing(sym, q, m.suffixes) and not _NOT_A_COMPANY.search(name)):
                    rows.append((sym, name, region, f"Yahoo-Screener {m.country}", round(cap)))
            offset += len(quotes)
            total = res.get("total")
            if not quotes or (total is not None and offset >= total):
                break
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
    # Dieselbe Firma an mehreren Börsen (z. B. Lundin Mining in Stockholm und Toronto,
    # Alphabet als kanadisches Zertifikat): nur der erste Eintrag (USA > Europa > Rest) bleibt.
    keys = df["name"].map(company_key)
    dup = keys.duplicated(keep="first") & (keys.str.len() > 2)
    if dup.any():
        log.append(f"Doppelte Firmen entfernt: {int(dup.sum())}")
    df = df[~dup]
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
