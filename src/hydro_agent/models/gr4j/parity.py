"""Registered GR4J reference-parity thresholds and oracle contract.

Parity is measured against an airGR-aligned reference (GRsuite, validated to
airGR 1.7.9). Thresholds are registered here *before* any unlock of
``supports_calibration``; changing them requires an explicit review.
"""

from __future__ import annotations

from typing import Final

# Maximum absolute daily residual (mm/d) allowed vs the reference oracle.
# Empirical residual with ``float32(0.9)`` UH split is ~1e-14; the registered
# gate is deliberately looser so CI stays stable across platforms while still
# catching structural equation mistakes (~1e-3 and above).
PARITY_ABS_MM_DAY: Final[dict[str, float]] = {
    "Qsim": 1e-6,
    "Prod": 1e-6,
    "Rout": 1e-6,
    "Pn": 1e-6,
    "Ps": 1e-6,
    "Perc": 1e-6,
    "PR": 1e-6,
    "Q9": 1e-6,
    "Q1": 1e-6,
    "Exch": 1e-6,
    "QR": 1e-6,
    "QD": 1e-6,
}

REFERENCE_ORACLE: Final[str] = "GRsuite/airGR-1.7.9-aligned"
REFERENCE_PARAMS: Final[dict[str, float]] = {
    "X1": 257.238,
    "X2": 1.012,
    "X3": 88.235,
    "X4": 2.208,
}
