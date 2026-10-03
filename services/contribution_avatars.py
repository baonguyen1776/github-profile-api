from __future__ import annotations

import asyncio
import base64
import io
import time
from collections import OrderedDict
from dataclasses import replace

import httpx
from PIL import Image

from services.contributions import ContributionReport


_CACHE: OrderedDict[str, tuple[float, str]] = OrderedDict()
SUCCESS_TTL_SECONDS = 86400
FAILURE_TTL_SECONDS = 300
AVATAR_TIMEOUT_SECONDS = 3.5


def _cache_avatar(owner: str, value: str) -> str:
    key = owner.casefold()
    _CACHE[key] = (time.monotonic(), value)
    _CACHE.move_to_end(key)
    while len(_CACHE)>64:
        _CACHE.popitem(last=False)
    return value


async def _download_avatar(owner: str, client: httpx.AsyncClient) -> str:
    try:
        response = await client.get(f'https://github.com/{owner}.png',params={'size':40})
        response.raise_for_status()
        if len(response.content)>1_000_000:
            return _cache_avatar(owner, '')
        with Image.open(io.BytesIO(response.content)) as picture:
            picture.thumbnail((40,40))
            buffer = io.BytesIO()
            picture.convert('RGBA').save(buffer,format='PNG')
            uri = 'data:image/png;base64,'+base64.b64encode(buffer.getvalue()).decode('ascii')
    except (httpx.HTTPError,OSError,ValueError):
        return _cache_avatar(owner, '')
    return _cache_avatar(owner, uri)


async def avatar_data(owner: str, client: httpx.AsyncClient | None = None) -> str:
    key = owner.casefold()
    cached = _CACHE.get(key)
    if cached:
        ttl = SUCCESS_TTL_SECONDS if cached[1] else FAILURE_TTL_SECONDS
        if time.monotonic()-cached[0] < ttl:
            _CACHE.move_to_end(key)
            return cached[1]
        del _CACHE[key]
    if client is not None:
        return await _download_avatar(owner, client)
    # Separate unauthenticated client: never send GITHUB_TOKEN to an image host.
    async with httpx.AsyncClient(timeout=AVATAR_TIMEOUT_SECONDS,follow_redirects=True) as own_client:
        return await _download_avatar(owner, own_client)


async def embed_avatars(report: ContributionReport) -> ContributionReport:
    overview = report.overview
    if not overview or not overview.projects:
        return report
    owners = sorted({project.name.split('/')[0] for project in overview.projects})
    gate = asyncio.Semaphore(3)
    async with httpx.AsyncClient(timeout=AVATAR_TIMEOUT_SECONDS,follow_redirects=True) as client:
        async def fetch(owner: str) -> tuple[str, str]:
            async with gate:
                return owner,await avatar_data(owner, client)
        images = dict(await asyncio.gather(*(fetch(owner) for owner in owners)))
    projects = tuple(replace(project,avatar_data_uri=images[project.name.split('/')[0]]) for project in overview.projects)
    return replace(report,overview=replace(overview,projects=projects))
