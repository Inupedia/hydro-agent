#!/usr/bin/env python3
"""Preregister, execute and export Hydro-Agent O/P/A/A+ research suites.

The CLI never invents a runtime. Use ``--executor module:function`` to plug in an
isolated task runner that accepts one ExperimentCell and returns BenchmarkRun (or
a compatible dict). Without an executor it writes the deterministic manifest only,
which can be reviewed/preregistered before any final-test data is consumed.
"""

from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path

from hydro_agent.research.benchmark import BenchmarkRun, BenchmarkScenario
from hydro_agent.research.suite import (
    ExperimentCell,
    ResearchSuiteManifest,
    ResearchSuiteRun,
    ResearchSuiteRunner,
    build_research_manifest,
    write_research_suite_bundle,
)


def _load_scenarios(path: Path) -> tuple[BenchmarkScenario, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("scenarios")
    if not isinstance(payload, list) or not payload:
        raise ValueError("scenario file must contain a non-empty JSON array or {scenarios:[...]}")
    return tuple(BenchmarkScenario.model_validate(item) for item in payload)


def _load_executor(spec: str):
    if ":" not in spec:
        raise ValueError("executor must use module:function syntax")
    module_name, function_name = spec.split(":", 1)
    module = importlib.import_module(module_name)
    function = getattr(module, function_name, None)
    if not callable(function):
        raise ValueError(f"executor is not callable: {spec}")

    def execute(cell: ExperimentCell) -> BenchmarkRun:
        result = function(cell)
        return result if isinstance(result, BenchmarkRun) else BenchmarkRun.model_validate(result)

    return execute


def _write_manifest(manifest: ResearchSuiteManifest, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "research-manifest.json"
    path.write_text(
        json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _load_runs(path: Path) -> tuple[ResearchSuiteRun, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("runs file must contain a JSON array")
    return tuple(ResearchSuiteRun.model_validate(item) for item in payload)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenarios", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--budget", type=int, default=512)
    parser.add_argument("--replicates", type=int, default=3)
    parser.add_argument("--seed", type=int, default=20260913)
    parser.add_argument(
        "--executor",
        help="optional isolated cell runner as module:function; omitted = preregister only",
    )
    parser.add_argument(
        "--runs",
        type=Path,
        help="aggregate a previously executed research-runs.json against the new deterministic manifest",
    )
    args = parser.parse_args()

    scenarios = _load_scenarios(args.scenarios)
    manifest = build_research_manifest(
        scenarios,
        evaluation_budget=args.budget,
        replicates=args.replicates,
        base_seed=args.seed,
    )
    manifest_path = _write_manifest(manifest, args.out)

    if args.executor and args.runs:
        raise ValueError("choose either --executor or --runs, not both")
    if args.executor:
        runs = ResearchSuiteRunner(_load_executor(args.executor)).execute(manifest)
        _, runs_path, summary_path = write_research_suite_bundle(manifest, runs, args.out)
        print(
            json.dumps(
                {
                    "manifest_id": manifest.manifest_id,
                    "manifest": str(manifest_path),
                    "runs": str(runs_path),
                    "summary": str(summary_path),
                    "cell_count": len(manifest.cells),
                },
                sort_keys=True,
            )
        )
        return
    if args.runs:
        runs = _load_runs(args.runs)
        _, runs_path, summary_path = write_research_suite_bundle(manifest, runs, args.out)
        print(
            json.dumps(
                {
                    "manifest_id": manifest.manifest_id,
                    "manifest": str(manifest_path),
                    "runs": str(runs_path),
                    "summary": str(summary_path),
                    "cell_count": len(manifest.cells),
                },
                sort_keys=True,
            )
        )
        return

    print(
        json.dumps(
            {
                "manifest_id": manifest.manifest_id,
                "manifest": str(manifest_path),
                "cell_count": len(manifest.cells),
                "status": "preregistered",
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
