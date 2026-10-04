"""Plan a food-driven snake once, then render a self-contained SVG animation."""
from __future__ import annotations

from collections import deque
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from functools import lru_cache
from heapq import heappop, heappush
from itertools import count

Point = tuple[int, int]
Body = tuple[Point, ...]
SNAKE_LENGTH = 4


@dataclass(frozen=True)
class SnakePlan:
    route: tuple[Point, ...]
    meals: tuple[tuple[Point, int], ...]

    def duration(self, minimum: float) -> float:
        # Dense calendars get longer cycles instead of an unreadably fast snake.
        return max(minimum, (len(self.route) - 1) * .1)


def _neighbors(point: Point, columns: int) -> Iterator[Point]:
    x, y = point
    for nx, ny in ((x - 1, y), (x, y + 1), (x + 1, y), (x, y - 1)):
        # One empty lane surrounds the calendar. It lets the snake route around
        # contribution cells without treating uneaten food as walkable ground.
        if -1 <= nx <= columns and -1 <= ny <= 7:
            yield nx, ny


def _advance(body: Body, point: Point) -> Body | None:
    if point in body[:-1]:
        return None
    return (point,) + body[:-1]


def _follow(body: Body, path: Sequence[Point]) -> Body | None:
    for point in path:
        moved = _advance(body, point)
        if moved is None:
            return None
        body = moved
    return body


def _grid_path(
    body: Body,
    targets: set[Point],
    columns: int,
    obstacles: set[Point] | None = None,
) -> list[Point] | None:
    """BFS between cells, treating the current body (except its tail) as blocked."""
    queue = deque([body[0]])
    previous: dict[Point, Point | None] = {body[0]: None}
    blocked = set(body[:-1]) | (obstacles or set())
    blocked -= targets
    while queue:
        point = queue.popleft()
        if point in targets:
            path = []
            parent = previous[point]
            while parent is not None:
                path.append(point)
                point = parent
                parent = previous[point]
            return path[::-1]
        for neighbor in _neighbors(point, columns):
            if neighbor not in blocked and neighbor not in previous:
                previous[neighbor] = point
                queue.append(neighbor)
    return None


def _position_path(
    start: Point,
    targets: set[Point],
    columns: int,
    obstacles: set[Point],
) -> list[Point] | None:
    """Cheap reachability check that ignores the moving body, not food walls."""
    queue = deque([start])
    previous: dict[Point, Point | None] = {start: None}
    while queue:
        point = queue.popleft()
        if point in targets:
            path = []
            parent = previous[point]
            while parent is not None:
                path.append(point)
                point = parent
                parent = previous[point]
            return path[::-1]
        for neighbor in _neighbors(point, columns):
            if neighbor not in obstacles and neighbor not in previous:
                previous[neighbor] = point
                queue.append(neighbor)
    return None


def _path(
    body: Body,
    targets: set[Point],
    columns: int,
    obstacles: set[Point] | None = None,
    finish: Sequence[Point] | None = None,
) -> list[Point]:
    obstacles = obstacles or set()

    def acceptable(state: Body) -> bool:
        if state[0] not in targets:
            return False
        if finish is not None:
            return _follow(state, finish) is not None
        # Ensure food walls do not seal the head away from the outer lane. Body
        # motion is handled by A* itself and must not fail this topology check.
        outer = {(x, y) for x in range(-1, columns + 1) for y in (-1, 7)}
        outer.update({(-1, y) for y in range(8)})
        outer.update({(columns, y) for y in range(8)})
        return _position_path(state[0], outer, columns, obstacles) is not None

    quick = _grid_path(body, targets, columns, obstacles)
    if quick is not None:
        state = _follow(body, quick)
        if state is not None and acceptable(state):
            return quick

    # A moving tail can unlock a route that static BFS cannot see. A* searches
    # complete body states here; Manhattan distance is an admissible heuristic.
    def distance(point: Point) -> int:
        return min(abs(point[0] - x) + abs(point[1] - y) for x, y in targets)

    serial = count()
    queue = [(distance(body[0]), 0, next(serial), body)]
    costs = {body: 0}
    parents: dict[Body, Body] = {}
    while queue:
        _, cost, _, state = heappop(queue)
        if costs[state] != cost:
            continue
        if acceptable(state):
            path = []
            while state != body:
                path.append(state[0])
                state = parents[state]
            return path[::-1]
        for neighbor in _neighbors(state[0], columns):
            if neighbor in obstacles and neighbor not in targets:
                continue
            moved = _advance(state, neighbor)
            if moved is not None and cost + 1 < costs.get(moved, float('inf')):
                costs[moved] = cost + 1
                parents[moved] = state
                heappush(queue, (cost + 1 + distance(neighbor), cost + 1, next(serial), moved))
    raise ValueError('No safe route for the contribution snake')


@lru_cache(maxsize=64)
def plan_snake(columns: int, food: tuple[tuple[int, int, int], ...]) -> SnakePlan:
    if columns < 1:
        raise ValueError('Snake needs at least one column')
    if any(not (0 <= x < columns and 0 <= y < 7 and 1 <= level <= 4) for x, y, level in food):
        raise ValueError('Food must be a dated calendar cell with level 1–4')
    body = tuple((-1, row) for row in range(SNAKE_LENGTH))
    route = [body[0]]
    meals: list[tuple[Point, int]] = []
    uneaten = {(x, y): level for x, y, level in food}

    def walk(path: Sequence[Point], remaining: set[Point] | None = None) -> None:
        nonlocal body
        for point in path:
            moved = _advance(body, point)
            if moved is None:
                raise ValueError('Snake route intersects its body')
            body = moved
            route.append(point)
            if remaining is not None and point in remaining:
                remaining.remove(point)
                meals.append((point, len(route) - 1))

    while uneaten:
        # Prefer the lowest reachable level. In a pathological dense calendar,
        # higher-level cells can completely enclose lower-level food. Opening
        # the lowest reachable cell is then necessary; we still never cross an
        # uneaten cell as if it were empty ground.
        for level in range(1, 5):
            remaining = {point for point, item_level in uneaten.items() if item_level == level}
            if not remaining:
                continue
            if body[0] in remaining:
                path: list[Point] = []
            else:
                obstacles = set(uneaten) - remaining
                reachable_path = _position_path(body[0], remaining, columns, obstacles)
                if reachable_path is None:
                    continue
                try:
                    path = _path(body, remaining, columns, obstacles)
                except ValueError:
                    continue
            before = set(remaining)
            if not path:
                remaining.remove(body[0])
                meals.append((body[0], len(route) - 1))
            else:
                walk(path, remaining)
            for point in before - remaining:
                uneaten.pop(point)
            break
        else:
            raise ValueError('No reachable contribution cell for the snake')

    if meals:
        # Enter home from below, restoring the complete initial body pose.
        # Matching just the head would make the tail jump at the loop seam.
        finish = [(-1, row) for row in range(6, -1, -1)]
        walk(_path(body, {(0, 6)}, columns, finish=finish))
        walk(finish)
    return SnakePlan(tuple(route), tuple(meals))


def snake_css(plan: SnakePlan, pitch: float, seconds: float, x: float, y: float) -> str:
    if not plan.meals:
        return '.snake-part{display:none}'
    moves = len(plan.route) - 1
    frames = ''.join(f'{100*i/moves:.6f}%{{transform:translate({x+col*pitch:.3f}px,{y+row*pitch:.3f}px)}}' for i, (col, row) in enumerate(plan.route))
    rules = ['.snake-part{display:none}', '@media(prefers-reduced-motion:no-preference){', '@keyframes snake-travel{' + frames + '}']
    for segment in range(SNAKE_LENGTH):
        delay = -seconds * ((moves - segment) % moves) / moves
        rules.append(f'.snake-{segment}{{display:inline;animation:snake-travel {seconds:g}s linear {delay:.8f}s infinite}}')
    for (col, row), step in plan.meals:
        name = f'food-{col}-{row}'
        # Discrete transition exactly when the head arrives; all cells reset at
        # the common cycle boundary, never on their own staggered timers.
        at = 100 * step / moves
        rules.append(f'@keyframes {name}{{0%{{opacity:1}}{at:.6f}%,100%{{opacity:0}}}}')
        rules.append(f'.{name}{{animation:{name} {seconds:g}s steps(1,end) infinite}}')
    rules.append('}')
    return ''.join(rules)


def snake_markup(plan: SnakePlan, pitch: float, x: float, y: float, color: str) -> str:
    if not plan.meals:
        return ''
    sizes = (1, .90, .78, .64, .49, .34, .20)
    parts = ['<g data-snake="true" aria-hidden="true">']
    for segment in reversed(range(SNAKE_LENGTH)):
        col, row = plan.route[(-segment) % (len(plan.route) - 1)]
        size = (pitch - 3.5) * sizes[segment]
        radius = min(3, size * .28)
        parts.append(f'<g data-segment="{segment}" class="snake-part snake-{segment}" transform="translate({x+col*pitch:.3f},{y+row*pitch:.3f})"><rect x="{-size/2:.3f}" y="{-size/2:.3f}" width="{size:.3f}" height="{size:.3f}" rx="{radius:.3f}" fill="{color}"/></g>')
    parts.append('</g>')
    return ''.join(parts)
