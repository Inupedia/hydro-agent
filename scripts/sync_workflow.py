#!/usr/bin/env python3
"""Regenerate derived workflow artifacts from workflow/hydro-agent.v*.json."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydro_agent.workflow.definition import repo_root
from hydro_agent.workflow.generate import sync_derived


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if generated Archify JSON or frontend metadata drifted",
    )
    args = parser.parse_args(argv)
    root = repo_root()
    if root is None:
        root = Path(__file__).resolve().parents[1]
    written = sync_derived(root, check=args.check)
    if args.check:
        print("workflow artifacts are in sync")
        return 0
    if written:
        for path in written:
            print(f"wrote {path.relative_to(root)}")
    else:
        print("workflow artifacts already up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
