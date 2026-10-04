from __future__ import annotations

from collections.abc import Mapping
from html import escape
from typing import Any
from urllib.parse import urlencode

from services.contribution_overview import ContributionOverview, ProjectContribution
from services.contributions import ContributionReport
from renderers.contributions import DEFAULT_ANIMATION_SECONDS, PALETTES, grid_geometry
from renderers.snake import plan_snake, snake_css, snake_markup


WIDTH, HEIGHT = 850, 502
GRID_X, GRID_Y = 74, 80
FONT = '-apple-system,BlinkMacSystemFont,Segoe UI,Arial,Helvetica,sans-serif'


def text(x: float, y: float, content: object, size: float, color: Any, extra: str = '') -> str:
    return f'<text x="{x}" y="{y}" font-family="{FONT}" font-size="{size}" fill="{color}" {extra}>{escape(str(content))}</text>'


def activity_ratios(activity: Mapping[str, int | None]) -> dict[str, float | None]:
    """Unavailable axes stay unknown; shares use only supplied event counts."""
    total = sum(value for value in activity.values() if value is not None)
    return {key: (None if value is None else value / total if total else 0) for key, value in activity.items()}


def render_activity(report: ContributionReport, p: Mapping[str, Any]) -> str:
    overview = report.overview or ContributionOverview()
    activity = overview.activity or {kind: None for kind in ('reviews', 'issues', 'pull_requests', 'commits')}
    ratios = activity_ratios(activity)
    cx, cy, radius = 646, 326, 68
    green = p.get('graph', '#1a7f37')
    axes = [('reviews', 0, -1, 'Code review', 646, 227, 'middle'),
            ('issues', 1, 0, 'Issues', 732, 321, 'start'),
            ('pull_requests', 0, 1, 'Pull requests', 646, 413, 'middle'),
            ('commits', -1, 0, 'Commits', 560, 321, 'end')]
    points: dict[str, tuple[float, float]] = {}
    parts: list[str] = ['<g aria-label="Activity shares among known contributions">']
    for fraction in (.25,.5,.75,1):
        r = radius*fraction
        parts.append(f'<path data-radar-grid="{fraction}" d="M{cx} {cy-r}L{cx+r} {cy}L{cx} {cy+r}L{cx-r} {cy}Z" fill="none" stroke="{p["border"]}" stroke-width=".8"/>')
        if fraction < 1:
            parts.append(text(cx+4,cy-r-2,f'{fraction:.0%}',7,p['muted']))
    for kind, dx, dy, _label, _x, _y, _anchor in axes:
        ratio = ratios.get(kind)
        if ratio is not None:
            points[kind] = (cx + dx * radius * ratio, cy + dy * radius * ratio)
    # With a missing category, leave its sectors unfilled instead of drawing a
    # zero-valued vertex and implying that unknown activity never happened.
    known_points = [points[kind] for kind, *_ in axes if kind in points]
    if len(known_points) >= 3:
        polygon = ' '.join(f'{px:.3f},{py:.3f}' for px, py in known_points)
        parts.append(f'<polygon data-activity-polygon="known" points="{polygon}" fill="{green}" fill-opacity=".18" stroke="{green}" stroke-width="1.5"/>')
    for kind, dx, dy, label, x, y, anchor in axes:
        ratio = ratios.get(kind)
        amount = activity.get(kind)
        known = ratio is not None and amount is not None
        style = '' if known else ' stroke-dasharray="3 3"'
        parts.append(f'<path data-activity-axis="{kind}" data-known="{str(known).lower()}" d="M{cx} {cy}l{dx*radius} {dy*radius}" stroke="{green if known else p["muted"]}" stroke-width="1.5"{style}/>')
        value = f'{amount:,} · {ratio:.0%}' if known else 'N/A'
        parts.append(text(x, y, value, 11, p['muted'], f'text-anchor="{anchor}"'))
        parts.append(text(x, y+15, label, 12, p['muted'], f'text-anchor="{anchor}"'))
        if known:
            px, py = points[kind]
            parts.append(f'<circle data-activity-point="{kind}" cx="{px:.3f}" cy="{py:.3f}" r="2.8" fill="{p["bg"]}" stroke="{green}" stroke-width="1.6"><title>{escape(label)}: {activity[kind]} ({ratio:.1%} of known activity)</title></circle>')
        else:
            ux, uy = cx + dx * radius, cy + dy * radius
            parts.append(f'<circle data-activity-unavailable="{kind}" cx="{ux:.3f}" cy="{uy:.3f}" r="4" fill="{p["bg"]}" stroke="{p["muted"]}" stroke-width="1.2" stroke-dasharray="2 2"><title>{escape(label)} data unavailable</title></circle>')
    parts.append('</g>')
    return ''.join(parts)



def avatar_markup(project: ProjectContribution, x: float, y: float, size: float, p: Mapping[str, Any]) -> str:
    if project.avatar_data_uri:
        return f'<image href="{project.avatar_data_uri}" x="{x}" y="{y}" width="{size}" height="{size}" preserveAspectRatio="xMidYMid slice"/>'
    return f'<rect x="{x}" y="{y}" width="{size}" height="{size}" rx="4" fill="{p["border"]}"/>'+text(x+size/2,y+size*.73,project.name[0].upper(),size*.6,p['ink'],'text-anchor="middle"')


def render_repo_chips(report: ContributionReport, p: Mapping[str, Any], theme: str) -> str:
    projects = list(report.overview.projects if report.overview else ())
    parts: list[str] = []

    def href(repo: str | None) -> str:
        return escape('/preview/contributions?'+urlencode({'username':report.username,'year':report.year,'theme':theme,**({'repo':repo} if repo else {})}),quote=True)
    all_active = not report.repository
    parts.append(f'<a href="{href(None)}"><rect x="20" y="225" width="48" height="28" rx="6" fill="{"#0969da" if all_active else p["panel"]}" stroke="{p["border"]}"/>{text(44,243,"All",12,"#ffffff" if all_active else p["ink"],"text-anchor=\"middle\"")}</a>')
    for index,project in enumerate(projects[:3]):
        x = 77+index*197
        selected = report.repository and report.repository.casefold()==project.name.casefold()
        label = project.short_name[:23]+('…' if len(project.short_name)>23 else '')
        parts.append(f'<a data-repo-filter="{escape(project.name)}" href="{href(project.name)}"><rect x="{x}" y="225" width="187" height="28" rx="6" fill="{"#0969da" if selected else p["panel"]}" stroke="{"#0969da" if selected else p["border"]}"/>{avatar_markup(project,x+6,230,18,p)}{text(x+31,243,label,11,"#ffffff" if selected else p["ink"])}</a>')
    if len(projects)>3:
        parts.append(text(674,243,f'+ {len(projects)-3} more',11,p['muted']))
    return ''.join(parts)

def render_profile_contributions(
    *,
    report: ContributionReport,
    theme: str,
    animate: bool = True,
    seconds: int = DEFAULT_ANIMATION_SECONDS,
    section: str = "full",
) -> str:
    base_theme = 'light' if theme == 'auto' else theme
    p: dict[str, Any] = dict(PALETTES[base_theme])
    p['graph'] = '#1a7f37' if base_theme == 'light' else '#3fb950'
    theme_css = ''
    if theme == 'auto':
        def declarations(name: str) -> str:
            values = dict(PALETTES[name])
            values['graph'] = '#1a7f37' if name == 'light' else '#3fb950'
            return ''.join(f'--c-{key}:{value};' for key,value in values.items() if key != 'cells') + ''.join(f'--c-cell-{i}:{value};' for i,value in enumerate(values['cells']))
        theme_css = ':root{'+declarations('light')+'}@media(prefers-color-scheme:dark){:root{'+declarations('dark')+'}}'
        p = {key: f'var(--c-{key})' for key in p if key != 'cells'}
        p['cells'] = tuple(f'var(--c-cell-{i})' for i in range(5))
    overview = report.overview or ContributionOverview()
    columns, pitch, positions = grid_geometry(report, grid_width=715, max_pitch=13.5)
    origin_x = GRID_X
    plan = plan_snake(columns, tuple((*positions[day.date], day.level) for day in report.days if day.level > 0)) if animate and section != 'activity' else None
    duration = plan.duration(seconds) if plan else seconds
    css = snake_css(plan, pitch, duration, origin_x, GRID_Y) if plan else '.snake-part{display:none}'
    historical = report.today is not None and report.as_of < report.today
    streak_label = 'Year-end streak' if historical else 'Current streak'
    title = f'{report.total:,} contributions in {report.year}' if not report.repository else f'{report.total:,} commits in {report.repository.split("/")[-1]} · {report.year}'
    description = f'{report.days[0].date} to {report.as_of}: {report.total} contributions, {report.active_days} active days, {streak_label.lower()} {report.current_streak} days, longest streak {report.longest_streak} days within this year. {overview.message} Activity percentages use known events. The snake eats levels 1 through 4; eaten cells return together when it reaches home. Contribution counts remain unchanged.'
    view_y, view_height = (0,210) if section == 'calendar' else (262,240) if section == 'activity' else (0,HEIGHT)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{view_height}" viewBox="0 {view_y} {WIDTH} {view_height}" role="img" aria-labelledby="title desc"><title id="title">{escape(title)} — @{escape(report.username)}</title><desc id="desc">{escape(description)}</desc><style>{theme_css}{css}</style>']
    parts.append(f'<rect width="{WIDTH}" height="{HEIGHT}" fill="{p["bg"]}"/>')
    parts.append(text(1, 22, title, 16, p['ink']))
    parts.append(text(830, 22, '@'+report.username, 11, p['muted'], 'text-anchor="end"'))
    parts.append(f'<rect x=".5" y="37.5" width="849" height="464" rx="6" fill="none" stroke="{p["border"]}"/>')
    previous_month = None
    for day, (column, _row) in positions.items():
        if day.month != previous_month:
            parts.append(text(origin_x+column*pitch-5, 61, day.strftime('%b'), 11, p['muted']))
            previous_month = day.month
    for row, label in ((1,'Mon'),(3,'Wed'),(5,'Fri')):
        parts.append(text(origin_x-24, GRID_Y+row*pitch+4, label, 11, p['muted'], 'text-anchor="end"'))
    tile = pitch-3.5
    for item in report.days:
        col, row = positions[item.date]
        x, y = origin_x+col*pitch, GRID_Y+row*pitch
        if plan and item.level > 0:
            parts.append(f'<rect x="{x-tile/2:.3f}" y="{y-tile/2:.3f}" width="{tile:.3f}" height="{tile:.3f}" rx="1.5" fill="{p["cells"][0]}" stroke="{p["border"]}" stroke-width=".35"/>')
        food_class = f'food-{col}-{row}' if item.level > 0 else ''
        parts.append(f'<rect class="{food_class}" data-date="{item.date}" data-count="{item.count}" data-level="{item.level}" x="{x-tile/2:.3f}" y="{y-tile/2:.3f}" width="{tile:.3f}" height="{tile:.3f}" rx="1.5" fill="{p["cells"][item.level]}" stroke="{p["border"]}" stroke-width=".35"><title>{item.date}: {item.count} contributions</title></rect>')
    for day, (col, row) in positions.items():

        if day > report.as_of:
            parts.append(f'<rect data-future-date="{day}" x="{origin_x+col*pitch-tile/2:.3f}" y="{GRID_Y+row*pitch-tile/2:.3f}" width="{tile:.3f}" height="{tile:.3f}" rx="1.5" fill="{p["cells"][0]}" opacity=".4"><title>{day}: Future date</title></rect>')
    if plan:
        parts.append(snake_markup(plan, pitch, origin_x, GRID_Y, p['snake']))
    parts.append(text(20, 192, f'{report.days[0].date:%b %d} – {report.days[-1].date:%b %d, %Y}', 11, p['muted']))
    parts.append(text(802, 192, 'More', 11, p['muted']))
    parts.append(text(708, 192, 'Less', 11, p['muted'], 'text-anchor="end"'))
    for level in range(5):
        parts.append(f'<rect x="{716+level*15}" y="183" width="10" height="10" rx="2" fill="{p["cells"][level]}"/>')
    parts.append(f'<path d="M1 209.5H849M1 262H849" stroke="{p["border"]}"/>')
    parts.append(render_repo_chips(report,p,theme))
    parts.append('<g transform="translate(0 52)">')
    parts.append(f'<path d="M455 230V430" stroke="{p["border"]}"/>')
    parts.append(text(20, 240, 'Activity in '+report.repository.split('/')[-1] if report.repository else 'Activity overview', 14, p['ink']))
    parts.append(f'<g transform="translate(20 260)" fill="none" stroke="{p["muted"]}" stroke-width="1.2"><rect x="1" y="0" width="10" height="12" rx="1"/><path d="M3 3h5M3 6h5M3 12v3l2-1 2 1v-3"/></g>')
    parts.append(text(40, 273, 'Contributed to', 13, p['ink']))
    for index, project in enumerate(overview.projects[:3]):
        label = project.short_name if len(project.short_name) <= 40 else project.short_name[:37]+'...'
        y = 284 + index * 34
        parts.append(f'<a data-project-button="true" href="{escape(project.url, quote=True)}" target="_blank" rel="noopener noreferrer"><title>{escape(project.name)}: {project.total} known contributions</title><rect x="40" y="{y}" width="394" height="28" rx="6" fill="{p["panel"]}" stroke="{p["border"]}"/>{avatar_markup(project,49,y+5,18,p)}{text(75, y+18, label, 11, p["ink"], "font-weight=\"600\"")}</a>')
    if overview.projects:
        remaining = len(overview.projects)-3
        if remaining > 0:
            parts.append(text(40, 396, f'and {remaining} other repositories', 12, p['ink']))
    else:
        parts.append(text(40, 299, 'No visible repository details for this year.', 12, p['muted']))
    parts.append(text(20, 420, f'{streak_label}: {report.current_streak}d · Longest: {report.longest_streak}d · Active days: {report.active_days}', 10, p['muted']))
    note = 'Code review is unavailable · percentages use known activity only' if (overview.activity or {}).get('reviews') is None else 'Shares of known activity · calendar includes other types'
    if overview.status == 'unavailable':
        note = 'Activity details unavailable · calendar data is available'
    parts.append(text(20, 440, note, 10, p['muted']))
    parts.append(render_activity(report, p))
    parts.append('</g></svg>')
    return ''.join(parts)
