"""D* Lite seeded, custom three-objective NSGA-III.

Objectives are exactly Risk / Energy / Time.  Distance is a statistic only.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np

from .dstar import DStarLite
from .errors import PlanningCancelled
from .grid import PlanningGrid, Point


class NoFeasibleRoute(RuntimeError):
    pass


@dataclass(slots=True)
class Individual:
    path: list[Point]
    objectives: np.ndarray

    @classmethod
    def from_path(cls, grid: PlanningGrid, path: Sequence[Point]) -> Individual:
        return cls(list(path), evaluate_path(grid, path))


def evaluate_path(grid: PlanningGrid, path: Sequence[Point]) -> np.ndarray:
    if len(path) < 2:
        return np.full(3, np.inf, dtype=float)
    risk_total = 0.0
    energy_total = 0.0
    time_total = 0.0
    for a, b in zip(path, path[1:], strict=False):
        if not grid.traversable(a) or not grid.traversable(b):
            return np.full(3, np.inf, dtype=float)
        result = grid.edge_result(a, b)
        if not result.feasible:
            return np.full(3, np.inf, dtype=float)
        risk_total += result.risk
        energy_total += result.energy_mwh
        time_total += result.travel_time_h
    return np.array([risk_total, energy_total, time_total], dtype=float)


def _dominates(a: np.ndarray, b: np.ndarray) -> bool:
    return bool(np.all(a <= b) and np.any(a < b))


def _front(population: Sequence[Individual]) -> list[Individual]:
    return [
        candidate
        for index, candidate in enumerate(population)
        if not any(
            _dominates(other.objectives, candidate.objectives)
            for other_index, other in enumerate(population)
            if index != other_index
        )
    ]


def _references(divisions: int = 8) -> np.ndarray:
    points = [
        (i, j, divisions - i - j)
        for i in range(divisions + 1)
        for j in range(divisions - i + 1)
    ]
    return np.asarray(points, dtype=float) / divisions


def _select(
    population: list[Individual], size: int, rng: np.random.Generator
) -> list[Individual]:
    fronts: list[list[Individual]] = []
    remaining = list(population)
    while remaining:
        current = _front(remaining)
        fronts.append(current)
        keys = {id(item) for item in current}
        remaining = [item for item in remaining if id(item) not in keys]
    selected: list[Individual] = []
    for current in fronts:
        if len(selected) + len(current) <= size:
            selected.extend(current)
            continue
        values = np.vstack([item.objectives for item in current])
        ideal = np.min(np.vstack([item.objectives for item in population]), axis=0)
        scale = np.ptp(values, axis=0)
        scale = np.where(scale > 1e-12, scale, 1.0)
        normalized = (values - ideal) / scale
        references = _references()
        units = references / np.maximum(np.linalg.norm(references, axis=1, keepdims=True), 1e-12)
        projection = normalized @ units.T
        distances = np.sqrt(
            np.maximum(
                np.sum(normalized * normalized, axis=1) - np.max(projection, axis=1) ** 2,
                0.0,
            )
        )
        assigned = np.argmax(projection, axis=1)
        niche_count = np.zeros(len(references), dtype=int)
        for item in selected:
            value = (item.objectives - ideal) / scale
            niche_count[int(np.argmax(value @ units.T))] += 1
        candidates = set(range(len(current)))
        while len(selected) < size and candidates:
            min_count = min(niche_count[assigned[index]] for index in candidates)
            niche = min(
                assigned[index]
                for index in candidates
                if niche_count[assigned[index]] == min_count
            )
            choices = [index for index in candidates if assigned[index] == niche]
            index = (
                min(choices, key=lambda item: distances[item])
                if niche_count[niche] == 0
                else int(rng.choice(choices))
            )
            selected.append(current[index])
            candidates.remove(index)
            niche_count[niche] += 1
        return selected
    return selected[:size]


def _mutate(
    grid: PlanningGrid, individual: Individual, rng: np.random.Generator
) -> Individual:
    path = individual.path
    if len(path) < 4:
        return Individual.from_path(grid, path)
    index = int(rng.integers(1, len(path) - 1))
    previous, following = path[index - 1], path[index + 1]
    choices = [
        candidate
        for candidate in grid.neighbors(previous)
        if following in set(grid.neighbors(candidate))
    ]
    if choices:
        candidate_path = list(path)
        candidate_path[index] = choices[int(rng.integers(len(choices)))]
        return Individual.from_path(grid, candidate_path)
    return Individual.from_path(grid, path)


def _crossover(
    grid: PlanningGrid,
    first: Individual,
    second: Individual,
    rng: np.random.Generator,
) -> tuple[Individual, Individual]:
    positions = {node: index for index, node in enumerate(second.path[1:-1], start=1)}
    common = [
        (index, positions[node])
        for index, node in enumerate(first.path[1:-1], start=1)
        if node in positions
    ]
    if not common:
        return Individual.from_path(grid, first.path), Individual.from_path(grid, second.path)
    left, right = common[int(rng.integers(len(common)))]
    child_a = first.path[:left] + second.path[right:]
    child_b = second.path[:right] + first.path[left:]

    def valid(path: list[Point]) -> bool:
        return bool(
            path
            and path[0] == grid.start
            and path[-1] == grid.goal
            and all(b in set(grid.neighbors(a)) for a, b in zip(path, path[1:], strict=False))
        )

    return (
        Individual.from_path(grid, child_a if valid(child_a) else first.path),
        Individual.from_path(grid, child_b if valid(child_b) else second.path),
    )


def run_nsga3(
    grid: PlanningGrid,
    population_size: int = 36,
    generations: int = 20,
    seed: int = 42,
    should_stop: Callable[[], bool] | None = None,
) -> list[Individual]:
    rng = np.random.default_rng(seed)
    seed_paths = [
        DStarLite(grid, mode, should_stop=should_stop).plan()
        for mode in ("risk", "energy", "time")
    ]
    if any(not path for path in seed_paths):
        raise NoFeasibleRoute("No feasible path exists for one of the D* Lite objectives")
    population = [
        Individual.from_path(grid, seed_paths[index % 3])
        for index in range(population_size)
    ]
    for index in range(3, population_size):
        population[index] = _mutate(grid, population[index], rng)
    for generation in range(generations):
        if should_stop is not None and should_stop():
            raise PlanningCancelled("planning cancelled")
        offspring: list[Individual] = []
        while len(offspring) < population_size:
            first, second = rng.choice(population, 2, replace=False)
            child_a, child_b = _crossover(grid, first, second, rng)
            if rng.random() < 0.85:
                child_a = _mutate(grid, child_a, rng)
            if rng.random() < 0.85:
                child_b = _mutate(grid, child_b, rng)
            offspring.extend((child_a, child_b))
        population = _select(
            population + offspring[:population_size], population_size, rng
        )
        if generation == 0:
            continue
    front = _front(population)
    unique: dict[tuple[Point, ...], Individual] = {}
    for item in front:
        unique.setdefault(tuple(item.path), item)
    return sorted(unique.values(), key=lambda item: tuple(float(x) for x in item.objectives))


def representative_routes(front: Sequence[Individual]) -> dict[str, Individual]:
    if not front:
        return {}
    return {
        "lowest_risk": min(front, key=lambda item: item.objectives[0]),
        "lowest_energy": min(front, key=lambda item: item.objectives[1]),
        "fastest_time": min(front, key=lambda item: item.objectives[2]),
    }
