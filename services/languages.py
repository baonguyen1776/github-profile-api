from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

from services.github import API_BASE, TIMEOUT, GitHubClientError, _headers


CACHE_TTL = 3600
CACHE_LIMIT = 64
MAX_PARALLEL_REQUESTS = 6


@dataclass(frozen=True)
class LanguageReport:
    username: str
    repositories_scanned: int
    language_bytes: dict[str, int]
    repositories: tuple[tuple[str, str], ...] = ()

    @property
    def total_bytes(self) -> int:
        return sum(self.language_bytes.values())


@dataclass(frozen=True)
class LanguageRow:
    name: str
    code_bytes: int
    tenths: int

    @property
    def percentage(self) -> float:
        return self.tenths / 10


_CACHE: OrderedDict[str, tuple[float, LanguageReport]] = OrderedDict()


async def _get_json(client: httpx.AsyncClient, path: str, params: dict[str, Any] | None = None) -> Any:
    response = await client.get(f"{API_BASE}{path}", params=params)
    if response.status_code == 404:
        raise GitHubClientError("GitHub profile or repository not found", 404)
    if response.status_code == 429 or (
        response.status_code == 403 and response.headers.get("x-ratelimit-remaining") == "0"
    ):
        raise GitHubClientError("GitHub API rate limit reached", 429)
    response.raise_for_status()
    return response.json()


async def fetch_language_report(username: str) -> LanguageReport:
    """Aggregate bytes from every owned public repository, excluding forks."""
    key = username.casefold()
    cached = _CACHE.get(key)
    if cached and time.monotonic() - cached[0] < CACHE_TTL:
        _CACHE.move_to_end(key)
        return cached[1]

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True, headers=_headers()) as client:
            user = await _get_json(client, f"/users/{quote(username, safe='')}")
            if not isinstance(user, dict) or not isinstance(user.get("login"), str):
                raise ValueError("Invalid GitHub profile response")
            login = user["login"]
            repositories: dict[str, dict[str, Any]] = {}
            page = 1
            while True:
                payload = await _get_json(
                    client, f"/users/{quote(login, safe='')}/repos",
                    {"type": "owner", "per_page": 100, "page": page, "sort": "full_name"},
                )
                if not isinstance(payload, list):
                    raise ValueError("Invalid repository list")
                for repo in payload:
                    if not isinstance(repo, dict):
                        raise ValueError("Invalid repository")
                    owner = repo.get("owner") or {}
                    if (
                        not repo.get("fork") and not repo.get("private")
                        and str(owner.get("login", "")).casefold() == login.casefold()
                        and isinstance(repo.get("name"), str)
                    ):
                        repositories[repo["name"]] = repo
                if len(payload) < 100:
                    break
                page += 1

            semaphore = asyncio.Semaphore(MAX_PARALLEL_REQUESTS)

            async def languages_for(repo_name: str) -> dict[str, int]:
                async with semaphore:
                    result = await _get_json(
                        client,
                        f"/repos/{quote(login, safe='')}/{quote(repo_name, safe='')}/languages",
                    )
                    if not isinstance(result, dict):
                        raise ValueError("Invalid language response")
                    values: dict[str, int] = {}
                    for name, count in result.items():
                        if not isinstance(name, str) or not isinstance(count, int) or count < 0:
                            raise ValueError("Invalid language byte count")
                        if count:
                            values[name] = count
                    return values

            results = await asyncio.gather(*(languages_for(name) for name in repositories), return_exceptions=True)
            totals: dict[str, int] = {}
            for result in results:
                if isinstance(result, BaseException):
                    raise result
                for name, count in result.items():
                    totals[name] = totals.get(name, 0) + count
            report = LanguageReport(login, len(repositories), totals, tuple((name, repo.get('default_branch') or 'HEAD') for name, repo in repositories.items() if repo.get('size') != 0))
    except GitHubClientError:
        raise
    except (httpx.HTTPError, ValueError, TypeError, AttributeError) as exc:
        raise GitHubClientError("GitHub language data is temporarily unavailable") from exc

    _CACHE[key] = (time.monotonic(), report)
    _CACHE.move_to_end(key)
    while len(_CACHE) > CACHE_LIMIT:
        _CACHE.popitem(last=False)
    return report


def _rounded_rows(values: list[tuple[str, int]]) -> list[LanguageRow]:
    """Largest-remainder rounding keeps displayed tenths summing to 100.0%."""
    total = sum(count for _, count in values)
    if not total:
        return []
    divisions = [divmod(count * 1000, total) for _, count in values]
    tenths = [whole for whole, _ in divisions]
    remaining = 1000 - sum(tenths)
    ranked = sorted(range(len(values)), key=lambda index: (-divisions[index][1], index))
    for index in ranked[:remaining]:
        tenths[index] += 1
    return [LanguageRow(name, count, amount) for (name, count), amount in zip(values, tenths)]


def all_language_rows(report: LanguageReport) -> list[LanguageRow]:
    return _rounded_rows(sorted(report.language_bytes.items(), key=lambda item: (-item[1], item[0].casefold())))


def select_language_rows(report: LanguageReport, requested: list[str], limit: int | None = None) -> list[LanguageRow]:
    available = {name.casefold(): name for name in report.language_bytes}
    selected: list[str] = []
    if requested:
        for choice in requested:
            name = available.get(choice.strip().casefold())
            if name and name not in selected:
                selected.append(name)
    else:
        selected = [row.name for row in all_language_rows(report)]
    if limit is not None:
        selected = selected[:limit]
    values = [(name, report.language_bytes[name]) for name in selected]
    remainder = report.total_bytes - sum(count for _, count in values)
    if remainder:
        values.append(("Other", remainder))
    return _rounded_rows(values)
