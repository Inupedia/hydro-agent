"""SAC-SMA calibration runtime: shared PDCA runtime wired for sac-sma."""

from __future__ import annotations

import argparse
from pathlib import Path

from hydro_agent.models.shared_calibrate_runtime import run as shared_run


def run(workspace: Path) -> dict:
    return shared_run(workspace)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    run(args.workspace)


if __name__ == "__main__":
    main()
