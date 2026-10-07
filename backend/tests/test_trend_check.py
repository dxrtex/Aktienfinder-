import numpy as np
import pandas as pd

from backend import trend_study as ts


def _df(seed=1, n=600):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(.001, .02, n)))
    idx = pd.bdate_range("2024-01-01", periods=n)
    return pd.DataFrame({"Open": c, "High": c * 1.01, "Low": c * .99, "Close": c, "Volume": rng.uniform(1e6, 3e6, n)}, index=idx)


def test_predict_uses_saved_model():
    out = ts.predict(_df(), True, 18.0)
    assert out is not None and 0 <= out["p"] <= 1
    assert out["fib50"] < out["hi"]
    assert len(out["pro"]) <= 3 and len(out["con"]) <= 3


def test_features_are_clipped():
    x = ts._ind(_df(2))
    i = len(x["c"]) - 1
    ri, R, L = ts.leg_at(x["h"], x["l"], i)
    f = ts.feats_at(x, i, ri, R, L, False, 99.0)
    for k, (lo, hi) in ts.CLIP.items():
        assert lo <= f[k] <= hi
