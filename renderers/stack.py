from __future__ import annotations

import base64
import hashlib
import re
import xml.etree.ElementTree as ET
from functools import lru_cache
from html import escape
from pathlib import Path

from renderers.shared import CARD_WIDTH, MONO, SANS, svg_text
from services.languages import LanguageReport, LanguageRow
from services.technologies import EDITORS, TechnologyReport, grouped_names, select_technologies


ET.register_namespace("", "http://www.w3.org/2000/svg")

ICON_DIR = Path(__file__).resolve().parents[1] / "assets/icons"
ICONS = {
    "TypeScript": "typescript", "JavaScript": "javascript", "C++": "cplusplus",
    "C": "c", "Python": "python", "HTML": "html5", "CSS": "css3",
    "C#": "csharp", "Java": "java", "Go": "go", "Rust": "rust",
    "Shell": "bash", "CMake": "cmake", "Jupyter Notebook": "jupyter",
    "Swift": "swift", "Kotlin": "kotlin",
    "React": "react", "React Native": "react", "Expo": "expo", "Vite": "vitejs",
    "Three.js": "threejs", "GSAP": "gsap", "NumPy": "numpy", "OpenCV": "opencv",
    "MediaPipe": "mediapipe", "Matplotlib": "matplotlib", "SciPy": "scipy", "JAX": "jax",
    "Next.js": "nextjs", "Vue.js": "vuejs", "Svelte": "svelte", "Express.js": "express",
    "Bootstrap": "bootstrap", "Handlebars": "handlebars", "Tailwind CSS": "tailwindcss",
    "Pandas": "pandas", "scikit-learn": "scikitlearn", "TensorFlow": "tensorflow",
    "PyTorch": "pytorch", "Jupyter": "jupyter", "FastAPI": "fastapi", "Flask": "flask",
    "Django": "django", **EDITORS,
}
COLORS = {
    "TypeScript": "#3178c6", "C++": "#f34b7d", "Python": "#488fbe",
    "JavaScript": "#f1e05a", "HTML": "#e34c26", "CSS": "#8963ce",
    "C": "#a2a8b0", "C#": "#ad73e2", "Java": "#e08039", "Go": "#00add8",
    "Rust": "#dea584", "Shell": "#89e051", "CMake": "#67c19d",
    "Jupyter Notebook": "#ec8d37", "Swift": "#f05138", "Kotlin": "#a97bff",
    "Other": "#768d9e", "React": "#087ea4", "React Native": "#20252b",
    "Expo": "#20252b", "Vite": "#7351cf", "Three.js": "#30333b", "GSAP": "#347a19",
    "NumPy": "#426fba", "OpenCV": "#42753e", "MediaPipe": "#087f8c", "Matplotlib": "#326d96",
    "SciPy": "#3768a1", "JAX": "#5e3791", "Visual Studio Code": "#287ed1",
    "IntelliJ IDEA": "#22242b", "PyCharm": "#316312",
}
FALLBACK_COLORS = ("#53b9ba", "#af88d8", "#d99b69", "#76b379")
PALETTES = {
    "dark": dict(bg="#081c20", panel="#092b2e", border="#146a68", ink="#d5faf2", muted="#79b5b0", accent="#25d0b4", track="#234648", tile="#103b40"),
    "light": dict(bg="#ffffff", panel="#eff8f7", border="#d7e3e8", ink="#24292f", muted="#617a85", accent="#087a67", track="#d0e2e4", tile="#eef4f7"),
}


def language_color(name: str) -> str:
    return COLORS.get(name) or FALLBACK_COLORS[hashlib.sha256(name.encode()).digest()[0] % len(FALLBACK_COLORS)]


@lru_cache(maxsize=128)
def _icon_data(name: str, foreground: str) -> str | None:
    slug = ICONS.get(name)
    if not slug:
        return None
    path = ICON_DIR / f"badge-{slug}.svg"
    if not path.exists():
        path = ICON_DIR / f"{slug}.svg"
    if not path.exists():
        return None
    tree = ET.fromstring(path.read_bytes())
    for node in tree.iter():
        if node.tag.rsplit('}', 1)[-1] in {'path', 'rect', 'circle', 'polygon', 'ellipse', 'polyline', 'line', 'text', 'g'}:
            if node.get('fill') != 'none':
                node.set('fill', foreground)
            if node.get('stroke') and node.get('stroke') != 'none':
                node.set('stroke', foreground)
            if node.get('style'):
                node.set('style', re.sub(r'(fill|stroke):\s*(?!none)[^;]+', lambda match: match[1] + ':' + foreground, node.get('style') or ''))
    return "data:image/svg+xml;base64," + base64.b64encode(ET.tostring(tree)).decode("ascii")


LABELS = {'HTML': 'HTML5', 'CSS': 'CSS3'}


def _badge_width(name: str) -> float:
    return min(400, max(78, 48 + len(LABELS.get(name, name)[:32]) * 8.5))


def _badge(name: str, x: float, y: float, sources: list[dict[str, str]], is_language: bool, editor: bool = False) -> str:
    color = language_color(name)
    foreground = '#20252b' if name in {'JavaScript', 'CMake', 'Rust', 'Shell'} else '#ffffff'
    attribute = 'data-language' if is_language else 'data-technology'
    if editor:
        attribute = 'data-editor'
    label = LABELS.get(name, name)[:32].upper()
    detail = name + (' — chosen by you' if editor else ' — GitHub language bytes' if is_language else ' — declared dependency')
    if sources:
        detail += ': ' + '; '.join(source['repository'] + '/' + source['path'] for source in sources)
    parts = [f'<g {attribute}="{escape(name, quote=True)}"><title>{escape(detail)}</title>']
    parts.append(f'<rect x="{x}" y="{y}" width="{_badge_width(name)}" height="34" fill="{color}"/>')
    icon = _icon_data(name, foreground)
    if icon:
        parts.append(f'<image x="{x+10}" y="{y+8}" width="18" height="18" href="{icon}"/>')
    else:
        parts.append(svg_text(x + 19, y + 22, name[:2].upper(), 10, foreground, 'text-anchor="middle" font-weight="800"'))
    parts.append(svg_text(x + 38, y + 22, label, 12, foreground, 'letter-spacing="1.2" font-weight="800"'))
    parts.append('</g>')
    return ''.join(parts)


def _animation_css() -> str:
    return """@media (prefers-reduced-motion:no-preference) {
@keyframes stack-fill {from {transform:scaleX(0)} to {transform:scaleX(1)}}
.usage-bar {transform-box:fill-box;transform-origin:left center;animation:stack-fill 1.3s ease-out 1 both}
}"""


def _counter(row: LanguageRow, x: float, y: float, color: str) -> str:
    return f'<text class="final-count" x="{x}" y="{y}" text-anchor="end" font-family="{MONO}" font-size="15" font-weight="700" fill="{color}">{row.percentage:.1f}%</text>'


def render_stack_svg(
    *, report: LanguageReport, rows: list[LanguageRow], theme: str,
    technologies: TechnologyReport | None = None,
    requested_technologies: list[str] | None = None,
    editors: list[str] | None = None,
    focus_areas: list[str] | None = None,
) -> str:
    p = PALETTES[theme]
    technologies = technologies or TechnologyReport({})
    selected = [row.name for row in rows if row.name != 'Other']
    groups = grouped_names(selected, select_technologies(technologies, requested_technologies or []))
    available_editors = {name.casefold(): name for name in EDITORS}
    editor_names = list(dict.fromkeys(available_editors[name.strip().casefold()] for name in (editors or []) if name.strip().casefold() in available_editors))
    if editor_names:
        groups.append(('IDEs / Text Editors — Your Selection', editor_names))
    badge_parts = []
    cursor = 119
    for title, names in groups:
        badge_parts.append(f'<g data-category="{escape(title, quote=True)}">')
        badge_parts.append(f'<text x="48" y="{cursor}" font-family="{SANS}" font-size="19" font-weight="700" fill="{p["ink"]}">{escape(title)}</text>')
        x, y = 48.0, cursor + 20
        for name in names:
            width = _badge_width(name)
            if x + width > 1052:
                x, y = 48.0, y + 43
            badge_parts.append(_badge(name, x, y, technologies.evidence.get(name, []), name in selected, name in editor_names))
            x += width + 8
        badge_parts.append('</g>')
        cursor = y + 72
    if not groups:
        text = 'No public language data yet' if not rows else 'Your selected languages are not present in these repositories'
        badge_parts.append(svg_text(48, cursor + 24, text, 16, p['muted']))
        cursor += 74
    focus_labels = [item.strip()[:24] for item in (focus_areas or []) if item.strip()][:4]
    x = 48
    for label in focus_labels:
        width = max(68, len(label) * 7 + 28)
        badge_parts.append(f'<rect x="{x}" y="{cursor-14}" width="{width}" height="27" rx="13.5" fill="{p["tile"]}"/>')
        badge_parts.append(svg_text(x + width / 2, cursor + 4, label, 11, p['muted'], 'text-anchor="middle"'))
        x += width + 12
    if focus_labels:
        cursor += 42
    if technologies.incomplete:
        badge_parts.append(svg_text(48, cursor, 'Dependency scan has skipped files; badges show verified declarations only.', 11, p['muted']))
        cursor += 24
    graph_y = cursor + 4
    height = graph_y + 143 + max(1, len(rows)) * 34
    extra_height = graph_y - 257
    description = '; '.join(f'{row.name}: {row.percentage:.1f}%' for row in rows) or 'No language data in public repositories.'
    group_description = '; '.join(title + ': ' + ', '.join(names) for title, names in groups)
    parts = [f'''<svg xmlns="http://www.w3.org/2000/svg" width="{CARD_WIDTH}" height="{height}" viewBox="0 0 {CARD_WIDTH} {height}" role="img" aria-labelledby="title desc">
<title id="title">Tech Stack — @{escape(report.username)}</title>
<desc id="desc">Owned public repositories, excluding forks. Manifest dependencies are declarations, not proof of proficiency. {escape(group_description)}. Code bytes by language: {escape(description)}</desc>
<defs><radialGradient id="stack-glow"><stop stop-color="{p['accent']}" stop-opacity=".06"/><stop offset="1" stop-color="{p['bg']}" stop-opacity="0"/></radialGradient></defs>
<style>{_animation_css()}</style>
<rect x="1" y="1" width="1098" height="{height-2}" rx="20" fill="{p['bg']}" stroke="{p['border']}" stroke-width="1.5"/>
<g class="stack-intro">
  <text x="48" y="49" font-family="{SANS}" font-size="28" font-weight="800" fill="{p['ink']}">Tech Stack</text>
  {svg_text(48, 74, 'GITHUB LANGUAGES + MANIFEST DEPENDENCIES', 10, p['muted'], 'letter-spacing="1.6"')}
  {svg_text(1052, 49, '@' + report.username, 12, p['muted'], 'text-anchor="end"')}
  <path d="M48 88H1052" stroke="{p['border']}"/>
  {''.join(badge_parts)}
</g>
<rect x="32" y="{graph_y}" width="1036" height="{height-graph_y-30}" rx="19" fill="{p['panel']}" stroke="{p['border']}" stroke-opacity=".7"/>
<g class="stack-content">
  <text x="62" y="{291+extra_height}" font-family="{SANS}" font-size="23" font-weight="800" fill="{p['ink']}">Language usage</text>
  {svg_text(62, 315+extra_height, 'CODE-BYTE SHARE / OWNED PUBLIC REPOSITORIES', 10, p['muted'], 'letter-spacing="1.2"')}
  {svg_text(1034, 291+extra_height, '> stack.scan', 12, p['accent'], 'text-anchor="end"')}
''']
    for index, row in enumerate(rows):
        y = 353 + extra_height + index * 34
        color = ({"JavaScript": "#8a7100", "C": "#65717c", "CMake": "#247765"}.get(row.name, language_color(row.name)) if theme == "light" else language_color(row.name))
        parts.append(f'<g data-usage="{escape(row.name, quote=True)}"><title>{escape(row.name)}: {row.percentage:.1f}% · {row.code_bytes:,} bytes</title><circle cx="65" cy="{y-5}" r="4" fill="{color}"/>')
        parts.append(svg_text(82, y, row.name[:24], 14, p['ink'], 'font-weight="600"'))
        parts.append(_counter(row, 350, y, color))
        parts.append(f'<rect x="380" y="{y-12}" width="654" height="9" rx="4.5" fill="{p["track"]}"/>')
        if row.tenths:
            parts.append(f'<rect class="usage-bar" x="380" y="{y-12}" width="{654*row.tenths/1000:.3f}" height="9" rx="4.5" fill="{color}"/>')
        parts.append('</g>')
    if not rows:
        parts.append(svg_text(62, 356+extra_height, 'Add code to a public repository to populate this card.', 14, p['muted']))
    parts.append('</g>')
    parts.append(svg_text(48, height - 12, f'{report.repositories_scanned} repositories scanned · forks excluded', 10, p['muted']))
    parts.append(svg_text(1052, height - 12, 'GITHUB / LIVE DATA', 9, p['muted'], 'text-anchor="end" letter-spacing="1"'))
    parts.append('</svg>')
    return ''.join(parts)
