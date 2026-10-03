from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, Response

from config import load_profile_config
from renderers.contributions import DEFAULT_ANIMATION_SECONDS, render_contributions_svg
from renderers.shared import render_error_svg
from routes.header import USERNAME_RE
from services.contributions import ContributionReport, fetch_contributions
from services.repository_contributions import fetch_repository_contributions, valid_repository
from services.contribution_avatars import embed_avatars
from renderers.contribution_preview import render_contribution_preview
from services.github import GitHubClientError


router = APIRouter(prefix='/api', tags=['contributions'])
preview_router = APIRouter(prefix='/preview', tags=['preview'])
CACHE_HEADERS = {'Cache-Control': 'no-cache', 'Vercel-CDN-Cache-Control': 'public, s-maxage=3600, stale-while-revalidate=86400'}


def validate_username(username: str) -> None:
    if not USERNAME_RE.fullmatch(username):
        raise HTTPException(status_code=422, detail='Invalid GitHub username')


def selected_year(year: int | None) -> int:
    current = datetime.now(timezone.utc).year
    if year is not None and not 2008 <= year <= current:
        raise HTTPException(status_code=422, detail=f'Year must be from 2008 to {current}')
    return year if year is not None else current


def validate_repo(repo: str | None) -> None:
    if repo and not valid_repository(repo):
        raise HTTPException(status_code=422,detail='Repository must be owner/name')


async def get_report(username: str, year: int, repo: str | None) -> ContributionReport:
    if repo:
        return await fetch_repository_contributions(username,repo,year=year)
    return await fetch_contributions(username,year=year)


@router.get('/contributions', response_class=Response)
async def contributions(
    username: str = Query(..., min_length=1, max_length=39),
    theme: Literal['auto', 'light', 'dark'] = 'auto',
    animate: bool = True,
    year: int | None = Query(None, ge=2008),
    repo: str | None = Query(None,max_length=140),
    section: Literal['full','calendar','activity'] = 'full',
) -> Response:
    validate_username(username)
    year = selected_year(year)
    validate_repo(repo)
    try:
        seconds = load_profile_config().get('contribution_animation_seconds', DEFAULT_ANIMATION_SECONDS)
        if type(seconds) is not int or not 12 <= seconds <= 120:
            raise ValueError('contribution_animation_seconds must be an integer from 12 to 120')
        report = await get_report(username, year, repo)
        if section != 'calendar':
            report = await embed_avatars(report)
        svg = render_contributions_svg(report=report, theme=theme, animate=animate, seconds=seconds, section=section)
        status, headers = 200, CACHE_HEADERS
    except GitHubClientError as exc:
        svg = render_error_svg(username=username, theme='light' if theme == 'auto' else theme, message=str(exc), heading='Contributions are temporarily unavailable')
        status = exc.status_code if exc.status_code in {404, 422, 429} else 502
        headers = {'Cache-Control': 'no-store'}
    except (OSError, ValueError, TypeError, KeyError):
        svg = render_error_svg(username=username, theme='light' if theme == 'auto' else theme, message='Contribution rendering is temporarily unavailable', heading='Contributions are temporarily unavailable')
        status, headers = 502, {'Cache-Control': 'no-store'}
    return Response(svg, media_type='image/svg+xml', status_code=status, headers={**headers, 'X-Content-Type-Options': 'nosniff'})


@router.get('/contribution-data')
async def contribution_data(username: str = Query(..., min_length=1, max_length=39), year: int | None = Query(None, ge=2008), repo: str | None = Query(None,max_length=140)) -> dict[str, Any]:
    validate_username(username)
    year = selected_year(year)
    validate_repo(repo)
    try:
        report = await get_report(username, year, repo)
    except GitHubClientError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    overview = None
    if report.overview:
        overview = asdict(report.overview)
        overview['projects'] = [{**asdict(project), 'url': project.url} for project in report.overview.projects]
    return {
        'username': report.username, 'source': report.source, 'year': report.year,
        'available_years': report.overview.years if report.overview else (),
        'from': report.days[0].date.isoformat(), 'to': report.days[-1].date.isoformat(), 'as_of':report.as_of.isoformat(), 'repository':report.repository,
        'total_contributions': report.total, 'current_streak': report.current_streak,
        'streak_label': 'year_end' if report.year is not None and report.as_of.year < (report.today or report.as_of).year else 'current',
        'longest_streak': report.longest_streak, 'active_days': report.active_days,
        'overview': overview,
        'days': [{'date': day.date.isoformat(), 'count': day.count, 'level': day.level} for day in report.days],
    }


@preview_router.get('/contributions', response_class=HTMLResponse)
async def contributions_preview(
    username: str = Query('baonguyen1776', min_length=1, max_length=39),
    year: int | None = Query(None, ge=2008),
    theme: Literal['auto', 'light', 'dark'] = 'auto',
    repo: str | None = Query(None,max_length=140),
) -> HTMLResponse:
    validate_username(username)
    year = selected_year(year)
    validate_repo(repo)
    repo = repo or None
    try:
        if repo:
            base_raw, report_raw = await asyncio.gather(
                fetch_contributions(username, year=year),
                get_report(username, year, repo),
            )
            base = await embed_avatars(base_raw)
            report = await embed_avatars(report_raw)
        else:
            base = await embed_avatars(await fetch_contributions(username,year=year))
            report = base
    except GitHubClientError as exc:
        raise HTTPException(status_code=exc.status_code,detail=str(exc)) from exc
    html = render_contribution_preview(base,report,username=username,year=year,theme=theme,repo=repo)
    return HTMLResponse(html,headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})


@router.get('/contribution-year-button', response_class=Response)
def contribution_year_button(year: int = Query(..., ge=2008), active: bool = False, theme: Literal['light', 'dark'] = 'light') -> Response:
    year = selected_year(year)
    background = '#0969da' if active else '#f6f8fa' if theme == 'light' else '#161b22'
    ink = '#ffffff' if active else '#1f2328' if theme == 'light' else '#e6edf3'
    border = '#0969da' if active else '#d0d7de' if theme == 'light' else '#30363d'
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="80" height="34" viewBox="0 0 80 34" role="img" aria-label="Contributions in {year}"><rect x=".5" y=".5" width="79" height="33" rx="6" fill="{background}" stroke="{border}"/><text x="40" y="22" font-family="Arial,Helvetica,sans-serif" font-size="13" font-weight="600" text-anchor="middle" fill="{ink}">{year}</text></svg>'
    return Response(svg, media_type='image/svg+xml', headers={**CACHE_HEADERS, 'X-Content-Type-Options': 'nosniff'})
