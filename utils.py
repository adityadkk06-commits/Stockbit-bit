"""
utils.py — Shared numeric helpers used by screener.py, multi_screener.py, top_gainer.py.
Import from here instead of duplicating these functions in every module.
"""

import numpy as np


def _f(val, fb: float = 0.0) -> float:
    """Safely cast val to float, returning fb on NaN / Inf / error."""
    try:
        v = float(val)
        return fb if (np.isnan(v) or np.isinf(v)) else v
    except Exception:
        return fb


def _ratio(num, den, fb: float = 0.0) -> float:
    """Safe division: num / den, returning fb when den == 0."""
    n, d = _f(num), _f(den)
    return fb if d == 0 else n / d
