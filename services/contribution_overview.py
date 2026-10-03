from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, replace
from datetime import date, timedelta
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx

from services.github import TIMEOUT


KINDS = ('commits', 'pull_requests', 'issues', 'reviews')
REPO_NAME = re.compile(r'^[A-Za-z0-9-]+/[A-Za-z0-9_.-]+$')


@dataclass(frozen=True)
class ProjectContribution:
    name: str
    commits: int = 0
    pull_requests: int = 0
    issues: int = 0
    reviews: int | None = 0
    avatar_data_uri: str = ""

    @property
    def short_name(self) -> str:
        return self.name.split("/",1)[-1]

    @property
    def url(self) -> str:
        return 'https://github.com/' + self.name

    @property
    def total(self) -> int:
        return self.commits + self.pull_requests + self.issues + (self.reviews or 0)


@dataclass(frozen=True)
class ContributionOverview:
    projects: tuple[ProjectContribution, ...] = ()
    activity: dict[str, int | None] | None = None
    status: str = 'unavailable'
    message: str = 'Project activity is not available for this year.'
    years: tuple[int, ...] = ()
    source: str = ''


def sorted_projects(values: dict[str, dict[str, int]]) -> tuple[ProjectContribution, ...]:
    return tuple(
        sorted(
            (
                ProjectContribution(
                    name,
                    commits=counts.get('commits', 0),
                    pull_requests=counts.get('pull_requests', 0),
                    issues=counts.get('issues', 0),
                    reviews=counts.get('reviews', 0),
                )
                for name, counts in values.items()
            ),
            key=lambda item: (-item.total, item.name.casefold()),
        )
    )


class PublicActivityParser(HTMLParser):
    """Read eligible monthly rollups; never use pinned/owned repository lists."""
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[dict[str, Any]] = []
        self.details: list[dict[str, Any]] = []
        self.in_summary = False
        self.anchor: dict[str, Any] | None = None
        self.years: set[int] = set()
        self.has_timeline = False
        self.text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {key: value or '' for key, value in attrs}
        if tag == 'a' and re.fullmatch(r'year-link-\d{4}', a.get('id', '')):
            self.years.add(int(a['id'][-4:]))
        if 'TimelineItem' in a.get('class', '').split():
            self.has_timeline = True
        if tag == 'details':
            self.details.append({'summary': [], 'anchors': []})
        if tag == 'summary':
            self.in_summary = True
        if tag == 'a' and self.details:
            self.anchor = {'href': a.get('href', ''), 'text': []}

    def handle_data(self, data: str) -> None:
        self.text.append(data)
        if self.in_summary and self.details:
            self.details[-1]['summary'].append(data)
        if self.anchor:
            self.anchor['text'].append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == 'summary':
            self.in_summary = False
        if tag == 'a' and self.anchor:
            for block in self.details:
                block['anchors'].append(self.anchor)
            self.anchor = None
        if tag == 'details' and self.details:
            self.blocks.append(self.details.pop())

    def result(self, month: date) -> tuple[dict[str, dict[str, int]], dict[str, int], bool]:
        projects: dict[str, dict[str, int]] = {}
        activity = {'commits': 0, 'pull_requests': 0, 'issues': 0}
        seen = set()
        incomplete = False
        matched = False
        for block in self.blocks:
            summary = ' '.join(''.join(block['summary']).split())
            match = re.search(r'(?:Created|Opened) ([\d,]+) (commits?|pull requests?|issues?)\b', summary)
            if not match:
                continue
            matched = True
            kind = 'commits' if match[2].startswith('commit') else 'pull_requests' if match[2].startswith('pull') else 'issues'
            expected = int(match[1].replace(',', ''))
            activity[kind] += expected
            listed = 0
            for anchor in block['anchors']:
                url = urlsplit(anchor['href'])
                if url.netloc and url.netloc != 'github.com':
                    continue
                parts = url.path.strip('/').split('/')
                if len(parts) < 3 or not REPO_NAME.fullmatch('/'.join(parts[:2])):
                    continue
                name = '/'.join(parts[:2])
                amount = 0
                if kind == 'commits' and parts[2] == 'commits':
                    since = parse_qs(url.query).get('since', [''])[0]
                    count = re.fullmatch(r'([\d,]+) commits?', ''.join(anchor['text']).strip())
                    if not count or not since.startswith(month.strftime('%Y-%m')):
                        continue
                    key = (name, kind, since)
                    amount = int(count[1].replace(',', ''))
                elif kind in {'pull_requests', 'issues'} and len(parts) == 4 and parts[2] == ('pull' if kind == 'pull_requests' else 'issues') and parts[3].isdigit():
                    key = (name, kind, parts[3])
                    amount = 1
                else:
                    continue
                if key in seen:
                    continue
                seen.add(key)
                projects.setdefault(name, {item: 0 for item in KINDS})[kind] += amount
                listed += amount
            if listed < expected:
                incomplete = True
        # A page containing only a calendar is not proof of zero project activity.
        empty = re.search(r'(?:No activity|No contributions) (?:in|during|for)\b', ' '.join(''.join(self.text).split()), re.IGNORECASE)
        if not self.has_timeline and not matched and not empty:
            raise ValueError('Public activity timeline not found')
        return projects, activity, incomplete


async def fetch_public_overview(username: str, start: date, end: date) -> ContributionOverview:
    semaphore = asyncio.Semaphore(3)
    months = []
    current = date(start.year, start.month, 1)
    while current <= end:
        next_month = date(current.year + (current.month == 12), current.month % 12 + 1, 1)
        months.append((current, min(end, next_month - timedelta(days=1))))
        current = next_month
    headers = {'User-Agent': 'github-profile-svg-api', 'Accept': 'text/html', 'Accept-Language': 'en-US', 'X-Requested-With': 'XMLHttpRequest'}
    years = set()
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True, headers=headers) as client:
            async def month_activity(
                month: date,
                until: date,
            ) -> tuple[dict[str, dict[str, int]], dict[str, int], bool, set[int]]:
                async with semaphore:
                    response = await client.get('https://github.com/' + username, params={'tab': 'contributions', 'from': month.isoformat(), 'to': until.isoformat()})
                response.raise_for_status()
                parser = PublicActivityParser()
                parser.feed(response.text)
                values, activity, incomplete = parser.result(month)
                return values, activity, incomplete, parser.years
            results = await asyncio.gather(*(month_activity(*item) for item in months), return_exceptions=True)
        values: dict[str, dict[str, int]] = {}
        totals = {'commits': 0, 'pull_requests': 0, 'issues': 0}
        for result in results:
            if not isinstance(result, BaseException):
                years.update(result[3])
        incomplete = False
        for result in results:
            if isinstance(result, BaseException):
                raise result
            projects, activity, limited, found_years = result
            years.update(found_years)
            incomplete |= limited
            for kind, amount in activity.items():
                totals[kind] += amount
            for name, counts in projects.items():
                entry = values.setdefault(name, {kind: 0 for kind in KINDS})
                for kind, amount in counts.items():
                    entry[kind] += amount
        message = 'Public monthly activity; review totals are unavailable.'
        if incomplete:
            message += ' Some repository details are omitted by GitHub.'
        final_projects = tuple(replace(project, reviews=None) for project in sorted_projects(values))
        return ContributionOverview(final_projects, {**totals, 'reviews': None}, 'partial', message, tuple(sorted(years, reverse=True)), 'github-public-timeline')
    except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError):
        return ContributionOverview(message='GitHub project activity could not be loaded. The calendar is still available.', years=tuple(sorted(years, reverse=True)))


def graphql_overview(
    collection: dict[str, Any],
    years: list[int],
    commit_override: dict[str, int] | None = None,
) -> ContributionOverview:
    values: dict[str, dict[str, int]] = {}
    incomplete = False
    fields = {
        'commits': 'commitContributionsByRepository', 'pull_requests': 'pullRequestContributionsByRepository',
        'issues': 'issueContributionsByRepository', 'reviews': 'pullRequestReviewContributionsByRepository',
    }
    for kind, field in fields.items():
        entries = collection[field]
        if len(entries) >= 100:
            incomplete = True
        for entry in entries:
            repo = entry['repository']
            if repo.get('isPrivate'):
                continue
            name = repo['nameWithOwner']
            if not REPO_NAME.fullmatch(name):
                raise ValueError('Invalid repository name')
            connection = entry['contributions']
            if kind == 'commits':
                if commit_override is not None:
                    amount = commit_override.get(name, 0)
                elif connection['pageInfo']['hasNextPage']:
                    raise ValueError('Commit-day pagination must be resolved')
                else:
                    counts = [node['commitCount'] for node in connection['nodes']]
                    if any(type(count) is not int or count < 0 for count in counts):
                        raise ValueError('Invalid commit-day count')
                    amount = sum(counts)
            else:
                amount = connection['totalCount']
            if type(amount) is not int or amount < 0:
                raise ValueError('Invalid project contribution count')
            values.setdefault(name, {item: 0 for item in KINDS})[kind] = amount
    if commit_override is not None:
        for name, amount in commit_override.items():
            values.setdefault(name, {item: 0 for item in KINDS})['commits'] = amount
    activity = {kind: collection[field] for kind, field in {
        'commits': 'totalCommitContributions', 'pull_requests': 'totalPullRequestContributions',
        'issues': 'totalIssueContributions', 'reviews': 'totalPullRequestReviewContributions',
    }.items()}
    if any(type(value) is not int or value < 0 for value in activity.values()):
        raise ValueError('Invalid activity totals')
    return ContributionOverview(sorted_projects(values), activity, 'partial' if incomplete else 'complete',
                                'Public repository details; activity totals follow token visibility.' + (' Repository lists may be limited.' if incomplete else ''),
                                tuple(sorted(set(years), reverse=True)), 'github-graphql')
