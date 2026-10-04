"""Universum (2.1): alle Aktien ab 2 Mrd. USD Börsenwert in Nordamerika, Westeuropa und Asien/Pazifik.

Quelle ist der Yahoo-Finance-Screener je Land (Heimatbörse, Börsenwert-Filter in Landeswährung).
Ergebnis: `data/universe_us.csv`, `data/universe_eu.csv`, `data/universe_asia.csv` – gepflegte Listen, die der Scanner
liest. Ausgeschlossen: ETFs/Fonds/Trusts, SPACs, Optionsscheine, Vorzugs-Duplikate,
Zweitlistings (USA nur NYSE/NASDAQ/NYSE American; Deutschland nur XETRA = .DE).

Aufruf:  python -m backend.universe
"""

import re
import sys

import pandas as pd

from .config import CONFIG, ROOT

COLUMNS = ["ticker", "name", "exchange", "country", "currency", "market_cap_usd", "sector",
           "earnings_date", "earnings_estimate", "ex_dividend_date", "dividend_date", "dividend_rate"]
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
# Asien/Pazifik
ASIA = {
    "jp": ((".T",), "JPY", 0.0068), "cn": ((".SS", ".SZ"), "CNY", 0.14), "hk": ((".HK",), "HKD", 0.13),
    "kr": ((".KS", ".KQ"), "KRW", 0.00073), "tw": ((".TW", ".TWO"), "TWD", 0.031), "in": ((".NS",), "INR", 0.012),
    "sg": ((".SI",), "SGD", 0.74), "au": ((".AX",), "AUD", 0.65), "nz": ((".NZ",), "NZD", 0.60),
    "th": ((".BK",), "THB", 0.029), "id": ((".JK",), "IDR", 0.000062), "my": ((".KL",), "MYR", 0.22),
    "ph": ((".PS",), "PHP", 0.017),
}
FX_USD = {"USD": 1.0, "EUR": 1.10, "GBP": 1.30, "GBp": 0.013, "GBX": 0.013, "CHF": 1.15, "SEK": 0.095,
          "DKK": 0.15, "NOK": 0.095, "PLN": 0.25, "CAD": 0.73, "JPY": 0.0068, "CNY": 0.14, "HKD": 0.13,
          "KRW": 0.00073, "TWD": 0.031, "INR": 0.012, "SGD": 0.74, "AUD": 0.65, "NZD": 0.60, "THB": 0.029,
          "IDR": 0.000062, "MYR": 0.22, "PHP": 0.017}

_NOT_COMMON = re.compile(r"\b(?:trust|fund|etf|etn|warrants?|units?|rights?|acquisition corp\w*|"
                         r"acquisition company|capital acquisition|spac)\b", re.IGNORECASE)
_PREF = re.compile(r"\b(?:vz|vzo|vorzug\w*|pref\w*|preference)\b\.?", re.IGNORECASE)
_LEGAL = re.compile(r"\b(?:inc|incorporated|corp|corporation|co|company|plc|ltd|limited|ag|se|sa|nv|n\.v|"
                    r"asa|ab|oyj|spa|s\.p\.a|holdings?|group|the|class [a-z]|kgaa|& co)\b\.?", re.IGNORECASE)


def company_key(name: str) -> str:
    """Vereinfachter Firmenname – erkennt dieselbe Firma an mehreren Börsen und Vorzugsaktien."""
    key = _LEGAL.sub(" ", _PREF.sub(" ", str(name).lower()))
    return re.sub(r"[^a-z0-9]+", "", key)


def quote_dates(q: dict) -> dict:
    """Termine aus der Screener-Antwort (zuverlässiger als die Einzelabfrage .info)."""
    from .data_provider import _future_date, _next_earnings
    return {"earnings_date": _next_earnings(q), "earnings_estimate": bool(q.get("isEarningsDateEstimate")),
            "ex_dividend_date": _future_date(q.get("exDividendDate")), "dividend_date": _future_date(q.get("dividendDate")),
            "dividend_rate": q.get("dividendRate") or q.get("trailingAnnualDividendRate")}


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
                             "currency": cur, "market_cap_usd": round(cap_usd), "sector": q.get("sector") or "",
                             **quote_dates(q)})
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


def _region(markets: dict, min_cap: float) -> pd.DataFrame:
    rows = []
    for country, (suffixes, cur, _) in markets.items():
        found = screen(country, suffixes, cur, min_cap)
        print(f"  {country}: {len(found)} Aktien")
        rows += found
    return dedupe(pd.DataFrame(rows, columns=COLUMNS).drop_duplicates("ticker"))


def build() -> dict[str, pd.DataFrame]:
    """Nordamerika (USA + Kanada), Westeuropa, Asien/Pazifik. Doppel-Listings zählen nur einmal:
    USA vor Kanada vor Europa vor Asien."""
    min_cap = CONFIG.universe.min_market_cap_usd
    us = dedupe(pd.DataFrame(screen("us", ("",), "USD", min_cap), columns=COLUMNS).drop_duplicates("ticker"))
    print(f"  us: {len(us)} Aktien")
    ca = _region({"ca": ((".TO",), "CAD", 0.73)}, min_cap)
    eu = _region(EUROPE, min_cap)
    asia = _region(ASIA, min_cap)
    seen = set(us["name"].map(company_key)) - {""}
    out = {"us": us}
    for name, df in (("ca", ca), ("eu", eu), ("asia", asia)):
        keys = df["name"].map(company_key)
        out[name] = df[~keys.isin(seen)]
        seen |= set(keys) - {""}
    out["us"] = pd.concat([out["us"], out.pop("ca")], ignore_index=True)   # Nordamerika in einer Liste
    return out


REGION_FILES = (("us", "universe_us.csv"), ("europe", "universe_eu.csv"), ("asia", "universe_asia.csv"))


def load() -> pd.DataFrame:
    """Alle Listen für den Scanner (Region us = Nordamerika, europe, asia = Asien/Pazifik)."""
    frames = []
    for region, name in REGION_FILES:
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
