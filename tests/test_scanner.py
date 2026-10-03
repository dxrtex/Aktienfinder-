import numpy as np
import pandas as pd

from aktienfinder import scanner


def _fake_download_dict(tickers, period):
    rng = np.random.default_rng(3)
    idx = pd.bdate_range("2024-10-01", periods=500)
    out = {}
    for t in tickers:
        c = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, 500)))
        out[t] = pd.DataFrame({"Open": c, "High": c * 1.01, "Low": c * 0.99, "Close": c,
                               "Volume": 1e6}, index=idx)
    out["PENNY"] = out[tickers[0]].assign(Close=0.5)
    return out


def _fake_download(tickers, period, log=print, **kw):
    yield from _fake_download_dict(tickers, period).items()


def _no_targets(tickers, log=print):
    return {t: {"target_price": 1.0, "upside_pct": 50.0, "analysts": 3} for t in tickers}


def test_scan_filters_pennystocks_and_sorts(monkeypatch, capsys):
    monkeypatch.setattr(scanner, "download", _fake_download)
    monkeypatch.setattr(scanner, "analyst_targets", _no_targets)
    rows = scanner.scan([f"T{i}" for i in range(30)], include_all=True)
    assert rows and all(r["ticker"] != "PENNY" for r in rows)
    keys = [(r["passed"], r["score"]) for r in rows]
    assert keys == sorted(keys, reverse=True)
    scanner._print_table(rows)
    assert "Ticker" in capsys.readouterr().out


def test_debug_report_lists_signal_dates():
    df = _fake_download_dict(["X"], "2y")["X"]
    text = scanner.debug_report("X", df)
    assert "MBI grünes X" in text and "MACD rot+schrumpfend" in text


def test_main_writes_json(monkeypatch, tmp_path):
    import json
    monkeypatch.setattr(scanner, "download", _fake_download)
    monkeypatch.setattr(scanner, "analyst_targets", _no_targets)
    uni = tmp_path / "u.csv"
    uni.write_text("ticker,name,region,source\nAAA,Alpha AG,europe,x\nBBB,Beta,us,x\n")
    (tmp_path / "u.csv.log").write_text("Quelle: 2 Aktien\n")
    out = tmp_path / "data" / "results.json"
    assert scanner.main(["--universe", str(uni), "--out", str(out), "--all", "--quiet"]) == 0
    data = json.loads(out.read_text())
    assert data["universe_log"] == ["Quelle: 2 Aktien"]
    assert data["stats"]["universe"] == 2
    names = {r["ticker"]: r["name"] for r in data["results"]}
    assert names.get("AAA") == "Alpha AG"


def test_report_runs_on_scan_output(monkeypatch, tmp_path):
    from aktienfinder import report
    monkeypatch.setattr(scanner, "download", _fake_download)
    monkeypatch.setattr(scanner, "analyst_targets", _no_targets)
    uni = tmp_path / "u.csv"
    rows = "\n".join(f"T{i},Firma {i},us,x,5e9" for i in range(40))
    uni.write_text("ticker,name,region,source,market_cap_usd\n" + rows + "\n")
    out = tmp_path / "r.json"
    scanner.main(["--universe", str(uni), "--out", str(out), "--quiet"])
    assert report.main(["--universe", str(uni), "--results", str(out), "--refs", "T1,NOPE"]) == 0


def test_chart_data_for_website():
    df = _fake_download_dict(["X"], "2y")["X"]
    data = scanner.chart_data(df)
    assert len(data["spark"]) == scanner.CHART_BARS
    assert data["fib_high"] is None or data["fib_high"] > data["fib_low"]


def test_watchlist_always_included(monkeypatch, tmp_path):
    import json
    monkeypatch.setattr(scanner, "download", _fake_download)
    monkeypatch.setattr(scanner, "analyst_targets", _no_targets)
    wl = tmp_path / "wl.json"
    wl.write_text(json.dumps({"_hinweis": "x", "Pennystock AG": ["PENNY"], "Firma 1": ["T1"]}))
    watch = scanner.load_watchlist(str(wl))
    assert watch == {"PENNY": "Pennystock AG", "T1": "Firma 1"}
    rows = scanner.scan(["T1", "T2", "T3"], watchlist=watch)
    by = {r["ticker"]: r for r in rows}
    # Watchlist-Aktien sind immer dabei – auch ohne Setup und trotz Liquiditätsfilter
    assert by["T1"]["in_watchlist"] and by["PENNY"]["in_watchlist"]
    assert by["PENNY"]["name"] == "Pennystock AG"
    assert all(r["passed"] or r["in_watchlist"] for r in rows)


def test_is_top_requires_all_criteria():
    from aktienfinder.scanner import is_top
    r = {"passed": True, "core_met": ["rueckgang", "fibonacci", "divergenz", "macd_jetzt", "mbi_x"], "upside_pct": 50, "crv": 2.5,
         "pullback_drawdown_pct": 30, "rise_from_low_pct": 8, "green_x_count": 2, "earnings_date": None,
         "rel_strength": 0.05}
    assert is_top(r)
    assert is_top({**r, "upside_pct": 31})               # Kursziel ab +30 %
    assert not is_top({**r, "upside_pct": 25})
    assert not is_top({**r, "core_met": ["rueckgang", "fibonacci", "divergenz", "mbi_x"]})  # MACD heute nicht rot/schrumpfend
    assert is_top({**r, "rel_strength": -0.1})           # Marktvergleich kein Kriterium
    assert is_top({**r, "rise_from_low_pct": 1})          # Abstand zum Tief egal
    assert is_top({**r, "green_x_count": 1})              # 1 grünes X genügt
    assert not is_top({**r, "green_x_count": 0})
    assert not is_top({**r, "passed": False})
    soon = (__import__("pandas").Timestamp.now() + __import__("pandas").Timedelta(days=4)).date().isoformat()
    assert is_top({**r, "earnings_date": soon})           # Quartalszahlen sind kein Kriterium
