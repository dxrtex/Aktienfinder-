"""Universum (2.1): alle Aktien ab 2 Mrd. USD Börsenwert in den USA und Europa.

Quelle ist der Yahoo-Finance-Screener je Land (Heimatbörse, Börsenwert-Filter in Landeswährung).
Ergebnis: `data/universe_us.csv` und `data/universe_eu.csv` – gepflegte Listen, die der Scanner
liest. Ausgeschlossen: ETFs/Fonds/Trusts, SPACs, Optionsscheine, Vorzugs-Duplikate,
Zweitlistings (USA nur NYSE/NASDAQ/NYSE American; Deutschland nur XETRA = .DE).

Aufruf:  python -m backend.universe
"""

import re
import sys

import pandas as pd

from .config import CONFIG, ROOT

COLUMNS = ["ticker", "name", "exchange", "country", "currency", "market_cap_usd", "sector"]
US_EXCHANGES = ["NMS", "NYQ", "NGM", "NCM", "ASE"]   # NASDAQ, NYSE, NYSE American
MAX_PAGES = 80

# Land → (Yahoo-Region, Suffixe der Heimatbörse, Währung, USD je Einheit)
EUROPE = {
    "de": ((".DE",), "EUR", 1.10), "gb": ((".L",), "GBP", 1.30), "fr": ((".PA",), "EUR", 1.10),
    "nl": ((".AS",), "EUR", 1.10), "ch": ((".SW",), "CHF", 1.15), "es": ((".MC",), "EUR", 1.10),
    "it": ((".MI",), "EUR", 1.10), "se": ((".ST",), "SEK", 0.095), "dk": ((".CO",), "DKK", 0.15),
    "no": ((".OL",), "NOK", 0.095), "fi": ((".HE",), "EUR", 1.10), "be": ((".BR",), "EUR", 1.10),
    "at": ((".VI",), "EUR", 1.10), "ie": ((".IR",), "EUR", 1.10), "pt": ((".LS",), "EUR", 1.10),
    "pl": ((".WA",), "PLN", 0.25), "gr": ((".AT",), "EUR", 1.10),
}
FX_USD = {"USD": 1.0, "EUR": 1.10, "GBP": 1.30, "GBp": 0.013, "GBX": 0.013, "CHF": 1.15, "SEK": 0.095,
          "DKK": 0.15, "NOK": 0.095, "PLN": 0.25}

_NOT_COMMON = re.compile(r"\b(?:trust|fund|etf|etn|warrants?|units?|rights?|acquisition corp\w*|"
                         r"acquisition company|capital acquisition|spac)\b", re.IGNORECASE)
_PREF = re.compile(r"\b(?:vz|vzo|vorzug\w*|pref\w*|preference)\b\.?", re.IGNORECASE)
_LEGAL = re.compile(r"\b(?:inc|incorporated|corp|corporation|co|company|plc|ltd|limited|ag|se|sa|nv|n\.v|"
                    r"asa|ab|oyj|spa|s\.p\.a|holdings?|group|the|class [a-z]|kgaa|& co)\b\.?", re.IGNORECASE)


def company_key(name: str) -> str:
    """Vereinfachter Firmenname – erkennt dieselbe Firma an mehreren Börsen und Vorzugsaktien."""
    key = _LEGAL.sub(" ", _PREF.sub(" ", str(name).lower()))
    return re.sub(r"[^a-z0-9]+", "", key)


def screen(country: str, suffixes: tuple, currency: str, min_cap_usd: float) -> list[dict]:
    import yfinance as yf
    from yfinance import EquityQuery

    parts = [EquityQuery("eq", ["region", country]),
             EquityQuery("gte", ["intradaymarketcap", min_cap_usd / FX_USD[currency]])]
    if country == "us":
        parts.append(EquityQuery("is-in", ["exchange", *US_EXCHANGES]))
    query = EquityQuery("and", parts)
    rows, offset = [], 0
    for _ in range(MAX_PAGES):
        try:
            res = yf.screen(query, offset=offset, size=250, sortField="intradaymarketcap", sortAsc=False)
        except Exception as exc:
            print(f"  Screener {country}: Fehler {exc!r}")
            break
        quotes = res.get("quotes", [])
        for q in quotes:
            sym, name = q.get("symbol", ""), q.get("longName") or q.get("shortName") or ""
            cur = q.get("currency") or currency
            cap = q.get("marketCap")
            cap_usd = cap * FX_USD.get(cur, FX_USD[currency]) if cap else None
            if cur in ("GBp", "GBX") and cap:          # London: Börsenwert in Pfund, Kurs in Pence
                cap_usd = cap * FX_USD["GBP"]
            home = ("." not in sym) if country == "us" else sym.endswith(suffixes)
            if (home and q.get("quoteType", "EQUITY") == "EQUITY" and cap_usd and cap_usd >= min_cap_usd
                    and not _NOT_COMMON.search(name)):
                rows.append({"ticker": sym, "name": name, "exchange": q.get("exchange", ""), "country": country,
                             "currency": cur, "market_cap_usd": round(cap_usd), "sector": q.get("sector") or ""})
        offset += len(quotes)
        if not quotes or (res.get("total") is not None and offset >= res["total"]):
            break
    return rows


def dedupe(df: pd.DataFrame) -> pd.DataFrame:
    """Gleiche Firma nur einmal: Stammaktie vor Vorzug, größter Börsenwert zuerst."""
    df = df.assign(_key=df["name"].map(company_key), _pref=df["name"].str.contains(_PREF))
    df = df.sort_values(["_pref", "market_cap_usd"], ascending=[True, False])
    keep = ~df["_key"].duplicated() | (df["_key"].str.len() <= 2)
    return df[keep].drop(columns=["_key", "_pref"]).sort_values("market_cap_usd", ascending=False)


def build() -> dict[str, pd.DataFrame]:
    min_cap = CONFIG.universe.min_market_cap_usd
    us = pd.DataFrame(screen("us", ("",), "USD", min_cap), columns=COLUMNS)
    eu_rows = []
    for country, (suffixes, cur, _) in EUROPE.items():
        rows = screen(country, suffixes, cur, min_cap)
        print(f"  {country}: {len(rows)} Aktien")
        eu_rows += rows
    eu = pd.DataFrame(eu_rows, columns=COLUMNS)
    us, eu = dedupe(us.drop_duplicates("ticker")), dedupe(eu.drop_duplicates("ticker"))
    us_keys = set(us["name"].map(company_key))
    eu = eu[~eu["name"].map(company_key).isin(us_keys - {""})]   # Doppel-Listing USA/Europa: USA zählt
    return {"us": us, "eu": eu}


def load() -> pd.DataFrame:
    """Beide Listen für den Scanner (Region us/europe)."""
    frames = []
    for region, name in (("us", "universe_us.csv"), ("europe", "universe_eu.csv")):
        path = ROOT / "data" / name
        if path.exists():
            frames.append(pd.read_csv(path, dtype={"ticker": str}).assign(region=region))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=COLUMNS + ["region"])


def main() -> int:
    lists = build()
    (ROOT / "data").mkdir(exist_ok=True)
    for region, df in lists.items():
        df.to_csv(ROOT / "data" / f"universe_{region}.csv", index=False)
        print(f"{region.upper()}: {len(df)} Aktien ab 2 Mrd. USD")
    return 0 if all(len(d) for d in lists.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
