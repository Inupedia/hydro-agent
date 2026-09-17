"""Sandbox I/O helpers for the tank-model runtime."""

from __future__ import annotations

from pathlib import Path

from hydro_agent.models.workspace_io import load_workspace_forcing

from .contracts import TankBasin, TankScheme
from .plugin import TankPlugin


def load_tank_inputs(workspace: Path):
    scheme_payload, basin_payload, dates, array = load_workspace_forcing(
        workspace,
        required_forcings=TankPlugin.descriptor.required_forcings,
    )
    scheme = TankScheme(
        model_id=scheme_payload.get("model_id", "tank"),
        warmup_days=scheme_payload["warmup_days"],
        parameters=scheme_payload["parameters"],
    )
    basin = TankBasin.model_validate(basin_payload)
    return scheme, basin, dates, array
