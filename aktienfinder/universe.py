"""Stellt die Liste der zu scannenden Aktien zusammen (USA, Europa, global).

Quellen (alle fehlertolerant – fällt eine aus, läuft der Rest weiter):
- USA komplett: Symbolverzeichnis von NASDAQ Trader (alle an US-Börsen gehandelten Aktien)
- Europa/global: Indexlisten von Wikipedia (DAX, FTSE 100, CAC 40, Nikkei 225 …)
- Europa/global breit: Yahoo-Finance-Screener nach Land und Mindest-Börsenwert

Aufruf:
    python -m aktienfinder.universe --out universe.csv [--regions us,europe,global]
"""

import argparse
import io
import re
import sys
from dataclasses import dataclass

import pandas as pd
import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (Aktienfinder; +https://github.com/dxrtex/Aktienfinder-)"}

NASDAQ_TRADED = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqtraded.txt"

# Namensbestandteile, die keine Stammaktien sind
_NON_COMMON = re.compile(
    r"(?:\b(?:warrants?|units?|rights?|preferred|notes due|debentures|subordinated)\b|%)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class IndexSource:
    name: str
    url: str
    region: str
    suffix: str            # Yahoo-Börsenkürzel, z. B. ".DE"
    columns: tuple = ("Ticker", "Symbol", "Code", "EPIC", "Ticker symbol", "Stock code")
    dot_to_dash: bool = False   # z. B. FTSE "BT.A" → "BT-A.L"
    zero_pad: int = 0           # Hongkong: "5" → "0005"


INDEX_SOURCES = [
    IndexSource("DAX", "https://en.wikipedia.org/wiki/DAX", "europe", ".DE"),
    IndexSource("MDAX", "https://en.wikipedia.org/wiki/MDAX", "europe", ".DE"),
    IndexSource("SDAX", "https://en.wikipedia.org/wiki/SDAX", "europe", ".DE"),
    IndexSource("TecDAX", "https://en.wikipedia.org/wiki/TecDAX", "europe", ".DE"),
    IndexSource("FTSE 100", "https://en.wikipedia.org/wiki/FTSE_100_Index", "europe", ".L", dot_to_dash=True),
    IndexSource("FTSE 250", "https://en.wikipedia.org/wiki/FTSE_250_Index", "europe", ".L", dot_to_dash=True),
    IndexSource("CAC 40", "https://en.wikipedia.org/wiki/CAC_40", "europe", ".PA"),
    IndexSource("AEX", "https://en.wikipedia.org/wiki/AEX_index", "europe", ".AS"),
    IndexSource("SMI", "https://en.wikipedia.org/wiki/Swiss_Market_Index", "europe", ".SW"),
    IndexSource("IBEX 35", "https://en.wikipedia.org/wiki/IBEX_35", "europe", ".MC"),
    IndexSource("FTSE MIB", "https://en.wikipedia.org/wiki/FTSE_MIB", "europe", ".MI"),
    IndexSource("OMX Stockholm 30", "https://en.wikipedia.org/wiki/OMX_Stockholm_30", "europe", ".ST", dot_to_dash=True),
    IndexSource("EURO STOXX 50", "https://en.wikipedia.org/wiki/Euro_Stoxx_50", "europe", ""),
    IndexSource("Nikkei 225", "https://en.wikipedia.org/wiki/Nikkei_225", "global", ".T"),
    IndexSource("Hang Seng", "https://en.wikipedia.org/wiki/Hang_Seng_Index", "global", ".HK", zero_pad=4),
    IndexSource("S&P/TSX 60", "https://en.wikipedia.org/wiki/S%26P/TSX_60", "global", ".TO", dot_to_dash=True),
    IndexSource("S&P/ASX 200", "https://en.wikipedia.org/wiki/S%26P/ASX_200", "global", ".AX"),
    IndexSource("NIFTY 50", "https://en.wikipedia.org/wiki/NIFTY_50", "global", ".NS"),
]

# Yahoo-Screener: Länder je Region (Yahoo-Regionscodes)
SCREENER_REGIONS = {
    "europe": ["de", "gb", "fr", "nl", "ch", "es", "it", "se", "dk", "no", "fi", "be", "at", "ie", "pt", "pl"],
    "global": ["jp", "hk", "ca", "au", "in", "kr", "tw", "sg", "br", "mx", "za", "il", "nz", "cn"],
}
SCREENER_MIN_MARKET_CAP = 300_000_000


def _get(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text


def us_all() -> pd.DataFrame:
    """Alle Stammaktien an US-Börsen (ohne ETFs, Test-Symbole, Optionsscheine, Vorzugsaktien)."""
    df = pd.read_csv(io.StringIO(_get(NASDAQ_TRADED)), sep="|", dtype=str)
    df = df[df["Symbol"].notna() & ~df["Symbol"].str.startswith("File Creation", na=False)]
    df = df[(df["ETF"] == "N") & (df["Test Issue"] == "N")]
    df = df[~df["Security Name"].fillna("").str.contains(_NON_COMMON)]
    df = df[~df["Symbol"].str.contains(r"[\$\^]", regex=True)]
    tickers = df["Symbol"].str.replace(".", "-", regex=False)
    return pd.DataFrame({"ticker": tickers, "name": df["Security Name"], "region": "us",
                         "source": "NASDAQ Trader"})


def _normalize(raw, src: IndexSource) -> str | None:
    """Wikipedia-Eintrag → Yahoo-Ticker, z. B. "XETRA: ADS" → "ADS.DE", "BT.A" → "BT-A.L"."""
    t = re.sub(r"\[.*?\]", "", str(raw)).strip().upper()   # Fußnoten entfernen
    if ":" in t:
        t = t.split(":")[-1].strip()                      # Börsenpräfix entfernen
    if not t or t == "NAN" or " " in t:
        return None
    if src.suffix and t.endswith(src.suffix):
        return t
    if not src.suffix:
        # gemischte Liste (z. B. EURO STOXX 50): nur Einträge mit Yahoo-Suffix verwendbar
        return t if re.search(r"\.[A-Z]{1,2}$", t) else None
    if src.zero_pad and t.isdigit():
        t = t.zfill(src.zero_pad)
    if src.dot_to_dash:
        t = t.replace(".", "-")
    return t + src.suffix


def index_members(src: IndexSource) -> pd.DataFrame:
    """Liest die Bestandteile eines Index aus der passenden Wikipedia-Tabelle."""
    tables = pd.read_html(io.StringIO(_get(src.url)))
    best = None
    for table in tables:
        cols = {str(c).strip(): c for c in (table.columns.get_level_values(-1)
                                             if isinstance(table.columns, pd.MultiIndex) else table.columns)}
        col = next((cols[c] for c in src.columns if c in cols), None)
        if col is None or len(table) < 10:
            continue
        if isinstance(table.columns, pd.MultiIndex):
            table.columns = table.columns.get_level_values(-1)
        if best is None or len(table) > len(best[0]):
            best = (table, col)
    if best is None:
        raise ValueError("keine passende Tabelle gefunden")
    table, col = best
    name_col = next((c for c in table.columns if str(c).strip() in ("Company", "Name", "Constituent")), None)
    rows = []
    for _, row in table.iterrows():
        t = _normalize(row[col], src)
        if t:
            rows.append((t, row[name_col] if name_col is not None else "", src.region, src.name))
    return pd.DataFrame(rows, columns=["ticker", "name", "region", "source"])


def screener(region: str) -> pd.DataFrame:
    """Yahoo-Screener: alle Aktien der Länder einer Region ab Mindest-Börsenwert."""
    import yfinance as yf
    from yfinance import EquityQuery

    rows = []
    for country in SCREENER_REGIONS[region]:
        query = EquityQuery("and", [
            EquityQuery("eq", ["region", country]),
            EquityQuery("gte", ["intradaymarketcap", SCREENER_MIN_MARKET_CAP]),
        ])
        offset = 0
        while True:
            res = yf.screen(query, offset=offset, size=250, sortField="intradaymarketcap", sortAsc=False)
            quotes = res.get("quotes", [])
            for q in quotes:
                rows.append((q["symbol"], q.get("longName") or q.get("shortName", ""), region,
                             f"Yahoo-Screener {country}"))
            offset += len(quotes)
            if not quotes or offset >= res.get("total", 0) or offset >= 5000:
                break
    return pd.DataFrame(rows, columns=["ticker", "name", "region", "source"])


def build(regions: list[str]) -> tuple[pd.DataFrame, list[str]]:
    """Baut das Universum. Gibt (Tabelle, Protokollzeilen) zurück."""
    frames, log = [], []

    def add(label: str, fn):
        try:
            df = fn()
            frames.append(df)
            log.append(f"{label}: {len(df)} Aktien")
        except Exception as exc:  # eine kaputte Quelle soll den Scan nicht verhindern
            log.append(f"{label}: FEHLER {type(exc).__name__}: {exc}")

    if "us" in regions:
        add("USA (NASDAQ Trader)", us_all)
    for src in INDEX_SOURCES:
        if src.region in regions:
            add(src.name, lambda s=src: index_members(s))
    for region in ("europe", "global"):
        if region in regions:
            add(f"Yahoo-Screener {region}", lambda r=region: screener(r))

    if not frames:
        return pd.DataFrame(columns=["ticker", "name", "region", "source"]), log
    df = pd.concat(frames, ignore_index=True)
    df["ticker"] = df["ticker"].str.strip()
    df = df[df["ticker"].str.len() > 0].drop_duplicates("ticker", keep="first")
    log.append(f"GESAMT: {len(df)} Aktien")
    return df.reset_index(drop=True), log


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Ticker-Universum zusammenstellen")
    p.add_argument("--out", required=True)
    p.add_argument("--regions", default="us,europe,global")
    args = p.parse_args(argv)
    df, log = build([r.strip() for r in args.regions.split(",")])
    print("\n".join(log))
    df.to_csv(args.out, index=False)
    with open(args.out + ".log", "w", encoding="utf-8") as f:
        f.write("\n".join(log) + "\n")
    return 0 if len(df) else 1


if __name__ == "__main__":
    sys.exit(main())
