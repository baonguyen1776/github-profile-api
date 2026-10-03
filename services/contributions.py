from __future__ import annotations

import asyncio
import os
import re
import time
from collections import OrderedDict
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote

import httpx

from services.contribution_overview import ContributionOverview, REPO_NAME, fetch_public_overview, graphql_overview
from services.github import API_BASE, TIMEOUT, GitHubClientError, _headers


CACHE_TTL = 3600
CACHE_LIMIT = 64
LEVELS = {'NONE': 0, 'FIRST_QUARTILE': 1, 'SECOND_QUARTILE': 2, 'THIRD_QUARTILE': 3, 'FOURTH_QUARTILE': 4}
QUERY = """query Contributions($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    login
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar {
        weeks { contributionDays { date contributionCount contributionLevel } }
      }
    }
  }
}"""


COMMIT_FIELDS = """commitContributionsByRepository(maxRepositories: 100) {
  repository { nameWithOwner isPrivate }
  contributions(first: 100) { nodes { commitCount } pageInfo { hasNextPage } }
}"""
YEAR_FIELDS = COMMIT_FIELDS + """
totalCommitContributions totalPullRequestContributions
totalIssueContributions totalPullRequestReviewContributions
pullRequestContributionsByRepository(maxRepositories: 100) {
  repository { nameWithOwner isPrivate } contributions { totalCount }
}
issueContributionsByRepository(maxRepositories: 100) {
  repository { nameWithOwner isPrivate } contributions { totalCount }
}
pullRequestReviewContributionsByRepository(maxRepositories: 100) {
  repository { nameWithOwner isPrivate } contributions { totalCount }
}
"""
YEAR_QUERY = QUERY.replace('    login', '    login\n    history: contributionsCollection { contributionYears }').replace('      contributionCalendar', YEAR_FIELDS + '\n      contributionCalendar')
COMMIT_QUERY = """query CommitDays($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) { contributionsCollection(from: $from, to: $to) {
""" + COMMIT_FIELDS + """
  } }
}"""


async def graphql_user(
    client: httpx.AsyncClient,
    username: str,
    start: date,
    end: date,
    query: str,
) -> dict[str, Any]:
    response = await client.post(API_BASE + '/graphql', json={
        'query': query, 'variables': {'login': username, 'from': start.isoformat() + 'T00:00:00Z', 'to': end.isoformat() + 'T23:59:59Z'},
    })
    _check_response(response)
    payload = response.json()
    if payload.get('errors'):
        errors = payload['errors']
        if any(error.get('type') == 'NOT_FOUND' for error in errors):
            raise GitHubClientError('GitHub profile not found', 404)
        if any(error.get('type') == 'RATE_LIMITED' for error in errors):
            raise GitHubClientError('GitHub contribution rate limit reached', 429)
        raise GitHubClientError('GitHub contribution query failed')
    user = payload['data']['user']
    if user is None:
        raise GitHubClientError('GitHub profile not found', 404)
    return user


async def complete_commit_counts(
    client: httpx.AsyncClient,
    username: str,
    start: date,
    end: date,
) -> tuple[dict[str, int], bool]:
    # Each node represents one active day. Quarters contain at most 92 days,
    # so first:100 gives every day without a per-repository cursor query.
    windows = []
    for month in (1, 4, 7, 10):
        first = date(start.year, month, 1)
        following = date(start.year + (month == 10), (month + 2) % 12 + 1, 1)
        if first <= end:
            windows.append((first, min(end, following - timedelta(days=1))))
    results = await asyncio.gather(*(graphql_user(client, username, a, b, COMMIT_QUERY) for a, b in windows), return_exceptions=True)
    counts: dict[str, int] = {}
    limited = False
    for user in results:
        if isinstance(user, BaseException):
            raise user
        entries = user['contributionsCollection']['commitContributionsByRepository']
        limited |= len(entries) >= 100
        for entry in entries:
            if entry['repository']['isPrivate']:
                continue
            name = entry['repository']['nameWithOwner']
            if not REPO_NAME.fullmatch(name) or entry['contributions']['pageInfo']['hasNextPage']:
                raise ValueError('Incomplete commit-day query')
            amounts = [node['commitCount'] for node in entry['contributions']['nodes']]
            if any(type(amount) is not int or amount < 0 for amount in amounts):
                raise ValueError('Invalid commit-day count')
            counts[name] = counts.get(name, 0) + sum(amounts)
    return counts, limited


@dataclass(frozen=True)
class ContributionDay:
    date: date
    count: int
    level: int


@dataclass(frozen=True)
class ContributionReport:
    username: str
    days: tuple[ContributionDay, ...]
    as_of: date
    source: str
    year: int | None = None
    today: date | None = None
    overview: ContributionOverview | None = None
    repository: str | None = None

    @property
    def total(self) -> int:
        return sum(day.count for day in self.days)

    @property
    def active_days(self) -> int:
        return sum(day.count > 0 for day in self.days)

    @property
    def longest_streak(self) -> int:
        longest = run = 0
        previous = None
        for day in self.days:
            run = (run + 1 if previous == day.date - timedelta(days=1) else 1) if day.count else 0
            longest = max(longest, run)
            previous = day.date
        return longest

    @property
    def current_streak(self) -> int:
        counts = {day.date: day.count for day in self.days}
        # An unfinished, empty today does not break yesterday's streak.
        historical = self.year is not None and self.today is not None and self.as_of < self.today
        anchor = self.as_of if historical or counts.get(self.as_of, 0) else self.as_of - timedelta(days=1)
        run = 0
        while counts.get(anchor, 0):
            run += 1
            anchor -= timedelta(days=1)
        return run


class CalendarParser(HTMLParser):
    """Join GitHub's dated cells with their separate, accessible count tooltips."""
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.cells: dict[str, tuple[date, int, int | None]] = {}
        self.tooltips: dict[str, str] = {}
        self.target: str | None = None
        self.fragments: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key: value or '' for key, value in attrs}
        if attributes.get('data-date') and attributes.get('data-level'):
            day = date.fromisoformat(attributes['data-date'])
            level = int(attributes['data-level'])
            identifier = attributes.get('id', day.isoformat())
            count = int(attributes['data-count']) if 'data-count' in attributes else None
            self.cells[identifier] = (day, level, count)
        if tag == 'tool-tip':
            self.target = attributes.get('for')
            self.fragments = []

    def handle_data(self, data: str) -> None:
        if self.target:
            self.fragments.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == 'tool-tip' and self.target:
            self.tooltips[self.target] = ''.join(self.fragments).strip()
            self.target = None

    def days(self) -> list[ContributionDay]:
        days = []
        for identifier, (day, level, count) in self.cells.items():
            if count is None:
                text = self.tooltips.get(identifier, '')
                match = re.match(r'^(No|[\d,]+) contributions?\b', text)
                if not match:
                    raise ValueError('Contribution counts are missing from GitHub calendar')
                count = 0 if match[1] == 'No' else int(match[1].replace(',', ''))
            days.append(ContributionDay(day, count, level))
        return days


def make_report(username: str, days: list[ContributionDay], as_of: date, source: str, *, year: int | None = None, overview: ContributionOverview | None = None) -> ContributionReport:
    today = as_of
    if year is not None and (type(year) is not int or not 2008 <= year <= today.year):
        raise ValueError('Contribution year is outside the supported range')
    start = date(year, 1, 1) if year is not None else as_of - timedelta(days=364)
    as_of = min(as_of, date(year, 12, 31)) if year is not None else as_of
    by_date: dict[date, ContributionDay] = {}
    for day in days:
        if type(day.count) is not int or day.count < 0 or type(day.level) is not int or not 0 <= day.level <= 4:
            raise ValueError('Invalid contribution count or level')
        if (day.count == 0) != (day.level == 0):
            raise ValueError('Inconsistent contribution count and level')
        if start <= day.date <= as_of:
            if day.date in by_date and by_date[day.date] != day:
                raise ValueError('Conflicting contribution dates')
            by_date[day.date] = day
    expected = [start + timedelta(days=index) for index in range((as_of - start).days + 1)]
    if any(day not in by_date for day in expected):
        raise ValueError('GitHub contribution calendar is incomplete')
    return ContributionReport(username, tuple(by_date[day] for day in expected), as_of, source, year, today, overview)


def parse_public_calendar(html: str) -> list[ContributionDay]:
    parser = CalendarParser()
    parser.feed(html)
    parser.close()
    return parser.days()


_CACHE: OrderedDict[tuple[str, date, bool, int | None], tuple[float, ContributionReport]] = OrderedDict()


def _check_response(response: httpx.Response) -> None:
    if response.status_code == 404:
        raise GitHubClientError('GitHub profile not found', 404)
    if response.status_code == 429 or (response.status_code == 403 and response.headers.get('x-ratelimit-remaining') == '0'):
        raise GitHubClientError('GitHub contribution rate limit reached', 429)
    if response.status_code in {401, 403}:
        raise GitHubClientError('GitHub contribution access denied; check GITHUB_TOKEN', 502)
    response.raise_for_status()


async def fetch_contributions(username: str, *, as_of: date | None = None, year: int | None = None) -> ContributionReport:
    """A calendar year (year=...) or the legacy rolling 365-day window."""
    as_of = as_of or datetime.now(timezone.utc).date()
    if year is not None and (type(year) is not int or not 2008 <= year <= as_of.year):
        raise ValueError('Contribution year is outside the supported range')
    token = bool(os.getenv('GITHUB_TOKEN'))
    key = (username.casefold(), as_of, token, year)
    cached = _CACHE.get(key)
    if cached and time.monotonic() - cached[0] < CACHE_TTL:
        _CACHE.move_to_end(key)
        return cached[1]
    start = date(year, 1, 1) if year is not None else as_of - timedelta(days=364)
    end = min(as_of, date(year, 12, 31)) if year is not None else as_of
    overview = None
    try:
        if token:
            async with httpx.AsyncClient(timeout=TIMEOUT, headers=_headers()) as client:
                user = await graphql_user(client, username, start, end, YEAR_QUERY if year is not None else QUERY)
                collection = user['contributionsCollection']
                days = [
                    ContributionDay(date.fromisoformat(day['date']), day['contributionCount'], LEVELS[day['contributionLevel']])
                    for week in collection['contributionCalendar']['weeks'] for day in week['contributionDays']
                ]
                if year is not None:
                    try:
                        override = None
                        limited = False
                        if any(entry['contributions']['pageInfo']['hasNextPage'] for entry in collection['commitContributionsByRepository']):
                            override, limited = await complete_commit_counts(client, username, start, end)
                        overview = graphql_overview(collection, user['history']['contributionYears'], override)
                        if limited:
                            overview = replace(overview, status='partial', message=overview.message + ' Quarterly repository lists may be limited.')
                    except (GitHubClientError, httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError):
                        overview = ContributionOverview(message='Project activity could not be loaded. The calendar is still available.')
                report = make_report(user['login'], days, as_of, 'github-graphql', year=year, overview=overview)
        else:
            headers = {'User-Agent': 'github-profile-svg-api', 'Accept': 'text/html', 'Accept-Language': 'en-US'}
            async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True, headers=headers) as client:
                async def calendar_year(selected_year: int) -> list[ContributionDay]:
                    response = await client.get(
                        f'https://github.com/users/{quote(username, safe="")}/contributions',
                        params={'from': f'{selected_year}-01-01', 'to': f'{selected_year}-12-31'},
                    )
                    _check_response(response)
                    return parse_public_calendar(response.text)
                results = await asyncio.gather(*(calendar_year(selected_year) for selected_year in range(start.year, end.year + 1)), return_exceptions=True)
                days = []
                for result in results:
                    if isinstance(result, BaseException):
                        raise result
                    days.extend(result)
            # Validate the authoritative calendar before making optional timeline calls.
            report = make_report(username, days, as_of, 'github-public-calendar', year=year)
            if year is not None:
                overview = await fetch_public_overview(username, start, end)
                report = make_report(username, days, as_of, 'github-public-calendar', year=year, overview=overview)
    except GitHubClientError:
        raise
    except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise GitHubClientError('GitHub contribution data is temporarily unavailable') from exc
    _CACHE[key] = (time.monotonic(), report)
    _CACHE.move_to_end(key)
    while len(_CACHE) > CACHE_LIMIT:
        _CACHE.popitem(last=False)
    return report
