"""Registered Tank (3-tank + Nash) reference-parity thresholds and oracle contract.

Parity is measured against an independent equation oracle of the Hydro-Agent
Sugawara-family three-tank + discrete Nash cascade. Thresholds are registered
here *before* any unlock of ``supports_calibration``.
"""

from __future__ import annotations

from typing import Final

PARITY_ABS_MM_DAY: Final[dict[str, float]] = {
    "Qsim": 1e-6,
    "S1": 1e-6,
    "S2": 1e-6,
    "S3": 1e-6,
    "Qsurface": 1e-6,
    "Qinter": 1e-6,
    "Qbase": 1e-6,
    "ET": 1e-6,
}

REFERENCE_ORACLE: Final[str] = "hydro-agent-tank-3nash/Sugawara-family"
REFERENCE_PARAMS: Final[dict[str, float]] = {
    "H1": 15.0,
    "A11": 0.2,
    "A12": 0.1,
    "B1": 0.2,
    "H2": 8.0,
    "A2": 0.08,
    "B2": 0.08,
    "A3": 0.02,
    "K": 0.4,
    "N": 2.0,
}
