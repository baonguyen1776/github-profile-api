from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache
from html import escape

from renderers.shared import CARD_WIDTH, SANS, svg_text
from services.contributions import ContributionReport


PALETTES = {
    'dark': {'bg': '#0d1117', 'panel': '#161b22', 'border': '#30363d', 'ink': '#e6edf3', 'muted': '#8b949e', 'accent': '#8cb8ff', 'cells': ('#242a32', '#0e4429', '#006d32', '#26a641', '#39d353'), 'snake': '#88dfe0', 'head': '#f2c879', 'eye': '#161b22'},
    'light': {'bg': '#ffffff', 'panel': '#f6f8fa', 'border': '#d0d7de', 'ink': '#1f2328', 'muted': '#656d76', 'accent': '#2563eb', 'cells': ('#ebedf0', '#9be9a8', '#40c463', '#30a14e', '#216e39'), 'snake': '#326cb1', 'head': '#bd7c16', 'eye': '#ffffff'},
}
GRID_X = 112
GRID_Y = 280
SNAKE_LENGTH = 7
DEFAULT_ANIMATION_SECONDS = 18


def snake_route(columns: int) -> list[tuple[int, int]]:
    """A closed, nonintersecting sweep; every move is one neighboring grid cell."""
    if columns < 1:
        raise ValueError('Snake needs at least one column')
    points = []
    for column in range(columns):
        for row in (range(7) if column % 2 == 0 else range(6, -1, -1)):
            points.append((column, row))
    end_column, end_row = points[-1]
    outside_row = 7 if end_row == 6 else -1
    points.append((end_column, outside_row))
    points.extend((column, outside_row) for column in range(end_column - 1, -2, -1))
    step = -1 if outside_row > 0 else 1
    points.extend((-1, row) for row in range(outside_row + step, step, step))
    points.append((0, 0))
    return points


def grid_geometry(
    report: ContributionReport,
    *,
    grid_width: float = 930,
    max_pitch: float = 17,
) -> tuple[int, float, dict[date, tuple[int, int]]]:
    first = date(report.year, 1, 1) if report.year is not None else report.days[0].date
    last = date(report.year, 12, 31) if report.year is not None else report.as_of
    grid_days = [first + timedelta(days=index) for index in range((last - first).days + 1)]
    # GitHub weeks begin Sunday: Python Monday=0 -> Sunday=0.
    first_weekday = (first.weekday() + 1) % 7
    columns = (first_weekday + len(grid_days) + 6) // 7
    pitch = min(max_pitch, grid_width / columns)
    positions = {}
    for index, day in enumerate(grid_days):
        column, row = divmod(first_weekday + index, 7)
        positions[day] = (column, row)
    return columns, pitch, positions


def animation_css(
    route: list[tuple[int, int]],
    pitch: float,
    seconds: int,
    *,
    origin_x: float = GRID_X,
    origin_y: float = GRID_Y,
) -> str:
    return _animation_css_cached(tuple(route), pitch, seconds, origin_x, origin_y)


@lru_cache(maxsize=32)
def _animation_css_cached(
    route: tuple[tuple[int, int], ...],
    pitch: float,
    seconds: int,
    origin_x: float,
    origin_y: float,
) -> str:
    count = len(route) - 1
    if count <= 0:
        raise ValueError('Snake route must contain a closed path')

    # One shared animation keeps every segment on the exact same closed path.
    # The final frame equals the first, so infinite replay has no pause or jump.
    frames: list[str] = []
    for index in range(count + 1):
        column, row = route[index]
        x, y = origin_x + column * pitch, origin_y + row * pitch
        progress = 100 * index / count
        frames.append(f'{progress:.5f}%{{transform:translate({x:.3f}px,{y:.3f}px)}}')

    rules = [
        '.snake-part{display:none}',
        '@media(prefers-reduced-motion:no-preference){',
        '@keyframes snake-travel{' + ''.join(frames) + '}',
    ]
    for segment in range(SNAKE_LENGTH):
        phase = ((count - segment) % count) / count
        delay = -seconds * phase
        rules.append(
            f'.snake-{segment}'
            + '{display:inline;will-change:transform;'
            + f'animation:snake-travel {seconds}s linear {delay:.6f}s infinite'
            + '}'
        )
    rules.append('@keyframes live-dot{0%,100%{opacity:.45}50%{opacity:1}}.live-dot{animation:live-dot 2.5s ease-in-out infinite}')
    rules.append('}')
    return ''.join(rules)


def render_contributions_svg(
    *,
    report: ContributionReport,
    theme: str,
    animate: bool = True,
    seconds: int = DEFAULT_ANIMATION_SECONDS,
    section: str = "full",
) -> str:
    if not report.days:
        raise ValueError('Contribution report must contain dated cells')
    if report.year is not None:
        from renderers.contribution_profile import render_profile_contributions
        return render_profile_contributions(report=report, theme=theme, animate=animate, seconds=seconds, section=section)
    p = PALETTES[theme]
    columns, pitch, positions = grid_geometry(report)
    route = snake_route(columns)
    css = animation_css(route, pitch, seconds) if animate else '.snake-part{display:none}'
    start, end = report.days[0].date.isoformat(), report.as_of.isoformat()
    height = 824 if report.year is not None else 480
    title = f'Contributions / {report.year}' if report.year is not None else 'Contribution Trail'
    historical = report.year is not None and report.today is not None and report.as_of < report.today
    description = f'{start} to {end}: {report.total} contributions, {report.active_days} active days, current streak {report.current_streak} days, longest streak {report.longest_streak} days within this window. A day with no contributions today keeps yesterday\'s streak open. Calendar dates follow GitHub. The snake is decorative; counts do not change.'
    if historical:
        description = description.replace('current streak', 'year-end streak').replace(" A day with no contributions today keeps yesterday's streak open.", '')
    parts = [f'''<svg xmlns="http://www.w3.org/2000/svg" width="{CARD_WIDTH}" height="{height}" viewBox="0 0 {CARD_WIDTH} {height}" role="img" aria-labelledby="title desc">
<title id="title">{title} — @{escape(report.username)}</title>
<desc id="desc">{escape(description)}</desc>
<style>{css}</style>
<rect x="1" y="1" width="1098" height="{height-2}" rx="20" fill="{p['bg']}" stroke="{p['border']}" stroke-width="1.5"/>
<text x="48" y="49" font-family="{SANS}" font-size="28" font-weight="800" fill="{p['ink']}">{title}</text>
{svg_text(48, 74, 'SHOW UP. BUILD SOMETHING. REPEAT.', 10, p['muted'], 'letter-spacing="1.6"')}
{svg_text(1052, 49, '@' + report.username, 12, p['muted'], 'text-anchor="end"')}
<path d="M48 88H1052" stroke="{p['border']}"/>
''']
    stats = [
        (f'{report.total:,}', 'Contributions', f'Calendar year {report.year}' if report.year is not None else 'Last 365 days'),
        (str(report.current_streak), 'Year-end streak' if historical else 'Current streak', 'Consecutive active days'),
        (str(report.longest_streak), 'Longest streak', 'Within this year' if report.year is not None else 'Within this window'),
        (str(report.active_days), 'Active days', 'Days with contributions'),
    ]
    for index, (value, label, detail) in enumerate(stats):
        x = 48 + index * 255
        parts.append(f'<rect x="{x}" y="106" width="238" height="92" rx="13" fill="{p["panel"]}" stroke="{p["border"]}" stroke-opacity=".65"/>')
        parts.append(svg_text(x + 18, 145, value, 29, p['accent'], 'font-weight="800"'))
        parts.append(f'<text x="{x+18}" y="166" font-family="{SANS}" font-size="13" font-weight="700" fill="{p["ink"]}">{label}</text>')
        parts.append(svg_text(x + 18, 185, detail, 9, p['muted']))
    parts.append(f'<rect x="32" y="220" width="1036" height="227" rx="19" fill="{p["panel"]}" stroke="{p["border"]}" stroke-opacity=".7"/>')
    previous_month = None
    previous_label_column = -10
    for day in positions:
        column, row = positions[day]
        month = (day.year, day.month)
        if month != previous_month:
            if column - previous_label_column >= 3:
                parts.append(svg_text(GRID_X + column * pitch - 6, 253, day.strftime('%b'), 11, p['muted']))
                previous_label_column = column
            previous_month = month
    for row, label in ((1, 'Mon'), (3, 'Wed'), (5, 'Fri')):
        parts.append(svg_text(88, GRID_Y + row * pitch + 4, label, 10, p['muted'], 'text-anchor="end"'))
    for item in report.days:
        col, r = positions[item.date]
        pos_x, pos_y = GRID_X + col * pitch, GRID_Y + r * pitch
        tile = pitch - 4
        parts.append(f'<rect data-date="{item.date}" data-count="{item.count}" data-level="{item.level}" x="{pos_x-tile/2:.3f}" y="{pos_y-tile/2:.3f}" width="{tile:.3f}" height="{tile:.3f}" rx="2.5" fill="{p["cells"][item.level]}"><title>{item.date}: {item.count} contribution{"s" if item.count != 1 else ""}</title></rect>')
    for day, (column, row) in positions.items():
        if day <= report.as_of:
            continue
        fut_x, fut_y, fut_tile = GRID_X + column * pitch, GRID_Y + row * pitch, pitch - 4
        parts.append(f'<rect data-future-date="{day}" x="{fut_x-fut_tile/2:.3f}" y="{fut_y-fut_tile/2:.3f}" width="{fut_tile:.3f}" height="{fut_tile:.3f}" rx="2.5" fill="{p["cells"][0]}" opacity=".35"><title>{day}: Future date</title></rect>')
    parts.append('<g aria-hidden="true" data-snake="true">')
    for segment in reversed(range(SNAKE_LENGTH)):
        column, row = route[(-segment) % (len(route) - 1)]
        seg_x, seg_y = GRID_X + column * pitch, GRID_Y + row * pitch
        size = (pitch - 2) if segment == 0 else (pitch - 4) * (1 - segment * .055)
        color = p['head'] if segment == 0 else p['snake']
        opacity = 1 - segment * .08
        parts.append(f'<g class="snake-part snake-{segment}" data-segment="{segment}" transform="translate({seg_x:.3f},{seg_y:.3f})"><rect x="{-size/2:.3f}" y="{-size/2:.3f}" width="{size:.3f}" height="{size:.3f}" rx="3.5" fill="{color}" opacity="{opacity:.2f}"/>')
        if segment == 0:
            parts.append(f'<circle cx="-3" cy="-2" r="1.3" fill="{p["eye"]}"/><circle cx="3" cy="-2" r="1.3" fill="{p["eye"]}"/>')
        parts.append('</g>')
    parts.append('</g>')
    parts.append(svg_text(62, 428, f'{start} to {end}', 10, p['muted']))
    parts.append(f'<circle class="live-dot" cx="505" cy="424" r="3" fill="{p["accent"]}"/>')
    parts.append(svg_text(518, 428, f'SNAKE REPLAY / {seconds}s' if animate else 'STATIC CALENDAR', 9, p['muted'], 'letter-spacing=".8"'))
    parts.append(svg_text(850, 428, 'Less', 10, p['muted'], 'text-anchor="end"'))
    for level in range(5):
        parts.append(f'<rect x="{866+level*19}" y="417" width="12" height="12" rx="2" fill="{p["cells"][level]}"/>')
    parts.append(svg_text(974, 428, 'More', 10, p['muted']))
    parts.append(svg_text(48, 466, 'GITHUB CALENDAR · contributions include more than commits', 9, p['muted']))
    parts.append(svg_text(1052, 466, 'LIVE DATA / ' + ('PUBLIC PROFILE' if report.source == 'github-public-calendar' else 'GRAPHQL'), 9, p['muted'], 'text-anchor="end" letter-spacing=".6"'))
    parts.append('</svg>')
    return ''.join(parts)
