"""Sandbox I/O helpers for the SAC-SMA runtime."""

from __future__ import annotations

from pathlib import Path

from hydro_agent.models.workspace_io import load_workspace_forcing

from .contracts import SacSmaBasin, SacSmaScheme
from .plugin import SacSmaPlugin


def load_sacsma_inputs(workspace: Path):
    scheme_payload, basin_payload, dates, array = load_workspace_forcing(
        workspace,
        required_forcings=SacSmaPlugin.descriptor.required_forcings,
    )
    scheme = SacSmaScheme(
        model_id=scheme_payload.get("model_id", "sac-sma"),
        warmup_days=scheme_payload["warmup_days"],
        parameters=scheme_payload["parameters"],
    )
    basin = SacSmaBasin.model_validate(basin_payload)
    return scheme, basin, dates, array
