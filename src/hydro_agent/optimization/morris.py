"""Deterministic Morris elementary-effects screening for calibration parameters.

This module is deliberately optimizer-agnostic. It answers *which parameters are
worth spending search budget on*; DDS/SCE-UA still own the numerical search for
concrete parameter values.

Morris exposes a versioned checkpoint so an interrupted screening run can resume
without replaying completed score-function calls. The checkpoint includes the RNG
state and any in-progress trajectory because both affect the exact elementary
-effects sequence.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass

ScoreFn = Callable[[dict[str, float]], float | None]
CheckpointFn = Callable[["MorrisCheckpoint"], None]


@dataclass(frozen=True)
class MorrisParameterSensitivity:
    name: str
    mu: float | None
    mu_star: float | None
    sigma: float | None
    relative_mu_star: float | None
    attempted_effects: int
    valid_effects: int
    status: str

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "mu": self.mu,
            "mu_star": self.mu_star,
            "sigma": self.sigma,
            "relative_mu_star": self.relative_mu_star,
            "attempted_effects": self.attempted_effects,
            "valid_effects": self.valid_effects,
            "status": self.status,
        }


@dataclass(frozen=True)
class MorrisCheckpoint:
    """Serializable continuation state for one Morris screening contract."""

    version: int
    parameter_names: tuple[str, ...]
    bounds: tuple[tuple[str, float, float], ...]
    trajectories: int
    levels: int
    random_seed: int
    min_relative_mu_star: float
    min_effects_per_parameter: int
    min_active_parameters: int
    active_parameter_limit: int | None
    trajectory_index: int
    step_index: int
    score_calls: int
    effects: dict[str, tuple[float, ...]]
    attempted: dict[str, int]
    directions: tuple[float, ...] | None
    order: tuple[int, ...] | None
    current: tuple[float, ...] | None
    current_score: float | None
    rng_state: dict[str, object]

    def as_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "parameter_names": list(self.parameter_names),
            "bounds": [list(item) for item in self.bounds],
            "trajectories": self.trajectories,
            "levels": self.levels,
            "random_seed": self.random_seed,
            "min_relative_mu_star": self.min_relative_mu_star,
            "min_effects_per_parameter": self.min_effects_per_parameter,
            "min_active_parameters": self.min_active_parameters,
            "active_parameter_limit": self.active_parameter_limit,
            "trajectory_index": self.trajectory_index,
            "step_index": self.step_index,
            "score_calls": self.score_calls,
            "effects": {name: list(values) for name, values in self.effects.items()},
            "attempted": dict(self.attempted),
            "directions": list(self.directions) if self.directions is not None else None,
            "order": list(self.order) if self.order is not None else None,
            "current": list(self.current) if self.current is not None else None,
            "current_score": self.current_score,
            "rng_state": dict(self.rng_state),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "MorrisCheckpoint":
        raw_bounds = payload.get("bounds") or ()
        bounds = tuple(
            (str(item[0]), float(item[1]), float(item[2]))
            for item in raw_bounds  # type: ignore[union-attr]
        )
        raw_effects = payload.get("effects") or {}
        effects = {
            str(name): tuple(float(value) for value in values)
            for name, values in dict(raw_effects).items()  # type: ignore[arg-type]
        }
        raw_attempted = payload.get("attempted") or {}
        attempted = {
            str(name): int(value)
            for name, value in dict(raw_attempted).items()  # type: ignore[arg-type]
        }
        raw_rng = payload.get("rng_state")
        if not isinstance(raw_rng, dict):
            raise ValueError("Morris checkpoint missing rng_state")
        current_score = payload.get("current_score")
        return cls(
            version=int(payload.get("version") or 0),
            parameter_names=tuple(str(name) for name in (payload.get("parameter_names") or ())),
            bounds=bounds,
            trajectories=int(payload.get("trajectories") or 0),
            levels=int(payload.get("levels") or 0),
            random_seed=int(payload.get("random_seed") or 0),
            min_relative_mu_star=float(payload.get("min_relative_mu_star") or 0.0),
            min_effects_per_parameter=int(payload.get("min_effects_per_parameter") or 0),
            min_active_parameters=int(payload.get("min_active_parameters") or 0),
            active_parameter_limit=(
                int(payload["active_parameter_limit"])
                if payload.get("active_parameter_limit") is not None
                else None
            ),
            trajectory_index=int(payload.get("trajectory_index") or 0),
            step_index=int(payload.get("step_index") or 0),
            score_calls=int(payload.get("score_calls") or 0),
            effects=effects,
            attempted=attempted,
            directions=(
                tuple(float(value) for value in payload["directions"])  # type: ignore[index]
                if payload.get("directions") is not None
                else None
            ),
            order=(
                tuple(int(value) for value in payload["order"])  # type: ignore[index]
                if payload.get("order") is not None
                else None
            ),
            current=(
                tuple(float(value) for value in payload["current"])  # type: ignore[index]
                if payload.get("current") is not None
                else None
            ),
            current_score=float(current_score) if current_score is not None else None,
            rng_state=dict(raw_rng),
        )


@dataclass(frozen=True)
class MorrisScreeningResult:
    method: str
    trajectories: int
    levels: int
    delta: float
    score_calls: int
    active_parameters: tuple[str, ...]
    screened_out_parameters: tuple[str, ...]
    insufficient_evidence_parameters: tuple[str, ...]
    sensitivities: tuple[MorrisParameterSensitivity, ...]
    checkpoint: MorrisCheckpoint | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "method": self.method,
            "trajectories": self.trajectories,
            "levels": self.levels,
            "delta": self.delta,
            "score_calls": self.score_calls,
            "active_parameters": list(self.active_parameters),
            "screened_out_parameters": list(self.screened_out_parameters),
            "insufficient_evidence_parameters": list(self.insufficient_evidence_parameters),
            "sensitivities": [item.as_dict() for item in self.sensitivities],
        }


def _is_valid_score(value: float | None) -> bool:
    return value is not None and math.isfinite(float(value))


def _checkpoint_score(value: float | None) -> float | None:
    return float(value) if _is_valid_score(value) else None


def _bounds_contract(
    names: tuple[str, ...], bounds: dict[str, tuple[float, float]]
) -> tuple[tuple[str, float, float], ...]:
    return tuple((name, float(bounds[name][0]), float(bounds[name][1])) for name in names)


def _validate_checkpoint(
    checkpoint: MorrisCheckpoint,
    *,
    names: tuple[str, ...],
    bounds_contract: tuple[tuple[str, float, float], ...],
    trajectories: int,
    levels: int,
    random_seed: int,
    min_relative_mu_star: float,
    min_effects_per_parameter: int,
    min_active_parameters: int,
    active_parameter_limit: int | None,
) -> None:
    if checkpoint.version != 1:
        raise ValueError(f"unsupported Morris checkpoint version: {checkpoint.version}")
    if checkpoint.parameter_names != names or checkpoint.bounds != bounds_contract:
        raise ValueError("Morris checkpoint parameter/bounds contract mismatch")
    if (
        checkpoint.trajectories != trajectories
        or checkpoint.levels != levels
        or checkpoint.random_seed != random_seed
        or abs(checkpoint.min_relative_mu_star - min_relative_mu_star) > 1e-15
        or checkpoint.min_effects_per_parameter != min_effects_per_parameter
        or checkpoint.min_active_parameters != min_active_parameters
        or checkpoint.active_parameter_limit != active_parameter_limit
    ):
        raise ValueError("Morris checkpoint screening contract mismatch")
    if checkpoint.trajectory_index < 0 or checkpoint.trajectory_index > trajectories:
        raise ValueError("Morris checkpoint trajectory index out of range")
    if checkpoint.step_index < 0 or checkpoint.step_index > len(names):
        raise ValueError("Morris checkpoint step index out of range")
    if set(checkpoint.effects) != set(names) or set(checkpoint.attempted) != set(names):
        raise ValueError("Morris checkpoint parameter state mismatch")
    in_progress = checkpoint.current is not None
    if in_progress != (checkpoint.directions is not None and checkpoint.order is not None):
        raise ValueError("Morris checkpoint incomplete trajectory state")
    if in_progress and (
        len(checkpoint.current or ()) != len(names)
        or len(checkpoint.directions or ()) != len(names)
        or len(checkpoint.order or ()) != len(names)
    ):
        raise ValueError("Morris checkpoint trajectory dimension mismatch")


def screen_morris(
    *,
    bounds: dict[str, tuple[float, float]],
    score_fn: ScoreFn,
    trajectories: int = 6,
    levels: int = 6,
    random_seed: int = 0,
    min_relative_mu_star: float = 0.10,
    min_effects_per_parameter: int = 2,
    min_active_parameters: int = 2,
    active_parameter_limit: int | None = 6,
    resume_from: MorrisCheckpoint | None = None,
    checkpoint_fn: CheckpointFn | None = None,
    checkpoint_every: int = 1,
) -> MorrisScreeningResult:
    """Screen parameters with Morris elementary effects in normalized space.

    Elementary effects are computed against normalized coordinates, making
    ``mu_star`` comparable across parameters with different physical units. A
    parameter is screened out only when there is enough valid evidence. Missing
    or invalid effects are handled conservatively: insufficiently observed
    parameters remain active rather than being declared unimportant.

    When ``resume_from`` is provided, the exact RNG/trajectory/effect state is
    restored and completed score calls are not replayed.
    """

    if trajectories < 1:
        raise ValueError("trajectories must be >= 1")
    if levels < 4 or levels % 2:
        raise ValueError("levels must be an even integer >= 4")
    if not 0.0 <= min_relative_mu_star <= 1.0:
        raise ValueError("min_relative_mu_star must be in [0, 1]")
    if min_effects_per_parameter < 1:
        raise ValueError("min_effects_per_parameter must be >= 1")
    if min_active_parameters < 1:
        raise ValueError("min_active_parameters must be >= 1")
    if active_parameter_limit is not None and active_parameter_limit < 1:
        raise ValueError("active_parameter_limit must be >= 1")
    if not bounds:
        raise ValueError("Morris screening requires at least one parameter")
    if checkpoint_every < 1:
        raise ValueError("checkpoint_every must be >= 1")

    import numpy as np

    names = tuple(bounds)
    for name, (low, high) in bounds.items():
        if not math.isfinite(float(low)) or not math.isfinite(float(high)) or high <= low:
            raise ValueError(f"invalid Morris bound for {name}: {low}..{high}")

    delta = float(levels / (2.0 * (levels - 1)))
    grid = np.linspace(0.0, 1.0, levels)
    bounds_contract = _bounds_contract(names, bounds)
    rng = np.random.default_rng(random_seed)

    if resume_from is not None:
        _validate_checkpoint(
            resume_from,
            names=names,
            bounds_contract=bounds_contract,
            trajectories=trajectories,
            levels=levels,
            random_seed=random_seed,
            min_relative_mu_star=min_relative_mu_star,
            min_effects_per_parameter=min_effects_per_parameter,
            min_active_parameters=min_active_parameters,
            active_parameter_limit=active_parameter_limit,
        )
        effects = {name: list(resume_from.effects[name]) for name in names}
        attempted = {name: int(resume_from.attempted[name]) for name in names}
        score_calls = int(resume_from.score_calls)
        trajectory_index = int(resume_from.trajectory_index)
        step_index = int(resume_from.step_index)
        directions = (
            np.asarray(resume_from.directions, dtype=float)
            if resume_from.directions is not None
            else None
        )
        order = tuple(resume_from.order) if resume_from.order is not None else None
        current = (
            np.asarray(resume_from.current, dtype=float)
            if resume_from.current is not None
            else None
        )
        current_score = resume_from.current_score
        rng.bit_generator.state = dict(resume_from.rng_state)
    else:
        effects = {name: [] for name in names}
        attempted = {name: 0 for name in names}
        score_calls = 0
        trajectory_index = 0
        step_index = 0
        directions = None
        order = None
        current = None
        current_score = None

    def to_physical(point) -> dict[str, float]:
        return {
            name: float(bounds[name][0] + float(point[index]) * (bounds[name][1] - bounds[name][0]))
            for index, name in enumerate(names)
        }

    def checkpoint() -> MorrisCheckpoint:
        return MorrisCheckpoint(
            version=1,
            parameter_names=names,
            bounds=bounds_contract,
            trajectories=trajectories,
            levels=levels,
            random_seed=random_seed,
            min_relative_mu_star=min_relative_mu_star,
            min_effects_per_parameter=min_effects_per_parameter,
            min_active_parameters=min_active_parameters,
            active_parameter_limit=active_parameter_limit,
            trajectory_index=trajectory_index,
            step_index=step_index,
            score_calls=score_calls,
            effects={name: tuple(effects[name]) for name in names},
            attempted=dict(attempted),
            directions=(
                tuple(float(value) for value in directions) if directions is not None else None
            ),
            order=order,
            current=tuple(float(value) for value in current) if current is not None else None,
            current_score=_checkpoint_score(current_score),
            rng_state=dict(rng.bit_generator.state),
        )

    def emit_checkpoint(*, force: bool = False) -> MorrisCheckpoint:
        state = checkpoint()
        if checkpoint_fn is not None and (
            force or score_calls % checkpoint_every == 0 or trajectory_index == trajectories
        ):
            checkpoint_fn(state)
        return state

    while trajectory_index < trajectories:
        if current is None:
            directions = rng.choice(np.asarray([-1.0, 1.0]), size=len(names))
            start = np.empty(len(names), dtype=float)
            for index, direction in enumerate(directions):
                if direction > 0:
                    choices = grid[grid <= 1.0 - delta + 1e-12]
                else:
                    choices = grid[grid >= delta - 1e-12]
                start[index] = float(rng.choice(choices))
            order = tuple(int(i) for i in rng.permutation(len(names)))
            current = start
            current_score = score_fn(to_physical(current))
            score_calls += 1
            step_index = 0
            emit_checkpoint()

        assert directions is not None
        assert order is not None
        assert current is not None

        while step_index < len(order):
            index = order[step_index]
            next_point = current.copy()
            next_point[index] += directions[index] * delta
            next_point[index] = min(max(float(next_point[index]), 0.0), 1.0)
            next_score = score_fn(to_physical(next_point))
            score_calls += 1
            name = names[index]
            attempted[name] += 1
            if _is_valid_score(current_score) and _is_valid_score(next_score):
                denominator = float(next_point[index] - current[index])
                if abs(denominator) > 1e-12:
                    effects[name].append((float(next_score) - float(current_score)) / denominator)
            current = next_point
            current_score = next_score
            step_index += 1

            if step_index == len(order):
                trajectory_index += 1
                step_index = 0
                directions = None
                order = None
                current = None
                current_score = None
            emit_checkpoint()
            if current is None:
                break

    raw_stats: dict[str, tuple[float | None, float | None, float | None]] = {}
    max_mu_star = 0.0
    for name in names:
        values = effects[name]
        if values:
            arr = np.asarray(values, dtype=float)
            mu = float(arr.mean())
            mu_star = float(np.abs(arr).mean())
            sigma = float(arr.std(ddof=1)) if len(arr) >= 2 else 0.0
            max_mu_star = max(max_mu_star, mu_star)
            raw_stats[name] = (mu, mu_star, sigma)
        else:
            raw_stats[name] = (None, None, None)

    reliable = [name for name in names if len(effects[name]) >= min_effects_per_parameter]
    insufficient = [name for name in names if name not in reliable]
    ranked = sorted(
        reliable,
        key=lambda name: float(raw_stats[name][1] or 0.0),
        reverse=True,
    )

    if max_mu_star <= 1e-12:
        active_reliable = list(ranked)
    else:
        active_reliable = [
            name
            for name in ranked
            if float(raw_stats[name][1] or 0.0) / max_mu_star >= min_relative_mu_star
        ]
        minimum = min(min_active_parameters, len(ranked))
        for name in ranked[:minimum]:
            if name not in active_reliable:
                active_reliable.append(name)
        active_reliable.sort(key=lambda name: ranked.index(name))
        if active_parameter_limit is not None:
            active_reliable = active_reliable[:active_parameter_limit]

    active_set = set(active_reliable) | set(insufficient)
    active = tuple(name for name in names if name in active_set)
    screened_out = tuple(name for name in names if name not in active_set)

    sensitivities: list[MorrisParameterSensitivity] = []
    for name in names:
        mu, mu_star, sigma = raw_stats[name]
        relative = None
        if mu_star is not None:
            relative = 0.0 if max_mu_star <= 0.0 else float(mu_star / max_mu_star)
        if name in insufficient:
            status = "insufficient_evidence"
        elif name in active_set:
            status = "active"
        else:
            status = "screened_out"
        sensitivities.append(
            MorrisParameterSensitivity(
                name=name,
                mu=mu,
                mu_star=mu_star,
                sigma=sigma,
                relative_mu_star=relative,
                attempted_effects=attempted[name],
                valid_effects=len(effects[name]),
                status=status,
            )
        )

    final_checkpoint = emit_checkpoint(force=True)
    return MorrisScreeningResult(
        method="morris",
        trajectories=trajectories,
        levels=levels,
        delta=delta,
        score_calls=score_calls,
        active_parameters=active,
        screened_out_parameters=screened_out,
        insufficient_evidence_parameters=tuple(insufficient),
        sensitivities=tuple(sensitivities),
        checkpoint=final_checkpoint,
    )
