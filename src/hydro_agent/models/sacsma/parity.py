"""Registered SAC-SMA reference-parity thresholds and upstream fixture contract.

Parity is measured against output produced by the NOAA-OWP Fortran executable,
pinned to a source revision.  Thresholds are registered here before any unlock
of ``supports_calibration``; changing them requires an explicit review.
"""

from __future__ import annotations

from typing import Final

PARITY_ABS_MM_DAY: Final[dict[str, float]] = {
    "TCI": 1e-9,
    "ROIMP": 1e-9,
    "SDRO": 1e-9,
    "SSUR": 1e-9,
    "SIF": 1e-9,
    "BFS": 1e-9,
    "BFP": 1e-9,
    "BFNCC": 1e-9,
    "ETA": 1e-9,
    "UZTWC": 1e-9,
    "UZFWC": 1e-9,
    "LZTWC": 1e-9,
    "LZFSC": 1e-9,
    "LZFPC": 1e-9,
    "ADIMC": 1e-9,
}

REFERENCE_REVISION: Final[str] = "975902e3d44785f3b3503f29adfb5755120f5bf5"
REFERENCE_ORACLE: Final[str] = f"NOAA-OWP sac-sma Fortran fixture@{REFERENCE_REVISION[:12]}"

REFERENCE_PARAMS: Final[dict[str, float]] = {
    "UZTWM": 50.0,
    "UZFWM": 40.0,
    "UZK": 0.3,
    "PCTIM": 0.01,
    "ADIMP": 0.15,
    "RIVA": 0.02,
    "ZPERC": 20.0,
    "REXP": 2.0,
    "LZTWM": 120.0,
    "LZFSM": 40.0,
    "LZFPM": 150.0,
    "LZSK": 0.08,
    "LZPK": 0.01,
    "PFREE": 0.3,
    "SIDE": 0.1,
    "RSERV": 0.3,
}
