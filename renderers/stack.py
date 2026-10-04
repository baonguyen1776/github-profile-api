from __future__ import annotations

import hashlib
from html import escape

from renderers.shared import CARD_WIDTH, MONO, SANS, svg_text
from services.languages import LanguageReport, LanguageRow


COLORS = {
    "TypeScript": "#3178c6", "C++": "#f34b7d", "Python": "#488fbe",
    "JavaScript": "#f1e05a", "HTML": "#e34c26", "CSS": "#8963ce",
    "C": "#a2a8b0", "C#": "#ad73e2", "Java": "#e08039", "Go": "#00add8",
    "Rust": "#dea584", "Shell": "#89e051", "CMake": "#67c19d",
    "Jupyter Notebook": "#ec8d37", "Swift": "#f05138", "Kotlin": "#a97bff",
    "Dart": "#0175c2", "Other": "#768d9e",
}
FALLBACK_COLORS = ("#53b9ba", "#af88d8", "#d99b69", "#76b379")
PALETTES = {
    "dark": dict(bg="#081c20", panel="#092b2e", border="#146a68", ink="#d5faf2", muted="#79b5b0", accent="#25d0b4", track="#234648"),
    "light": dict(bg="#ffffff", panel="#eff8f7", border="#d7e3e8", ink="#24292f", muted="#617a85", accent="#087a67", track="#d0e2e4"),
}


def language_color(name: str) -> str:
    return COLORS.get(name) or FALLBACK_COLORS[hashlib.sha256(name.encode()).digest()[0] % len(FALLBACK_COLORS)]


def _animation_css() -> str:
    return """@media (prefers-reduced-motion:no-preference) {
@keyframes stack-fill {from {transform:scaleX(0)} to {transform:scaleX(1)}}
.usage-bar {transform-box:fill-box;transform-origin:left center;animation:stack-fill 1.3s ease-out 1 both}
}"""


def _counter(row: LanguageRow, x: float, y: float, color: str) -> str:
    return f'<text class="final-count" x="{x}" y="{y}" text-anchor="end" font-family="{MONO}" font-size="15" font-weight="700" fill="{color}">{row.percentage:.1f}%</text>'


def render_stack_svg(*, report: LanguageReport, rows: list[LanguageRow], theme: str) -> str:
    p = PALETTES[theme]
    panel_y = 102
    row_start = 170
    row_gap = 38
    height = max(286, row_start + max(1, len(rows)) * row_gap + 56)
    description = '; '.join(f'{row.name}: {row.percentage:.1f}%' for row in rows) or 'No language data in public repositories.'
    parts = [f'''<svg xmlns="http://www.w3.org/2000/svg" width="{CARD_WIDTH}" height="{height}" viewBox="0 0 {CARD_WIDTH} {height}" role="img" aria-labelledby="title desc">
<title id="title">Language Usage — @{escape(report.username)}</title>
<desc id="desc">Owned public repositories, excluding forks. Code bytes by language: {escape(description)}</desc>
<style>{_animation_css()}</style>
<rect x="1" y="1" width="1098" height="{height-2}" rx="20" fill="{p['bg']}" stroke="{p['border']}" stroke-width="1.5"/>
<text x="48" y="49" font-family="{SANS}" font-size="28" font-weight="800" fill="{p['ink']}">Language Usage</text>
{svg_text(48, 74, 'CODE-BYTE SHARE / OWNED PUBLIC REPOSITORIES', 10, p['muted'], 'letter-spacing="1.6"')}
{svg_text(1052, 49, '@' + report.username, 12, p['muted'], 'text-anchor="end"')}
<path d="M48 88H1052" stroke="{p['border']}"/>
<rect x="32" y="{panel_y}" width="1036" height="{height-panel_y-30}" rx="19" fill="{p['panel']}" stroke="{p['border']}" stroke-opacity=".7"/>
''']
    for index, row in enumerate(rows):
        y = row_start + index * row_gap
        color = ({"JavaScript": "#8a7100", "C": "#65717c", "CMake": "#247765"}.get(row.name, language_color(row.name)) if theme == "light" else language_color(row.name))
        parts.append(f'<g data-usage="{escape(row.name, quote=True)}"><title>{escape(row.name)}: {row.percentage:.1f}% · {row.code_bytes:,} bytes</title><circle cx="65" cy="{y-5}" r="4" fill="{color}"/>')
        parts.append(svg_text(82, y, row.name[:24], 14, p['ink'], 'font-weight="600"'))
        parts.append(_counter(row, 350, y, color))
        parts.append(f'<rect x="380" y="{y-12}" width="654" height="9" rx="4.5" fill="{p["track"]}"/>')
        if row.tenths:
            parts.append(f'<rect class="usage-bar" x="380" y="{y-12}" width="{654*row.tenths/1000:.3f}" height="9" rx="4.5" fill="{color}"/>')
        parts.append('</g>')
    if not rows:
        parts.append(svg_text(62, row_start, 'Add code to a public repository to populate this card.', 14, p['muted']))
    parts.append(svg_text(48, height - 12, f'{report.repositories_scanned} repositories scanned · forks excluded', 10, p['muted']))
    parts.append(svg_text(1052, height - 12, 'GITHUB / LIVE DATA', 9, p['muted'], 'text-anchor="end" letter-spacing="1"'))
    parts.append('</svg>')
    return ''.join(parts)
