"""One-shot D* Lite initial-path search over the planning grid."""

from __future__ import annotations

import heapq
import math
from collections.abc import Callable

from .errors import PlanningCancelled
from .grid import PlanningGrid, Point


class DStarLite:
    """D* Lite used as a feasibility seed for NSGA-III.

    It is intentionally one-shot: the static grid does not change during an
    optimization run, so an incremental replanner is unnecessary here.  The
    algorithm is still D* Lite's g/rhs/key update machinery.
    """

    def __init__(
        self,
        grid: PlanningGrid,
        mode: str,
        start: Point | None = None,
        goal: Point | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> None:
        if mode not in {"risk", "energy", "time"}:
            raise ValueError(f"Unsupported planner mode: {mode}")
        self.grid = grid
        self.mode = mode
        self.start = start or grid.start
        self.goal = goal or grid.goal
        self.should_stop = should_stop
        self.g: dict[Point, float] = {}
        self.rhs: dict[Point, float] = {self.goal: 0.0}
        self.queue: list[tuple[float, float, int, Point]] = []
        self.entries: dict[Point, tuple[float, float]] = {}
        self.counter = 0
        self.expanded = 0
        self._push(self.goal, self._key(self.goal))

    def _g(self, point: Point) -> float:
        return self.g.get(point, math.inf)

    def _rhs(self, point: Point) -> float:
        return self.rhs.get(point, math.inf)

    def _cost(self, a: Point, b: Point) -> float:
        risk, energy, time_h = self.grid.edge(a, b)
        return {"risk": max(risk, 1e-9), "energy": energy, "time": time_h}[self.mode]

    @staticmethod
    def _heuristic(_a: Point, _b: Point) -> float:
        # Directional resistance/current make a closed-form heuristic unsafe;
        # zero is admissible for all three objectives.
        return 0.0

    def _key(self, point: Point) -> tuple[float, float]:
        value = min(self._g(point), self._rhs(point))
        return value + self._heuristic(self.start, point), value

    def _push(self, point: Point, key: tuple[float, float]) -> None:
        self.counter += 1
        self.entries[point] = key
        heapq.heappush(self.queue, (key[0], key[1], self.counter, point))

    def _discard(self) -> None:
        while self.queue and self.entries.get(self.queue[0][3]) != (
            self.queue[0][0],
            self.queue[0][1],
        ):
            heapq.heappop(self.queue)

    def _update(self, point: Point) -> None:
        if point != self.goal:
            self.rhs[point] = min(
                (self._cost(point, neighbor) + self._g(neighbor) for neighbor in self.grid.neighbors(point)),
                default=math.inf,
            )
        self.entries.pop(point, None)
        if not math.isclose(self._g(point), self._rhs(point), rel_tol=1e-12, abs_tol=1e-12):
            self._push(point, self._key(point))

    def _compute(self) -> bool:
        limit = self.grid.width * self.grid.height * 20
        while True:
            if self.should_stop is not None and self.expanded % 256 == 0 and self.should_stop():
                raise PlanningCancelled("planning cancelled")
            self._discard()
            top = (self.queue[0][0], self.queue[0][1]) if self.queue else (math.inf, math.inf)
            if not (
                top < self._key(self.start)
                or not math.isclose(
                    self._rhs(self.start), self._g(self.start), rel_tol=1e-12, abs_tol=1e-12
                )
            ):
                return math.isfinite(self._g(self.start)) or math.isfinite(self._rhs(self.start))
            if self.expanded >= limit or not self.queue:
                return False
            old_key_1, old_key_2, _, current = heapq.heappop(self.queue)
            self.entries.pop(current, None)
            old_key = (old_key_1, old_key_2)
            new_key = self._key(current)
            if old_key < new_key:
                self._push(current, new_key)
                continue
            if self._g(current) > self._rhs(current):
                self.g[current] = self._rhs(current)
                for predecessor in self.grid.neighbors(current):
                    self._update(predecessor)
            else:
                self.g[current] = math.inf
                self._update(current)
                for predecessor in self.grid.neighbors(current):
                    self._update(predecessor)
            self.expanded += 1

    def plan(self) -> list[Point]:
        if (
            not self.grid.traversable(self.start)
            or not self.grid.traversable(self.goal)
            or not self._compute()
        ):
            return []
        current, path = self.start, [self.start]
        visited = {current}
        for _ in range(self.grid.width * self.grid.height):
            if current == self.goal:
                return path
            candidates = [neighbor for neighbor in self.grid.neighbors(current) if neighbor not in visited]
            if not candidates:
                return []
            nxt = min(
                candidates,
                key=lambda neighbor: (
                    self._cost(current, neighbor) + self._g(neighbor),
                    self._heuristic(neighbor, self.goal),
                    neighbor,
                ),
            )
            if not math.isfinite(self._cost(current, nxt) + self._g(nxt)):
                return []
            path.append(nxt)
            visited.add(nxt)
            current = nxt
        return []
