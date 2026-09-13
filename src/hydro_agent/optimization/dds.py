"""Dynamically Dimensioned Search for bounded hydrologic calibration.

DDS is designed for calibration problems where the number of model evaluations
is explicitly limited. Early iterations perturb many dimensions for exploration;
later iterations progressively focus on fewer dimensions for local refinement.

This implementation maximizes ``score_fn`` and keeps the same dependency-light
contract as the in-repo SCE-UA implementation so optimizers remain swappable.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import log
from typing import Callable

import numpy as np

ScoreFn = Callable[[dict[str, float]], float | None]


@dataclass(frozen=True)
class DdsResult:
    best_parameters: dict[str, float]
    best_score: float
    evaluations: int
    improvement_history: tuple[tuple[int, float], ...]


def _reflect(value: float, low: float, high: float) -> float:
    """Reflect a DDS perturbation back into its legal interval."""
    if high <= low:
        raise ValueError("DDS bounds must satisfy upper > lower")
    x = float(value)
    # A large Gaussian draw may cross more than one interval. Repeated reflection
    # preserves distance information without silently pinning candidates to bounds.
    while x < low or x > high:
        if x < low:
            x = low + (low - x)
        if x > high:
            x = high - (x - high)
    return min(max(x, low), high)


def optimize_dds(
    *,
    bounds: dict[str, tuple[float, float]],
    score_fn: ScoreFn,
    evaluation_budget: int,
    random_seed: int,
    initial_parameters: dict[str, float] | None = None,
    perturbation_scale: float = 0.2,
) -> DdsResult:
    """Maximize ``score_fn`` within ``bounds`` using DDS.

    ``evaluation_budget`` is a hard cap on score-function calls. The first call
    evaluates the supplied baseline (or the midpoint when absent); each remaining
    call perturbs a dynamically shrinking subset of parameter dimensions.
    """

    if not bounds:
        raise ValueError("DDS requires at least one tunable parameter")
    if evaluation_budget < 2:
        raise ValueError("evaluation_budget must be >= 2")
    if not 0.0 < perturbation_scale <= 1.0:
        raise ValueError("perturbation_scale must be in (0, 1]")

    names = tuple(bounds)
    lows = np.asarray([float(bounds[name][0]) for name in names], dtype=float)
    highs = np.asarray([float(bounds[name][1]) for name in names], dtype=float)
    if np.any(highs <= lows):
        raise ValueError("all DDS bounds must satisfy upper > lower")

    rng = np.random.default_rng(random_seed)
    if initial_parameters is None:
        best = (lows + highs) / 2.0
    else:
        best = np.asarray(
            [
                float(initial_parameters.get(name, (lo + hi) / 2.0))
                for name, lo, hi in zip(names, lows, highs)
            ],
            dtype=float,
        )
        best = np.minimum(np.maximum(best, lows), highs)

    evaluations = 0
    best_score = float("-inf")
    history: list[tuple[int, float]] = []

    def evaluate(point: np.ndarray) -> float:
        nonlocal evaluations, best_score, best
        params = {name: float(value) for name, value in zip(names, point)}
        raw = score_fn(params)
        evaluations += 1
        score = float(raw) if raw is not None else float("-inf")
        if not np.isfinite(score):
            score = float("-inf")
        if score > best_score:
            best_score = score
            best = point.copy()
            history.append((evaluations, score))
        return score

    evaluate(best.copy())
    dimension = len(names)
    spans = highs - lows
    denominator = max(log(float(evaluation_budget)), 1e-12)

    for call_index in range(2, evaluation_budget + 1):
        # Tolson/Shoemaker DDS: perturbation probability decays logarithmically.
        probability = 1.0 - log(float(call_index)) / denominator
        probability = max(1.0 / dimension, min(1.0, probability))
        selected = rng.random(dimension) < probability
        if not np.any(selected):
            selected[int(rng.integers(0, dimension))] = True

        candidate = best.copy()
        for idx in np.flatnonzero(selected):
            proposal = candidate[idx] + rng.normal(0.0, perturbation_scale * spans[idx])
            candidate[idx] = _reflect(float(proposal), float(lows[idx]), float(highs[idx]))

        evaluate(candidate)

    if not np.isfinite(best_score):
        raise ValueError("DDS found no evaluable candidate")
    return DdsResult(
        best_parameters={name: float(value) for name, value in zip(names, best)},
        best_score=float(best_score),
        evaluations=evaluations,
        improvement_history=tuple(history),
    )
