"""Independent three-tank + Nash oracle used for Tank parity fixtures.

Deliberately mirrors the product equations without importing ``engine.py``, so
residuals catch accidental structural drift.
"""

from __future__ import annotations

from typing import Mapping

import numpy as np

from .contracts import NASH_N_MAX, NASH_N_MIN


def _nash_length(n_value: float) -> int:
    n = int(round(float(n_value)))
    return max(NASH_N_MIN, min(NASH_N_MAX, n))


def simulate_reference(
    precip: np.ndarray,
    pet: np.ndarray,
    params: Mapping[str, float],
) -> dict[str, np.ndarray]:
    """Return daily mm/day components for the Hydro-Agent 3-tank + Nash equations."""

    p = np.asarray(precip, dtype=float)
    e = np.asarray(pet, dtype=float)
    n = len(p)
    if len(e) != n:
        raise ValueError("forcing length mismatch")

    h1 = float(params["H1"])
    a11 = float(params["A11"])
    a12 = float(params["A12"])
    b1 = float(params["B1"])
    h2 = float(params["H2"])
    a2 = float(params["A2"])
    b2 = float(params["B2"])
    a3 = float(params["A3"])
    k = float(params["K"])
    n_res = _nash_length(params["N"])

    s1 = 10.0
    s2 = 10.0
    s3 = 20.0
    stor = [0.0] * n_res

    s1_series = np.zeros(n, dtype=float)
    s2_series = np.zeros(n, dtype=float)
    s3_series = np.zeros(n, dtype=float)
    q_surface = np.zeros(n, dtype=float)
    q_inter = np.zeros(n, dtype=float)
    q_base = np.zeros(n, dtype=float)
    et = np.zeros(n, dtype=float)
    qsim = np.zeros(n, dtype=float)

    for t in range(n):
        s1 += p[t]
        et1 = min(s1, e[t])
        s1 -= et1
        et2 = min(s2, max(0.0, e[t] - et1) * 0.5)
        s2 -= et2
        et[t] = et1 + et2

        q_high = a11 * max(s1 - h1, 0.0)
        q_side = a12 * s1
        inf1 = b1 * s1
        take1 = min(s1, q_high + q_side + inf1)
        if take1 > 0 and (q_high + q_side + inf1) > 0:
            scale = take1 / (q_high + q_side + inf1)
            q_high *= scale
            q_side *= scale
            inf1 *= scale
        s1 = max(0.0, s1 - take1)

        s2 += inf1
        q2 = a2 * max(s2 - h2, 0.0)
        inf2 = b2 * s2
        take2 = min(s2, q2 + inf2)
        if take2 > 0 and (q2 + inf2) > 0:
            scale = take2 / (q2 + inf2)
            q2 *= scale
            inf2 *= scale
        s2 = max(0.0, s2 - take2)

        s3 += inf2
        q3 = a3 * s3
        s3 = max(0.0, s3 - q3)

        q_surface[t] = q_high + q_side
        q_inter[t] = q2
        q_base[t] = q3
        runoff = max(0.0, q_surface[t] + q2 + q3)

        routed = runoff
        for i in range(n_res):
            stor[i] += routed
            outflow = k * stor[i]
            stor[i] = max(0.0, stor[i] - outflow)
            routed = outflow
        qsim[t] = routed
        s1_series[t] = s1
        s2_series[t] = s2
        s3_series[t] = s3

    return {
        "Qsim": qsim,
        "S1": s1_series,
        "S2": s2_series,
        "S3": s3_series,
        "Qsurface": q_surface,
        "Qinter": q_inter,
        "Qbase": q_base,
        "ET": et,
    }
