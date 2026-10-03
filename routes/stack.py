from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from renderers.shared import render_error_svg
from renderers.stack import render_stack_svg
from routes.header import USERNAME_RE
from services.github import GitHubClientError
from services.languages import all_language_rows, fetch_language_report, select_language_rows
from services.technologies import fetch_technology_report


router = APIRouter(prefix="/api", tags=["stack"])
CACHE_HEADERS = {
    "Cache-Control": "no-cache",
    "Vercel-CDN-Cache-Control": "public, s-maxage=3600, stale-while-revalidate=86400",
}


def _validate_username(username: str) -> None:
    if not USERNAME_RE.fullmatch(username):
        raise HTTPException(status_code=422, detail="Invalid GitHub username")


def _choices(value: str | None) -> list[str]:
    """An omitted or blank README query option uses that field's defaults."""
    return list(dict.fromkeys(name.strip() for name in (value or "").split(",") if name.strip()))


@router.get("/languages")
async def available_languages(username: str = Query(..., min_length=1, max_length=39)) -> dict[str, Any]:
    """List GitHub-backed choices before configuring the stack card."""
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


@router.get("/technologies")
async def available_technologies(username: str = Query(..., min_length=1, max_length=39)) -> dict[str, Any]:
    """List selectable dependencies together with their manifest evidence."""
    _validate_username(username)
    try:
        languages = await fetch_language_report(username)
        report = await fetch_technology_report(languages)
    except GitHubClientError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return {
        "username": languages.username, "manifests_scanned": report.manifests_scanned,
        "incomplete": report.incomplete,
        "technologies": [{"name": name, "sources": report.evidence[name]} for name in sorted(report.evidence)],
    }


@router.get("/stack", response_class=Response)
async def stack(
    username: str = Query(..., min_length=1, max_length=39),
    theme: Literal["light", "dark"] = "dark",
    languages: str | None = Query(None, max_length=300, description="Optional comma-separated GitHub language choices"),
    technologies: str | None = Query(None, max_length=500, description="Comma-separated detected technologies; omitted or blank means automatic"),
    editors: str | None = Query(None, max_length=200, description="Comma-separated editor names; omitted or blank hides editors"),
    focus: str | None = Query(None, max_length=200, description="Comma-separated personal focus labels; omitted or blank hides labels"),
) -> Response:
    _validate_username(username)
    try:
        report = await fetch_language_report(username)
        rows = select_language_rows(report, _choices(languages))
        technology_report = await fetch_technology_report(report)
        svg = render_stack_svg(
            report=report, rows=rows, theme=theme, technologies=technology_report,
            requested_technologies=_choices(technologies), editors=_choices(editors),
            focus_areas=_choices(focus),
        )
        status_code = 200
        headers = CACHE_HEADERS
    except GitHubClientError as exc:
        svg = render_error_svg(username=username, theme=theme, message=str(exc), heading="Tech Stack is temporarily unavailable")
        status_code = exc.status_code if exc.status_code in {404, 429} else 502
        headers = {"Cache-Control": "no-store"}
    except (OSError, ValueError, TypeError):
        svg = render_error_svg(username=username, theme=theme, message="Tech Stack rendering is temporarily unavailable", heading="Tech Stack is temporarily unavailable")
        status_code = 502
        headers = {"Cache-Control": "no-store"}
    return Response(
        svg, media_type="image/svg+xml", status_code=status_code,
        headers={**headers, "X-Content-Type-Options": "nosniff"},
    )
