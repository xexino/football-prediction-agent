"""Probability calibration for the 1X2 ensemble.

Power (temperature-like) calibration: p_k' = p_k^t / sum_j p_j^t. One parameter, so it needs little
data and cannot overfit much; t > 1 sharpens (fixes under-confidence), t < 1 softens.
Raw probabilities are always stored alongside calibrated ones.
"""
from __future__ import annotations

import numpy as np
from scipy.optimize import minimize_scalar


def apply_power(p, t: float):
    a = np.clip(np.asarray(p, float), 1e-9, 1) ** t
    return list(a / a.sum())


def fit_power(rows) -> float:
    """rows: [(probs[3], outcome_index)] — minimise log loss over t in [0.5, 2]."""
    P = np.clip(np.array([r[0] for r in rows], float), 1e-9, 1)
    y = np.array([r[1] for r in rows])

    def nll(t):
        a = P ** t
        a = a / a.sum(axis=1, keepdims=True)
        return -np.mean(np.log(a[np.arange(len(y)), y]))

    return float(minimize_scalar(nll, bounds=(0.5, 2.0), method="bounded").x)
