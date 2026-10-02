from __future__ import annotations

import re
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from config import load_profile_config
from renderers.header import render_profile_svg
from renderers.shared import render_error_svg
from services.github import GitHubClientError, fetch_profile


USERNAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
router = APIRouter(prefix="/api", tags=["header"])


@router.get("/header", response_class=Response)
def header(
    username: str = Query(..., min_length=1, max_length=39),
    theme: Literal["light", "dark"] = "light",
) -> Response:
    if not USERNAME_RE.fullmatch(username):
        raise HTTPException(status_code=422, detail="Invalid GitHub username")

    try:
        profile, avatar_bytes = fetch_profile(username)
        svg = render_profile_svg(
            profile=profile,
            avatar_bytes=avatar_bytes,
            theme=theme,
            config=load_profile_config(),
        )
        status_code = 200
        cache_headers = {
            "Cache-Control": "no-cache",
            "Vercel-CDN-Cache-Control": "public, s-maxage=3600, stale-while-revalidate=86400",
        }
    except GitHubClientError as exc:
        svg = render_error_svg(username=username, theme=theme, message=str(exc))
        status_code = exc.status_code if exc.status_code in {404, 429} else 502
        cache_headers = {"Cache-Control": "no-store"}
    except (OSError, ValueError):
        svg = render_error_svg(
            username=username,
            theme=theme,
            message="Profile rendering is temporarily unavailable",
        )
        status_code = 502
        cache_headers = {"Cache-Control": "no-store"}

    return Response(
        content=svg,
        media_type="image/svg+xml",
        status_code=status_code,
        headers={**cache_headers, "X-Content-Type-Options": "nosniff"},
    )
