from __future__ import annotations

import io
from html import escape
from typing import TYPE_CHECKING, Any

from PIL import Image, UnidentifiedImageError

from renderers.ascii import render_ascii_name
from renderers.shared import ANIMATION_KEYFRAMES, CARD_WIDTH, MONO, PALETTES, svg_text

if TYPE_CHECKING:
    from services.github import GitHubProfile


WIDTH, HEIGHT = CARD_WIDTH, 560
ASCII_CHARS = " .:-=+*#%@"

# Six-second cycle: staggered reveal, readable hold, shared fade, then reset.
HEADER_REVEAL_KEYFRAMES = """  @keyframes intro-loop {
    0% { opacity: 0; transform: translateY(6px); }
    10%,88% { opacity: 1; transform: translateY(0); }
    96%,100% { opacity: 0; transform: translateY(6px); }
  }
  @keyframes name-loop {
    0%,3.67% { opacity: 0; clip-path: inset(0 100% 0 0); }
    25.33%,88% { opacity: 1; clip-path: inset(0 0 0 0); }
    96% { opacity: 0; clip-path: inset(0 0 0 0); }
    100% { opacity: 0; clip-path: inset(0 100% 0 0); }
  }
  @keyframes portrait-loop {
    0%,9.17% { opacity: 0; clip-path: inset(0 0 100% 0); }
    32.5%,88% { opacity: 1; clip-path: inset(0 0 0 0); }
    96% { opacity: 0; clip-path: inset(0 0 0 0); }
    100% { opacity: 0; clip-path: inset(0 0 100% 0); }
  }
  @keyframes details-loop {
    0%,22.5% { opacity: 0; transform: translateY(6px); }
    33.33%,88% { opacity: 1; transform: translateY(0); }
    96%,100% { opacity: 0; transform: translateY(6px); }
  }
  @keyframes footer-loop {
    0%,28.33% { opacity: 0; transform: translateY(6px); }
    40%,88% { opacity: 1; transform: translateY(0); }
    96%,100% { opacity: 0; transform: translateY(6px); }
  }
"""


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], weight: float) -> tuple[int, int, int]:
    return (
        round(a[0] * (1 - weight) + b[0] * weight),
        round(a[1] * (1 - weight) + b[1] * weight),
        round(a[2] * (1 - weight) + b[2] * weight),
    )


def _avatar_color(rgb: tuple[int, int, int], theme: str) -> str:
    target = (115, 185, 207) if theme == "dark" else (33, 65, 95)
    weight = 0.36 if theme == "dark" else 0.26
    return "#%02x%02x%02x" % _mix(rgb, target, weight)


def _avatar_image(avatar_bytes: bytes) -> Image.Image:
    try:
        image = Image.open(io.BytesIO(avatar_bytes)).convert("RGB")
        return image.resize((66, 52), Image.Resampling.LANCZOS)
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("Could not decode GitHub avatar") from exc


def render_profile_svg(
    *,
    profile: "GitHubProfile",
    avatar_bytes: bytes,
    theme: str,
    config: dict[str, Any],
) -> str:
    p = PALETTES[theme]
    avatar = _avatar_image(avatar_bytes)
    name_markup = render_ascii_name(profile.name, p["ink"])

    tagline = str(config.get("tagline") or "Build. Learn. Share.")
    visual_language = str(config.get("visual_language") or "Characters become identity.")

    parts = [f'''<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-labelledby="title desc">
<title id="title">{escape(profile.name)} — ASCII identity</title>
<desc id="desc">Animated ASCII GitHub profile header for @{escape(profile.login)}.</desc>
<defs>
  <pattern id="grid" width="28" height="28" patternUnits="userSpaceOnUse"><path d="M28 0H0V28" fill="none" stroke="{p['grid']}" stroke-width=".65"/></pattern>
  <radialGradient id="glow"><stop stop-color="{p['glow']}" stop-opacity=".9"/><stop offset="1" stop-color="{p['bg']}" stop-opacity="0"/></radialGradient>
  <clipPath id="card"><rect x="1" y="1" width="1098" height="558" rx="26"/></clipPath>
</defs>
<style>
  .intro {{ animation: intro-loop 6s ease-out infinite; }}
  .name {{ animation: name-loop 6s ease-out infinite; }}
  .portrait {{ animation: portrait-loop 6s ease-out infinite; }}
  .details {{ animation: details-loop 6s ease-out infinite; }}
  .footer {{ animation: footer-loop 6s ease-out infinite; }}
  .orbit {{ transform-origin: 865px 268px; animation: orbit 32s linear infinite; }}
  .signal {{ animation: pulse 3.8s ease-in-out infinite; }}
{ANIMATION_KEYFRAMES}{HEADER_REVEAL_KEYFRAMES}  @media (prefers-reduced-motion: reduce) {{ .intro,.name,.portrait,.details,.footer,.orbit,.signal {{ animation: none; }} }}
</style>
<g clip-path="url(#card)">
  <rect width="1100" height="560" fill="{p['bg']}"/>
  <rect width="1100" height="560" fill="url(#grid)" opacity=".58"/>
  <ellipse cx="860" cy="220" rx="360" ry="330" fill="url(#glow)"/>
  <path d="M663 104V430" stroke="{p['line']}" stroke-dasharray="2 8" opacity=".7"/>
</g>
<rect x="1" y="1" width="1098" height="558" rx="26" fill="none" stroke="{p['line']}" stroke-width="1.5"/>
<g class="intro">
  {svg_text(1046, 51, '@' + profile.login, 11, p['muted'], 'text-anchor="end"')}
  <circle class="signal" cx="57" cy="112" r="3" fill="{p['accent']}"/>
  {svg_text(71, 116, "HELLO, WORLD. I'M", 11, p['accent'], 'letter-spacing="3.4"')}
</g>
<g class="name">{name_markup}</g>
<g fill="none" stroke="{p['accent']}" stroke-width=".8">
  <circle cx="865" cy="268" r="182" opacity=".16"/>
  <circle cx="865" cy="268" r="174" opacity=".1"/>
  <g class="orbit">
    <circle cx="865" cy="268" r="182" stroke-dasharray="68 1076" transform="rotate(-103 865 268)" opacity=".65"/>
    <circle cx="865" cy="268" r="174" stroke-dasharray="46 1047" transform="rotate(61 865 268)" opacity=".5"/>
  </g>
</g>
<g class="portrait" font-family="{MONO}" font-size="6.3" font-weight="500">''']

    for row in range(52):
        for col in range(66):
            pixel = avatar.getpixel((col, row))
            rgb = (int(pixel[0]), int(pixel[1]), int(pixel[2]))  # type: ignore[index]
            luminance = sum(channel * weight for channel, weight in zip(rgb, (0.2126, 0.7152, 0.0722)))
            char_index = round((1 - luminance / 255) * (len(ASCII_CHARS) - 1))
            if char_index == 0:
                continue
            parts.append(
                f'<text x="{701 + col * 4.95:.2f}" y="{124 + row * 5.8:.2f}" '
                f'fill="{_avatar_color(rgb, theme)}">{escape(ASCII_CHARS[char_index])}</text>'
            )

    parts.append(f'''</g>
<g class="details">
  {svg_text(54, 382, tagline, 13, p['muted'])}
</g>
<g class="footer">
  <path d="M54 461H1046" stroke="{p['line']}"/>
  {svg_text(54, 489, 'BASED IN', 9, p['muted'], 'letter-spacing="2"')}
  {svg_text(54, 515, profile.location[:28], 15, p['ink'])}
  {svg_text(386, 489, 'REPOSITORIES / FOLLOWERS', 9, p['muted'], 'letter-spacing="2"')}
  {svg_text(386, 515, f'{profile.public_repos} repos / {profile.followers} followers', 15, p['ink'])}
  {svg_text(736, 489, 'VISUAL LANGUAGE', 9, p['muted'], 'letter-spacing="2"')}
  {svg_text(736, 515, visual_language[:34], 14, p['ink'])}
</g>
</svg>''')
    return "".join(parts)
