"""Sandbox I/O helpers for the HBV-light runtime."""

from __future__ import annotations

from pathlib import Path

from hydro_agent.models.workspace_io import load_workspace_forcing

from .contracts import HbvBasin, HbvScheme
from .plugin import HbvPlugin


def load_hbv_inputs(workspace: Path):
    scheme_payload, basin_payload, dates, array = load_workspace_forcing(
        workspace,
        required_forcings=HbvPlugin.descriptor.required_forcings,
    )
    scheme = HbvScheme(
        model_id=scheme_payload.get("model_id", "hbv"),
        warmup_days=scheme_payload["warmup_days"],
        parameters=scheme_payload["parameters"],
    )
    basin = HbvBasin.model_validate(basin_payload)
    return scheme, basin, dates, array
