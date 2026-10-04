from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from renderers.shared import render_error_svg
from renderers.stack import render_stack_svg
from routes.header import USERNAME_RE
from services.github import GitHubClientError
from services.languages import all_language_rows, fetch_language_report, select_language_rows


router = APIRouter(prefix="/api", tags=["stack"])
CACHE_HEADERS = {
    "Cache-Control": "no-cache",
    "Vercel-CDN-Cache-Control": "public, s-maxage=3600, stale-while-revalidate=86400",
}


def _validate_username(username: str) -> None:
    if not USERNAME_RE.fullmatch(username):
        raise HTTPException(status_code=422, detail="Invalid GitHub username")


def _choices(value: str | None) -> list[str]:
    return list(dict.fromkeys(name.strip() for name in (value or "").split(",") if name.strip()))


@router.get("/languages")
async def available_languages(username: str = Query(..., min_length=1, max_length=39)) -> dict[str, Any]:
    _validate_username(username)
    try:
        report = await fetch_language_report(username)
    except GitHubClientError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return {
        "username": report.username,
        "repositories_scanned": report.repositories_scanned,
        "total_bytes": report.total_bytes,
        "languages": [
            {"name": row.name, "bytes": row.code_bytes, "percentage": row.percentage}
            for row in all_language_rows(report)
        ],
    }


@router.get("/stack", response_class=Response)
async def stack(
    username: str = Query(..., min_length=1, max_length=39),
    theme: Literal["light", "dark"] = "dark",
    languages: str | None = Query(None, max_length=300, description="Optional comma-separated GitHub language choices"),
) -> Response:
    _validate_username(username)
    try:
        report = await fetch_language_report(username)
        rows = select_language_rows(report, _choices(languages))
        svg = render_stack_svg(report=report, rows=rows, theme=theme)
        status_code = 200
        headers = CACHE_HEADERS
    except GitHubClientError as exc:
        svg = render_error_svg(username=username, theme=theme, message=str(exc), heading="Language usage is temporarily unavailable")
        status_code = exc.status_code if exc.status_code in {404, 429} else 502
        headers = {"Cache-Control": "no-store"}
    except (OSError, ValueError, TypeError):
        svg = render_error_svg(username=username, theme=theme, message="Language usage rendering is temporarily unavailable", heading="Language usage is temporarily unavailable")
        status_code = 502
        headers = {"Cache-Control": "no-store"}
    return Response(
        svg, media_type="image/svg+xml", status_code=status_code,
        headers={**headers, "X-Content-Type-Options": "nosniff"},
    )
