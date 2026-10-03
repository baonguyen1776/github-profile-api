from __future__ import annotations

import asyncio
import os
import time
from collections import Counter, OrderedDict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping, TypeAlias

import httpx

from services.contribution_overview import ContributionOverview, ProjectContribution, REPO_NAME
from services.contributions import ContributionDay, ContributionReport, _check_response
from services.github import API_BASE, TIMEOUT, GitHubClientError, _headers

KINDS = ('commits', 'pull_requests', 'issues', 'reviews')
RepositoryEvent: TypeAlias = tuple[str, date, int]
_CACHE: OrderedDict[
    tuple[str, str, int, date, bool], tuple[float, ContributionReport]
] = OrderedDict()


def valid_repository(value: str) -> bool:
    return bool(REPO_NAME.fullmatch(value)) and value.split('/')[-1] not in {'.', '..'}


def event_day(value: str) -> date:
    # GitHub's authored date (including its supplied offset), not the fetch date.
    return datetime.fromisoformat(value.replace('Z', '+00:00')).date()


def repository_report(
    username: str,
    repository: str,
    year: int,
    today: date,
    events: Mapping[str, RepositoryEvent],
    *,
    source: str,
    reviews_known: bool,
) -> ContributionReport:
    start, end = date(year, 1, 1), min(today, date(year, 12, 31))
    commit_daily: Counter[date] = Counter()
    totals: dict[str, int] = {kind: 0 for kind in KINDS}
    for kind, day, amount in events.values():
        if start <= day <= end:
            if kind not in totals or type(amount) is not int or amount < 0:
                raise ValueError('Invalid repository event')
            totals[kind] += amount
            if kind == 'commits':
                commit_daily[day] += amount

    # Keep the same full-year/YTD calendar geometry when a repository is
    # selected. Only commit days for that repository are highlighted; the
    # other event categories remain available to the activity chart below.
    peak = max(commit_daily.values(), default=0)
    days = []
    for index in range((end - start).days + 1):
        day = start + timedelta(days=index)
        count = commit_daily[day]
        level = min(4, 1 + (count-1)*4//max(1,peak)) if count else 0
        days.append(ContributionDay(day,count,level))
    reviews = totals['reviews'] if reviews_known else None
    activity: dict[str, int | None] = {**totals, 'reviews': reviews}
    project = ProjectContribution(
        repository,
        commits=totals['commits'],
        pull_requests=totals['pull_requests'],
        issues=totals['issues'],
        reviews=reviews,
    )
    message = 'GitHub contribution events for this repository.' if reviews_known else 'Public default-branch commits and opened PRs/issues; review data is not included. Counts may differ from the GitHub profile calendar.'
    overview = ContributionOverview((project,) if project.total else (), activity, 'complete' if reviews_known else 'partial', message, (year,), source)
    return ContributionReport(username, tuple(days), end, source, year, today, overview, repository)


async def rest_events(
    client: httpx.AsyncClient,
    username: str,
    repository: str,
    start: date,
    end: date,
) -> dict[str, RepositoryEvent]:
    async def commits() -> dict[str, RepositoryEvent]:
        events: dict[str, RepositoryEvent] = {}
        for page in range(1,101):
            response = await client.get(f'{API_BASE}/repos/{repository}/commits',params={'author':username,'since':start.isoformat()+'T00:00:00Z','until':end.isoformat()+'T23:59:59Z','per_page':100,'page':page})
            if response.status_code == 409 and response.json().get('message') == 'Git Repository is empty.':
                return events
            _check_response(response)
            rows = response.json()
            if not isinstance(rows,list):
                raise ValueError('Invalid commits response')
            for row in rows:
                author = row.get('author') or {}
                if author.get('login','').casefold() != username.casefold():
                    continue
                day = event_day(row['commit']['author']['date'])
                if start <= day <= end:
                    events['commit:'+row['sha']] = ('commits',day,1)
            if 'next' not in response.links:
                return events
        raise GitHubClientError('Repository commit history exceeds the supported scan size')

    async def issues() -> dict[str, RepositoryEvent]:
        events: dict[str, RepositoryEvent] = {}
        for page in range(1,101):
            response = await client.get(f'{API_BASE}/repos/{repository}/issues',params={'creator':username,'state':'all','since':start.isoformat()+'T00:00:00Z','per_page':100,'page':page})
            _check_response(response)
            rows = response.json()
            if not isinstance(rows,list):
                raise ValueError('Invalid issues response')
            for row in rows:
                if (row.get('user') or {}).get('login','').casefold() != username.casefold():
                    continue
                day = event_day(row['created_at'])
                if start <= day <= end:
                    kind = 'pull_requests' if 'pull_request' in row else 'issues'
                    events['issue:'+str(row['number'])] = (kind,day,1)
            if 'next' not in response.links:
                return events
        raise GitHubClientError('Repository issue history exceeds the supported scan size')
    results = await asyncio.gather(commits(),issues(),return_exceptions=True)
    merged: dict[str, RepositoryEvent] = {}
    for result in results:
        if isinstance(result,BaseException):
            raise result
        merged.update(result)
    return merged


async def gql(
    client: httpx.AsyncClient,
    query: str,
    username: str,
    start: date,
    end: date,
    cursor: str | None = None,
) -> dict[str, Any]:
    variables: dict[str, Any] = {'login':username,'from':start.isoformat()+'T00:00:00Z','to':end.isoformat()+'T23:59:59Z'}
    if '$cursor' in query:
        variables['cursor'] = cursor
    response = await client.post(API_BASE+'/graphql',json={'query':query,'variables':variables})
    _check_response(response)
    payload = response.json()
    if payload.get('errors') or not (payload.get('data') or {}).get('user'):
        raise GitHubClientError('Repository contribution query failed')
    return payload['data']['user']['contributionsCollection']


async def graphql_events(
    client: httpx.AsyncClient,
    username: str,
    repository: str,
    start: date,
    end: date,
) -> dict[str, RepositoryEvent]:
    commit_query = '''query RepoCommitDays($login:String!,$from:DateTime!,$to:DateTime!){user(login:$login){contributionsCollection(from:$from,to:$to){commitContributionsByRepository(maxRepositories:100){repository{nameWithOwner isPrivate} contributions(first:100){nodes{occurredAt commitCount} pageInfo{hasNextPage}}}}}}'''
    async def commits(first: date, last: date) -> dict[str, RepositoryEvent]:
        data = await gql(client,commit_query,username,first,last)
        entries = data['commitContributionsByRepository']
        entry = next((item for item in entries if item['repository']['nameWithOwner'].casefold()==repository.casefold() and not item['repository']['isPrivate']),None)
        if entry is None:
            if len(entries)>=100:
                raise GitHubClientError('Repository is outside the GitHub contribution list limit')
            return {}
        connection = entry['contributions']
        if connection['pageInfo']['hasNextPage']:
            if first==last:
                raise GitHubClientError('Incomplete repository commit-day data')
            middle = first+(last-first)//2
            left = await commits(first,middle)
            left.update(await commits(middle+timedelta(days=1),last))
            return left
        return {'commit:'+node['occurredAt']:('commits',event_day(node['occurredAt']),node['commitCount']) for node in connection['nodes']}

    async def category(kind: str, field: str, object_field: str) -> dict[str, RepositoryEvent]:
        query = 'query RepoEvents($login:String!,$from:DateTime!,$to:DateTime!,$cursor:String){user(login:$login){contributionsCollection(from:$from,to:$to){'+field+'(first:100,after:$cursor){nodes{occurredAt '+object_field+'{id repository{nameWithOwner isPrivate}}} pageInfo{hasNextPage endCursor}}}}}'
        events: dict[str, RepositoryEvent] = {}
        cursor: str | None = None
        for _ in range(100):
            connection = (await gql(client,query,username,start,end,cursor))[field]
            for node in connection['nodes']:
                obj = node[object_field]
                if obj['repository']['nameWithOwner'].casefold()==repository.casefold() and not obj['repository']['isPrivate']:
                    events[kind+':'+obj['id']] = (kind,event_day(node['occurredAt']),1)
            page = connection['pageInfo']
            if not page['hasNextPage']:
                return events
            if not page['endCursor'] or cursor==page['endCursor']:
                raise ValueError('Invalid contribution cursor')
            cursor = page['endCursor']
        raise GitHubClientError('Repository event history exceeds the supported scan size')
    results = await asyncio.gather(commits(start,end), category('pull_requests','pullRequestContributions','pullRequest'), category('issues','issueContributions','issue'), category('reviews','pullRequestReviewContributions','pullRequest'),return_exceptions=True)
    merged: dict[str, RepositoryEvent] = {}
    for result in results:
        if isinstance(result,BaseException):
            raise result
        merged.update(result)
    return merged


async def fetch_repository_contributions(
    username: str,
    repository: str,
    *,
    year: int,
    as_of: date | None = None,
) -> ContributionReport:
    if not valid_repository(repository):
        raise GitHubClientError('Invalid repository name',422)
    today = as_of or datetime.now(timezone.utc).date()
    if not 2008 <= year <= today.year:
        raise GitHubClientError('Invalid contribution year',422)
    token = bool(os.getenv('GITHUB_TOKEN'))
    key = (username.casefold(),repository.casefold(),year,today,token)
    cached = _CACHE.get(key)
    if cached and time.monotonic()-cached[0]<3600:
        _CACHE.move_to_end(key)
        return cached[1]
    start,end = date(year,1,1),min(today,date(year,12,31))
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT,headers=_headers()) as client:
            response = await client.get(f'{API_BASE}/repos/{repository}')
            _check_response(response)
            metadata = response.json()
            if metadata.get('private',True):
                raise GitHubClientError('Only public repositories can be displayed',404)
            repository = metadata['full_name']
            if not valid_repository(repository):
                raise ValueError('Invalid repository metadata')
            events = await (graphql_events if token else rest_events)(client,username,repository,start,end)
        report = repository_report(username,repository,year,today,events,source='github-graphql-repository' if token else 'github-rest-repository',reviews_known=token)
    except GitHubClientError:
        raise
    except (httpx.HTTPError,ValueError,KeyError,TypeError,AttributeError) as exc:
        raise GitHubClientError('Repository activity is temporarily unavailable') from exc
    _CACHE[key] = (time.monotonic(),report)
    while len(_CACHE)>64:
        _CACHE.popitem(last=False)
    return report
