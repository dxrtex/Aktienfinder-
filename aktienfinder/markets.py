"""Märkte: Heimatbörse (Yahoo-Suffix), Region, grobe Umrechnung in US-Dollar, Anzahl Aktien.

Die Dollar-Kurse sind bewusst grob und fest hinterlegt – sie dienen nur dazu, den
Liquiditätsfilter (Mindestkurs, Mindest-Tagesumsatz) für alle Börsen vergleichbar zu machen.
Achtung: London (.L), Johannesburg (.JO) und Tel Aviv (.TA) notieren in Pence/Cent/Agorot.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Market:
    country: str          # Yahoo-Regionscode
    suffixes: tuple       # Yahoo-Suffixe der Heimatbörse(n)
    region: str           # "europe" oder "global"
    usd: float            # US-Dollar je Kurseinheit (London: Pence)
    currency: str         # Währung, in der Yahoo den Börsenwert des Landes angibt


MARKETS = [
    # USA (Yahoo-Ticker ohne Suffix)
    Market("us", ("",), "us", 1.0, "USD"),
    # Europa
    Market("de", (".DE",), "europe", 1.10, "EUR"),
    Market("gb", (".L",), "europe", 0.0130, "GBP"),
    Market("fr", (".PA",), "europe", 1.10, "EUR"),
    Market("nl", (".AS",), "europe", 1.10, "EUR"),
    Market("ch", (".SW",), "europe", 1.15, "CHF"),
    Market("es", (".MC",), "europe", 1.10, "EUR"),
    Market("it", (".MI",), "europe", 1.10, "EUR"),
    Market("se", (".ST",), "europe", 0.095, "SEK"),
    Market("dk", (".CO",), "europe", 0.15, "DKK"),
    Market("no", (".OL",), "europe", 0.095, "NOK"),
    Market("fi", (".HE",), "europe", 1.10, "EUR"),
    Market("be", (".BR",), "europe", 1.10, "EUR"),
    Market("at", (".VI",), "europe", 1.10, "EUR"),
    Market("ie", (".IR",), "europe", 1.10, "EUR"),
    Market("pt", (".LS",), "europe", 1.10, "EUR"),
    Market("pl", (".WA",), "europe", 0.25, "PLN"),
    # Rest der Welt
    Market("jp", (".T",), "global", 0.0068, "JPY"),
    Market("hk", (".HK",), "global", 0.13, "HKD"),
    Market("ca", (".TO",), "global", 0.73, "CAD"),
    Market("au", (".AX",), "global", 0.65, "AUD"),
    Market("in", (".NS",), "global", 0.012, "INR"),
    Market("kr", (".KS", ".KQ"), "global", 0.00073, "KRW"),
    Market("tw", (".TW", ".TWO"), "global", 0.031, "TWD"),
    Market("sg", (".SI",), "global", 0.74, "SGD"),
    Market("br", (".SA",), "global", 0.18, "BRL"),
    Market("mx", (".MX",), "global", 0.055, "MXN"),
    Market("za", (".JO",), "global", 0.00055, "ZAR"),
    Market("il", (".TA",), "global", 0.0027, "ILS"),
    Market("nz", (".NZ",), "global", 0.60, "NZD"),
]

_BY_SUFFIX = {s: m for m in MARKETS for s in m.suffixes if s}
KNOWN_SUFFIXES = set(_BY_SUFFIX)


def market_for(ticker: str) -> Market | None:
    """Markt anhand des Yahoo-Suffixes; None = US-Börse (kein Suffix) oder unbekannt."""
    if "." not in ticker:
        return None
    return _BY_SUFFIX.get("." + ticker.rsplit(".", 1)[1])


# US-Dollar je Währungseinheit (grob, nur für Schwellenwerte). Yahoo nennt bei manchen
# Börsen die Kurswährung in Untereinheiten (GBp, ZAc, ILA); der Börsenwert ist dann in der
# Hauptwährung angegeben.
FX_USD = {
    "USD": 1.0, "EUR": 1.10, "GBP": 1.30, "CHF": 1.15, "SEK": 0.095, "DKK": 0.15, "NOK": 0.095,
    "PLN": 0.25, "JPY": 0.0068, "HKD": 0.13, "CAD": 0.73, "AUD": 0.65, "INR": 0.012,
    "KRW": 0.00073, "TWD": 0.031, "SGD": 0.74, "BRL": 0.18, "MXN": 0.055, "ZAR": 0.055,
    "ILS": 0.27, "NZD": 0.60, "CNY": 0.14,
}
_MINOR_UNITS = {"GBp": "GBP", "GBX": "GBP", "ZAc": "ZAR", "ZAC": "ZAR", "ILA": "ILS"}


def market_cap_usd(market_cap: float | None, currency: str | None) -> float | None:
    """Börsenwert aus dem Yahoo-Screener in US-Dollar; None, wenn unbekannt."""
    if not market_cap:
        return None
    cur = _MINOR_UNITS.get(currency or "USD", currency or "USD")
    fx = FX_USD.get(cur)
    return market_cap * fx if fx else None


def usd_factor(ticker: str) -> float:
    m = market_for(ticker)
    return m.usd if m else 1.0


def region_of(ticker: str) -> str:
    if "." not in ticker:
        return "us"
    m = market_for(ticker)
    return m.region if m else "global"
