"""Registered HBV-light reference-parity thresholds and oracle contract.

Parity is measured against a hydromad pure-R algorithm port of HBV-light
(Seibert & Vis 2012). Thresholds are registered here *before* any unlock of
``supports_calibration``; changing them requires an explicit review.
"""

from __future__ import annotations

from typing import Final

# Maximum absolute daily residual (mm/d) allowed vs the reference oracle.
# Structural equation mistakes typically exceed ~1e-3; the registered gate is
# loose enough for platform float noise while still catching wrong UZL / MAXBAS.
PARITY_ABS_MM_DAY: Final[dict[str, float]] = {
    "Qsim": 1e-6,
    "Snow": 1e-6,
    "SM": 1e-6,
    "SUZ": 1e-6,
    "SLZ": 1e-6,
    "Recharge": 1e-6,
    "AET": 1e-6,
    "Q0": 1e-6,
    "Q1": 1e-6,
    "Q2": 1e-6,
}

REFERENCE_ORACLE: Final[str] = "hydromad-hbv-light/Seibert-Vis-2012"
REFERENCE_PARAMS: Final[dict[str, float]] = {
    "TT": 0.0,
    "CFMAX": 3.0,
    "SFCF": 1.0,
    "CFR": 0.05,
    "CWH": 0.1,
    "FC": 250.0,
    "BETA": 2.0,
    "LP": 0.7,
    "K0": 0.2,
    "K1": 0.08,
    "K2": 0.02,
    "PERC": 1.0,
    "UZL": 40.0,
    "MAXBAS": 2.5,
}
