import numpy as np
import pandas as pd

from aktienfinder import scanner


def _fake_download(tickers, period, batch_size=100):
    rng = np.random.default_rng(3)
    idx = pd.bdate_range("2024-10-01", periods=500)
    out = {}
    for t in tickers:
        c = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, 500)))
        out[t] = pd.DataFrame({"Open": c, "High": c * 1.01, "Low": c * 0.99, "Close": c,
                               "Volume": 1e6}, index=idx)
    out["PENNY"] = out[tickers[0]].assign(Close=0.5)
    return out


def test_scan_filters_pennystocks_and_sorts(monkeypatch, capsys):
    monkeypatch.setattr(scanner, "download", _fake_download)
    rows = scanner.scan([f"T{i}" for i in range(30)], include_all=True)
    assert rows and all(r["ticker"] != "PENNY" for r in rows)
    keys = [(r["passed"], r["score"]) for r in rows]
    assert keys == sorted(keys, reverse=True)
    scanner._print_table(rows)
    assert "Ticker" in capsys.readouterr().out


def test_debug_report_lists_signal_dates():
    df = _fake_download(["X"], "2y")["X"]
    text = scanner.debug_report("X", df)
    assert "MBI grünes X" in text and "MACD rot+schrumpfend" in text
