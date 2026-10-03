from __future__ import annotations

from html import escape


CARD_WIDTH = 1100
MONO = "ui-monospace,SFMono-Regular,Menlo,Consolas,'Liberation Mono',monospace"
SANS = "Inter,Arial,Helvetica,'DejaVu Sans',sans-serif"
PALETTES = {
    "light": {
        "bg": "#eef4fb",
        "ink": "#172f4a",
        "muted": "#60758c",
        "accent": "#2868cc",
        "line": "#cbd9e9",
        "grid": "#d5e1ef",
        "glow": "#dce9fc",
    },
    "dark": {
        "bg": "#0c1723",
        "ink": "#e6eef9",
        "muted": "#97a9c1",
        "accent": "#77b8ff",
        "line": "#263a50",
        "grid": "#21344b",
        "glow": "#152f4d",
    },
}


from typing import Any


def svg_text(x: float, y: float, content: str, size: float, color: Any, extra: str = "") -> str:
    return (
        f'<text x="{x}" y="{y}" font-family="{MONO}" font-size="{size}" '
        f'fill="{color}" {extra}>{escape(content)}</text>'
    )


ANIMATION_KEYFRAMES = """  @keyframes appear { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }
  @keyframes word-in { from { opacity: 0; clip-path: inset(0 100% 0 0); } to { opacity: 1; clip-path: inset(0 0 0 0); } }
  @keyframes portrait-in { from { opacity: 0; clip-path: inset(0 0 100% 0); } to { opacity: 1; clip-path: inset(0 0 0 0); } }
  @keyframes orbit { to { transform: rotate(360deg); } }
  @keyframes pulse { 0%,100% { opacity: .4; } 50% { opacity: 1; } }
"""


def render_error_svg(*, username: str, theme: str, message: str, heading: str = "Profile header is temporarily unavailable") -> str:
    p = PALETTES[theme]
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{CARD_WIDTH}" height="220" viewBox="0 0 {CARD_WIDTH} 220" role="img">
<rect width="1100" height="220" rx="24" fill="{p['bg']}" stroke="{p['line']}"/>
{svg_text(54, 66, '@' + username, 15, p['accent'])}
{svg_text(54, 118, heading, 24, p['ink'])}
{svg_text(54, 156, message[:80], 13, p['muted'])}
</svg>'''
