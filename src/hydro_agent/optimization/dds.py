"""Dynamically Dimensioned Search for bounded hydrologic calibration.

DDS is designed for calibration problems where the number of model evaluations
is explicitly limited. Early iterations perturb many dimensions for exploration;
later iterations progressively focus on fewer dimensions for local refinement.

The optimizer exposes a versioned checkpoint containing the numerical state
needed to resume *the same* search after interruption. A resume does not replay
completed score-function calls and therefore does not silently double-spend the
campaign model-evaluation budget.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, log
from typing import Callable, Mapping

import numpy as np

ScoreFn = Callable[[dict[str, float]], float | None]
CheckpointFn = Callable[["DdsCheckpoint"], None]


@dataclass(frozen=True)
class DdsCheckpoint:
    """Serializable DDS continuation state.

    The bounds and parameter order are part of the state contract because DDS
    perturbation probabilities and RNG draws are dimension/order dependent.
    ``rng_state`` is the NumPy bit-generator state *after* ``evaluations`` calls.
    """

    version: int
    parameter_names: tuple[str, ...]
    bounds: tuple[tuple[str, float, float], ...]
    evaluation_budget: int
    random_seed: int
    perturbation_scale: float
    evaluations: int
    best_parameters: dict[str, float]
    best_score: float | None
    improvement_history: tuple[tuple[int, float], ...]
    rng_state: dict[str, object]

    def as_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "parameter_names": list(self.parameter_names),
            "bounds": [list(item) for item in self.bounds],
            "evaluation_budget": self.evaluation_budget,
            "random_seed": self.random_seed,
            "perturbation_scale": self.perturbation_scale,
            "evaluations": self.evaluations,
            "best_parameters": dict(self.best_parameters),
            "best_score": self.best_score,
            "improvement_history": [list(item) for item in self.improvement_history],
            "rng_state": dict(self.rng_state),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "DdsCheckpoint":
        raw_bounds = payload.get("bounds") or ()
        bounds = tuple(
            (str(item[0]), float(item[1]), float(item[2]))
            for item in raw_bounds  # type: ignore[union-attr]
        )
        raw_history = payload.get("improvement_history") or ()
        history = tuple(
            (int(item[0]), float(item[1]))
            for item in raw_history  # type: ignore[union-attr]
        )
        raw_best = payload.get("best_parameters") or {}
        best_parameters = {
            str(key): float(value)
            for key, value in dict(raw_best).items()  # type: ignore[arg-type]
        }
        raw_rng = payload.get("rng_state")
        if not isinstance(raw_rng, dict):
            raise ValueError("DDS checkpoint missing rng_state")
        raw_score = payload.get("best_score")
        return cls(
            version=int(payload.get("version") or 0),
            parameter_names=tuple(str(name) for name in (payload.get("parameter_names") or ())),
            bounds=bounds,
            evaluation_budget=int(payload.get("evaluation_budget") or 0),
            random_seed=int(payload.get("random_seed") or 0),
            perturbation_scale=float(payload.get("perturbation_scale") or 0.0),
            evaluations=int(payload.get("evaluations") or 0),
            best_parameters=best_parameters,
            best_score=float(raw_score) if raw_score is not None else None,
            improvement_history=history,
            rng_state=dict(raw_rng),
        )


@dataclass(frozen=True)
class DdsResult:
    best_parameters: dict[str, float]
    best_score: float
    evaluations: int
    improvement_history: tuple[tuple[int, float], ...]
    checkpoint: DdsCheckpoint


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


def _bounds_contract(
    names: tuple[str, ...], lows: np.ndarray, highs: np.ndarray
) -> tuple[tuple[str, float, float], ...]:
    return tuple(
        (name, float(low), float(high))
        for name, low, high in zip(names, lows, highs)
    )


def _checkpoint(
    *,
    names: tuple[str, ...],
    bounds_contract: tuple[tuple[str, float, float], ...],
    evaluation_budget: int,
    random_seed: int,
    perturbation_scale: float,
    evaluations: int,
    best: np.ndarray,
    best_score: float,
    history: list[tuple[int, float]],
    rng: np.random.Generator,
) -> DdsCheckpoint:
    return DdsCheckpoint(
        version=1,
        parameter_names=names,
        bounds=bounds_contract,
        evaluation_budget=evaluation_budget,
        random_seed=random_seed,
        perturbation_scale=perturbation_scale,
        evaluations=evaluations,
        best_parameters={name: float(value) for name, value in zip(names, best)},
        best_score=float(best_score) if isfinite(best_score) else None,
        improvement_history=tuple(history),
        rng_state=dict(rng.bit_generator.state),
    )


def _validate_checkpoint(
    checkpoint: DdsCheckpoint,
    *,
    names: tuple[str, ...],
    bounds_contract: tuple[tuple[str, float, float], ...],
    evaluation_budget: int,
    random_seed: int,
    perturbation_scale: float,
) -> None:
    if checkpoint.version != 1:
        raise ValueError(f"unsupported DDS checkpoint version: {checkpoint.version}")
    if checkpoint.parameter_names != names or checkpoint.bounds != bounds_contract:
        raise ValueError("DDS checkpoint parameter/bounds contract mismatch")
    if checkpoint.evaluation_budget != evaluation_budget:
        raise ValueError("DDS checkpoint evaluation_budget mismatch")
    if checkpoint.random_seed != random_seed:
        raise ValueError("DDS checkpoint random_seed mismatch")
    if abs(checkpoint.perturbation_scale - perturbation_scale) > 1e-15:
        raise ValueError("DDS checkpoint perturbation_scale mismatch")
    if checkpoint.evaluations < 1 or checkpoint.evaluations > evaluation_budget:
        raise ValueError("DDS checkpoint evaluations out of range")
    if tuple(checkpoint.best_parameters) != names:
        raise ValueError("DDS checkpoint best_parameters order mismatch")


def optimize_dds(
    *,
    bounds: dict[str, tuple[float, float]],
    score_fn: ScoreFn,
    evaluation_budget: int,
    random_seed: int,
    initial_parameters: dict[str, float] | None = None,
    perturbation_scale: float = 0.2,
    resume_from: DdsCheckpoint | None = None,
    checkpoint_fn: CheckpointFn | None = None,
    checkpoint_every: int = 1,
) -> DdsResult:
    """Maximize ``score_fn`` within ``bounds`` using DDS.

    ``evaluation_budget`` is a hard cumulative cap on score-function calls. A
    fresh run evaluates the supplied baseline (or midpoint) once. A resumed run
    restores the exact RNG/best/history state and continues at evaluation
    ``resume_from.evaluations + 1`` without replaying completed calls.

    ``checkpoint_fn`` is invoked after completed evaluations according to
    ``checkpoint_every`` and always on the final evaluation. Callers may persist
    this state atomically; if the callback itself raises, the exception bubbles
    out and the last emitted state remains a valid interruption checkpoint.
    """

    if not bounds:
        raise ValueError("DDS requires at least one tunable parameter")
    if evaluation_budget < 2:
        raise ValueError("evaluation_budget must be >= 2")
    if not 0.0 < perturbation_scale <= 1.0:
        raise ValueError("perturbation_scale must be in (0, 1]")
    if checkpoint_every < 1:
        raise ValueError("checkpoint_every must be >= 1")

    names = tuple(bounds)
    lows = np.asarray([float(bounds[name][0]) for name in names], dtype=float)
    highs = np.asarray([float(bounds[name][1]) for name in names], dtype=float)
    if np.any(highs <= lows):
        raise ValueError("all DDS bounds must satisfy upper > lower")
    bounds_contract = _bounds_contract(names, lows, highs)

    rng = np.random.default_rng(random_seed)
    history: list[tuple[int, float]]
    evaluations: int
    best_score: float

    if resume_from is not None:
        _validate_checkpoint(
            resume_from,
            names=names,
            bounds_contract=bounds_contract,
            evaluation_budget=evaluation_budget,
            random_seed=random_seed,
            perturbation_scale=perturbation_scale,
        )
        best = np.asarray([resume_from.best_parameters[name] for name in names], dtype=float)
        best_score = (
            float(resume_from.best_score)
            if resume_from.best_score is not None
            else float("-inf")
        )
        evaluations = int(resume_from.evaluations)
        history = list(resume_from.improvement_history)
        rng.bit_generator.state = dict(resume_from.rng_state)
    else:
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
        history = []

    def emit_checkpoint(*, force: bool = False) -> DdsCheckpoint:
        state = _checkpoint(
            names=names,
            bounds_contract=bounds_contract,
            evaluation_budget=evaluation_budget,
            random_seed=random_seed,
            perturbation_scale=perturbation_scale,
            evaluations=evaluations,
            best=best,
            best_score=best_score,
            history=history,
            rng=rng,
        )
        if checkpoint_fn is not None and (
            force or evaluations % checkpoint_every == 0 or evaluations == evaluation_budget
        ):
            checkpoint_fn(state)
        return state

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
        emit_checkpoint()
        return score

    if resume_from is None:
        evaluate(best.copy())

    dimension = len(names)
    spans = highs - lows
    denominator = max(log(float(evaluation_budget)), 1e-12)

    for call_index in range(evaluations + 1, evaluation_budget + 1):
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
    final_checkpoint = emit_checkpoint(force=True)
    return DdsResult(
        best_parameters={name: float(value) for name, value in zip(names, best)},
        best_score=float(best_score),
        evaluations=evaluations,
        improvement_history=tuple(history),
        checkpoint=final_checkpoint,
    )
