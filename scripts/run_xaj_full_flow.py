#!/usr/bin/env python3
"""Run the XAJ-first research demo path on Lowman (camels_13235000).

Requires:
  HYDRO_AGENT_LOWMAN_SNAPSHOT pointing at a built R-mode snapshot
  prepared source under data/source/camels_13235000

Example:
  HYDRO_AGENT_LOWMAN_SNAPSHOT=$PWD/data/snapshots/camels_13235000/lowman-r-2020-05-01 \\
    uv run python scripts/run_xaj_full_flow.py --output /tmp/hydro-xaj-demo
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/xaj-full-flow"),
        help="Directory for DB/workspaces/reports (recreated)",
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("data/source/camels_13235000"),
        help="Prepared normalized Lowman source directory",
    )
    parser.add_argument(
        "--scheme",
        type=Path,
        default=Path("tests/fixtures/xaj/lowman_scheme.json"),
        help="Base XAJ scheme JSON",
    )
    args = parser.parse_args()
    if not os.getenv("HYDRO_AGENT_LOWMAN_SNAPSHOT"):
        print("HYDRO_AGENT_LOWMAN_SNAPSHOT is required", file=sys.stderr)
        return 2
    if not args.source.exists():
        print(f"missing prepared source: {args.source}", file=sys.stderr)
        return 2
    if not args.scheme.exists():
        print(f"missing scheme fixture: {args.scheme}", file=sys.stderr)
        return 2

    from hydro_agent.demo.xaj_full_flow import XajFullResearchFlow

    if args.output.exists():
        shutil.rmtree(args.output)
    args.output.mkdir(parents=True)
    result = XajFullResearchFlow(args.output, source_dir=args.source, scheme_path=args.scheme).run()
    summary_path = args.output / "summary.json"
    summary_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    print(f"wrote {summary_path}")
    print(f"reports under {args.output / 'reports'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
