"""Deterministic SCE-UA optimizer for bounded hydrologic calibration.

The implementation follows the Shuffled Complex Evolution idea:
a population is ranked, partitioned into complexes, each complex evolves
competitive simplexes, and the population is shuffled again. It is deliberately
small and dependency-light so the XAJ sandbox only requires NumPy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np

ScoreFn = Callable[[dict[str, float]], float | None]


@dataclass(frozen=True)
class SceUaResult:
    best_parameters: dict[str, float]
    best_score: float
    evaluations: int
    improvement_history: tuple[tuple[int, float], ...]


def _clip(point: np.ndarray, lows: np.ndarray, highs: np.ndarray) -> np.ndarray:
    return np.minimum(np.maximum(point, lows), highs)


def _weighted_simplex_indices(
    rng: np.random.Generator, size: int, simplex_size: int
) -> np.ndarray:
    # SCE-UA gives better ranked points a larger selection probability.
    ranks = np.arange(size, dtype=float)
    weights = 2.0 * (size - ranks) / (size * (size + 1.0))
    return rng.choice(size, size=simplex_size, replace=False, p=weights / weights.sum())


def optimize_sceua(
    *,
    bounds: dict[str, tuple[float, float]],
    score_fn: ScoreFn,
    evaluation_budget: int,
    random_seed: int,
    initial_parameters: dict[str, float] | None = None,
    complexes: int = 2,
) -> SceUaResult:
    """Maximize ``score_fn`` within ``bounds`` using shuffled complex evolution.

    ``evaluation_budget`` is a hard cap on score-function calls. Invalid model
    states may return ``None`` or a non-finite score and are treated as -inf.
    """

    if not bounds:
        raise ValueError("SCE-UA requires at least one tunable parameter")
    if evaluation_budget < 2:
        raise ValueError("evaluation_budget must be >= 2")

    names = tuple(bounds)
    lows = np.asarray([float(bounds[name][0]) for name in names], dtype=float)
    highs = np.asarray([float(bounds[name][1]) for name in names], dtype=float)
    if np.any(highs <= lows):
        raise ValueError("all SCE-UA bounds must satisfy upper > lower")

    dimension = len(names)
    complexes = max(1, int(complexes))
    points_per_complex = max(2 * dimension + 1, dimension + 2)
    population_size = min(evaluation_budget, complexes * points_per_complex)
    complexes = max(1, min(complexes, population_size // (dimension + 1) or 1))
    rng = np.random.default_rng(random_seed)

    population: list[np.ndarray] = []
    if initial_parameters is not None:
        initial = np.asarray(
            [
                float(initial_parameters.get(name, (lo + hi) / 2.0))
                for name, lo, hi in zip(names, lows, highs)
            ],
            dtype=float,
        )
        population.append(_clip(initial, lows, highs))
    while len(population) < population_size:
        population.append(rng.uniform(lows, highs))

    evaluations = 0
    history: list[tuple[int, float]] = []
    best_score = float("-inf")
    best_point = population[0].copy()

    def evaluate(point: np.ndarray) -> float:
        nonlocal evaluations, best_score, best_point
        if evaluations >= evaluation_budget:
            return float("-inf")
        params = {name: float(value) for name, value in zip(names, point)}
        raw = score_fn(params)
        evaluations += 1
        score = float(raw) if raw is not None else float("-inf")
        if not np.isfinite(score):
            score = float("-inf")
        if score > best_score:
            best_score = score
            best_point = point.copy()
            history.append((evaluations, score))
        return score

    scores = np.asarray([evaluate(point) for point in population], dtype=float)

    while evaluations < evaluation_budget:
        order = np.argsort(-scores)
        pop_arr = np.asarray(population, dtype=float)[order]
        scores = scores[order]

        # Rank-shuffled partition: 0,m,2m... / 1,m+1...
        complex_points: list[list[np.ndarray]] = [[] for _ in range(complexes)]
        complex_scores: list[list[float]] = [[] for _ in range(complexes)]
        for rank, (point, score) in enumerate(zip(pop_arr, scores)):
            bucket = rank % complexes
            complex_points[bucket].append(point.copy())
            complex_scores[bucket].append(float(score))

        any_step = False
        for cidx in range(complexes):
            pts = complex_points[cidx]
            scs = complex_scores[cidx]
            if len(pts) < dimension + 1:
                continue

            # A few competitive-complex-evolution steps before shuffling.
            steps = max(1, len(pts))
            for _ in range(steps):
                if evaluations >= evaluation_budget:
                    break
                local_order = np.argsort(-np.asarray(scs, dtype=float))
                pts = [pts[i] for i in local_order]
                scs = [scs[i] for i in local_order]
                simplex_size = min(dimension + 1, len(pts))
                selected = _weighted_simplex_indices(rng, len(pts), simplex_size)
                simplex = [pts[i] for i in selected]
                simplex_scores = [scs[i] for i in selected]
                sorder = np.argsort(-np.asarray(simplex_scores, dtype=float))
                simplex = [simplex[i] for i in sorder]
                simplex_scores = [simplex_scores[i] for i in sorder]

                worst = simplex[-1]
                centroid = np.mean(np.asarray(simplex[:-1], dtype=float), axis=0)
                reflected = _clip(centroid + (centroid - worst), lows, highs)
                trial = reflected
                trial_score = evaluate(trial)

                if trial_score <= simplex_scores[-1] and evaluations < evaluation_budget:
                    contracted = _clip(worst + 0.5 * (centroid - worst), lows, highs)
                    contracted_score = evaluate(contracted)
                    if contracted_score > trial_score:
                        trial, trial_score = contracted, contracted_score

                if trial_score <= simplex_scores[-1] and evaluations < evaluation_budget:
                    random_point = rng.uniform(lows, highs)
                    random_score = evaluate(random_point)
                    if random_score > trial_score:
                        trial, trial_score = random_point, random_score

                # Replace the selected simplex's worst member in the complex.
                worst_selected_idx = int(selected[int(sorder[-1])])
                pts[worst_selected_idx] = trial
                scs[worst_selected_idx] = trial_score
                any_step = True

            complex_points[cidx] = pts
            complex_scores[cidx] = scs

        population = []
        score_list: list[float] = []
        max_len = max(len(points) for points in complex_points)
        for rank in range(max_len):
            for cidx in range(complexes):
                if rank < len(complex_points[cidx]):
                    population.append(complex_points[cidx][rank])
                    score_list.append(complex_scores[cidx][rank])
        scores = np.asarray(score_list, dtype=float)
        if not any_step:
            break

    if not np.isfinite(best_score):
        raise ValueError("SCE-UA found no evaluable candidate")
    return SceUaResult(
        best_parameters={name: float(value) for name, value in zip(names, best_point)},
        best_score=float(best_score),
        evaluations=evaluations,
        improvement_history=tuple(history),
    )
