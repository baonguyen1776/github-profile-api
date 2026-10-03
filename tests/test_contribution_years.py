from __future__ import annotations

import json
import unittest
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from datetime import date, datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient

from app import app
from renderers.contributions import render_contributions_svg
from services import contributions as service
from services.contribution_overview import ContributionOverview, ProjectContribution, PublicActivityParser, fetch_public_overview, graphql_overview
from services.contributions import ContributionDay, ContributionReport, make_report
from tests.test_contributions import AS_OF, calendar_html


def annual_days(
    year: int,
    counts: Mapping[date, int] | None = None,
) -> list[ContributionDay]:
    return service.parse_public_calendar(calendar_html(year, counts))


def overview_collection() -> dict[str, Any]:
    return {
        'commitContributionsByRepository': [
            {'repository': {'nameWithOwner':'other/project','isPrivate':False}, 'contributions': {'nodes':[{'commitCount':7},{'commitCount':4}], 'pageInfo':{'hasNextPage':False}}},
            {'repository': {'nameWithOwner':'test/private','isPrivate':True}, 'contributions': {'nodes':[{'commitCount':2}], 'pageInfo':{'hasNextPage':False}}},
        ],
        'pullRequestContributionsByRepository':[{'repository':{'nameWithOwner':'other/project','isPrivate':False}, 'contributions':{'totalCount':3}}],
        'issueContributionsByRepository':[], 'pullRequestReviewContributionsByRepository':[],
        'totalCommitContributions':13, 'totalPullRequestContributions':3,
        'totalIssueContributions':0, 'totalPullRequestReviewContributions':0,
    }


def identity_report(report: ContributionReport) -> ContributionReport:
    return report


class YearStatisticsTests(unittest.TestCase):
    def test_year_to_date_and_leap_year_have_exact_dates(self) -> None:
        current = make_report('test', annual_days(2026), AS_OF, 'public', year=2026)
        self.assertEqual((current.days[0].date,current.as_of,len(current.days)), (date(2026,1,1),AS_OF,276))
        leap = make_report('test', annual_days(2024), AS_OF, 'public', year=2024)
        self.assertEqual(len(leap.days),366)
        self.assertEqual(leap.as_of,date(2024,12,31))
        self.assertIn(date(2024,2,29),[day.date for day in leap.days])
        with self.assertRaises(ValueError):
            make_report('test', annual_days(2027), AS_OF, 'public', year=2027)

    def test_historical_year_end_has_no_today_grace_and_streak_stays_in_year(self) -> None:
        counts = {date(2025,12,30):1, date(2026,1,1):1}
        previous = make_report('test',annual_days(2025,counts),AS_OF,'public',year=2025)
        self.assertEqual(previous.current_streak,0)
        current = make_report('test',annual_days(2026,counts),date(2026,1,2),'public',year=2026)
        self.assertEqual(current.current_streak,1)

    def test_year_svg_shows_all_months_future_placeholders_and_correct_project_links(self) -> None:
        overview = ContributionOverview((ProjectContribution('other/project',commits=12),), {'commits':12,'pull_requests':0,'issues':0,'reviews':None},'partial','Reviews unavailable.',(2026,2025),'public')
        report = make_report('test',annual_days(2026,{AS_OF:5}),AS_OF,'public',year=2026,overview=overview)
        for theme in ('dark','light'):
            svg = render_contributions_svg(report=report,theme=theme)
            tree = ET.fromstring(svg)
            ns = {'s':'http://www.w3.org/2000/svg'}
            cells = tree.findall('.//s:rect[@data-date]',ns)
            future = tree.findall('.//s:rect[@data-future-date]',ns)
            self.assertEqual((len(cells),len(future)),(276,89))
            self.assertTrue(all('data-count' not in cell.attrib for cell in future))
            self.assertEqual(sum(int(cell.attrib['data-count']) for cell in cells),5)
            self.assertIn('Dec',svg)
            self.assertIn('href="https://github.com/other/project"',svg)
            self.assertIn('Code review',svg)
            self.assertEqual(tree.attrib['height'],'502')
            self.assertFalse(tree.findall('.//s:circle[@data-activity-point="reviews"]',ns))
            review_axis = tree.find('.//s:path[@data-activity-axis="reviews"]',ns)
            self.assertIsNotNone(review_axis)
            assert review_axis is not None
            self.assertEqual(review_axis.attrib['data-known'],'false')
            self.assertEqual(len(tree.findall('.//s:polygon[@data-activity-polygon="known"]',ns)),1)
            self.assertEqual(len(tree.findall('.//s:circle[@data-activity-unavailable="reviews"]',ns)),1)
            self.assertIn('N/A', svg)


class OverviewParserTests(unittest.TestCase):
    def test_monthly_rollup_uses_contributed_projects_and_deduplicates_links(self) -> None:
        parser = PublicActivityParser()
        parser.feed('''<a id="year-link-2026"></a><a id="year-link-2024"></a>
        <div class="TimelineItem"><details><summary>Created 12 commits in 2 repositories</summary>
        <a href="/other/project/commits?since=2026-01-01">10 commits</a>
        <a href="/other/project/commits?since=2026-01-01">10 commits</a>
        <a href="/test/own/commits?since=2026-01-01">2 commits</a>
        <a href="/test/older/commits?since=2025-12-01">30 commits</a></details>
        <details><summary>Opened 1 pull request</summary><details><summary>other/project</summary><a href="/other/project/pull/5">Title</a><a href="/other/project/pull/5">Same</a></details></details>
        <details><summary>Opened 1 issue</summary><a href="/other/project/issues/7">Issue</a></details></div>''')
        values, activity, limited = parser.result(date(2026,1,1))
        self.assertEqual(values['other/project'],{'commits':10,'pull_requests':1,'issues':1,'reviews':0})
        self.assertNotIn('test/older',values)
        self.assertEqual(activity,{'commits':12,'pull_requests':1,'issues':1})
        self.assertFalse(limited)
        self.assertEqual(parser.years,{2026,2024})

    def test_truncation_is_explicit_and_calendar_only_is_not_zero_activity(self) -> None:
        parser = PublicActivityParser()
        parser.feed('<div class="TimelineItem"><details><summary>Created 80 commits in 8 repositories</summary><a href="/test/one/commits?since=2026-02-01">20 commits</a></details></div>')
        self.assertTrue(parser.result(date(2026,2,1))[2])
        empty = PublicActivityParser()
        empty.feed('<div>Calendar only</div>')
        with self.assertRaises(ValueError):
            empty.result(date(2026,2,1))

    def test_explicit_empty_month_is_zero_known_activity(self) -> None:
        parser = PublicActivityParser()
        parser.feed('<div>test had no activity during this period.</div>')
        projects, activity, limited = parser.result(date(2025,1,1))
        self.assertEqual(projects,{})
        self.assertEqual(sum(activity.values()),0)
        self.assertFalse(limited)

    def test_graphql_sums_commits_not_active_days_and_hides_private_repo_names(self) -> None:
        overview = graphql_overview(overview_collection(),[2024,2026,2024])
        self.assertEqual(len(overview.projects),1)
        self.assertEqual(overview.projects[0].commits,11)
        self.assertEqual(overview.projects[0].pull_requests,3)
        self.assertEqual(overview.years,(2026,2024))
        collection = overview_collection()
        collection['commitContributionsByRepository'][0]['contributions']['pageInfo']['hasNextPage'] = True
        with self.assertRaises(ValueError):
            graphql_overview(collection,[2026])


class YearFetchTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        service._CACHE.clear()

    async def asyncTearDown(self) -> None:
        service._CACHE.clear()

    async def test_public_year_cache_is_separate_and_optional_overview_does_not_change_calendar(self) -> None:
        urls = []
        def handle(request: httpx.Request) -> httpx.Response:
            urls.append(str(request.url))
            year = int(request.url.params['from'][:4])
            return httpx.Response(200,text=calendar_html(year,{date(year,1,1):3}))
        client_type = httpx.AsyncClient
        def factory(**kwargs: Any) -> httpx.AsyncClient:
            return client_type(transport=httpx.MockTransport(handle),**kwargs)
        with patch.dict('os.environ',{},clear=True), patch('services.contributions.httpx.AsyncClient',side_effect=factory), patch('services.contributions.fetch_public_overview',AsyncMock(return_value=ContributionOverview())):
            first = await service.fetch_contributions('test',as_of=AS_OF,year=2026)
            again = await service.fetch_contributions('TEST',as_of=AS_OF,year=2026)
            older = await service.fetch_contributions('test',as_of=AS_OF,year=2025)
        self.assertIs(first,again)
        self.assertEqual(len(urls),2)
        self.assertEqual((first.year,older.year),(2026,2025))
        self.assertIsNotNone(first.overview)
        assert first.overview is not None
        self.assertEqual(first.overview.status,'unavailable')
        self.assertEqual(first.total,3)

    async def test_public_months_end_before_next_month_and_unknown_reviews_stay_unknown(self) -> None:
        periods = []
        def handle(request: httpx.Request) -> httpx.Response:
            periods.append((request.url.params['from'],request.url.params['to']))
            return httpx.Response(200,text='<a id="year-link-2026"></a><div class="TimelineItem"><details><summary>Created 3 commits</summary><a href="/other/project/commits?since='+request.url.params['from']+'">3 commits</a></details></div>')
        client_type = httpx.AsyncClient
        def factory(**kwargs: Any) -> httpx.AsyncClient:
            return client_type(transport=httpx.MockTransport(handle),**kwargs)
        with patch('services.contribution_overview.httpx.AsyncClient',side_effect=factory):
            overview = await fetch_public_overview('test',date(2026,1,1),date(2026,2,3))
        self.assertEqual(sorted(periods),[('2026-01-01','2026-01-31'),('2026-02-01','2026-02-03')])
        self.assertEqual(overview.projects[0].commits,6)
        assert overview.activity is not None
        self.assertEqual(overview.activity['reviews'],None)
        self.assertIsNone(overview.projects[0].reviews)
        self.assertEqual(overview.status,'partial')

    async def test_quarter_queries_resolve_more_than_one_hundred_commit_days(self) -> None:
        calls = []
        def handle(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            variables = body['variables']
            calls.append(variables)
            if len(calls) == 1:
                collection = overview_collection()
                collection['commitContributionsByRepository'][0]['contributions']['pageInfo']['hasNextPage'] = True
                collection['contributionCalendar'] = {'weeks':[{'contributionDays':[{'date':day.date.isoformat(),'contributionCount':day.count,'contributionLevel':'NONE'} for day in annual_days(2025)]}]}
                return httpx.Response(200,json={'data':{'user':{'login':'test','history':{'contributionYears':[2026,2025]},'contributionsCollection':collection}}})
            entries = [{'repository':{'nameWithOwner':'other/project','isPrivate':False},'contributions':{'nodes':[{'commitCount':7}], 'pageInfo':{'hasNextPage':False}}}]
            return httpx.Response(200,json={'data':{'user':{'contributionsCollection':{'commitContributionsByRepository':entries}}}})
        client_type = httpx.AsyncClient
        def factory(**kwargs: Any) -> httpx.AsyncClient:
            return client_type(transport=httpx.MockTransport(handle),**kwargs)
        with patch.dict('os.environ',{'GITHUB_TOKEN':'fixture'}), patch('services.contributions.httpx.AsyncClient',side_effect=factory):
            report = await service.fetch_contributions('test',as_of=AS_OF,year=2025)
        self.assertEqual(len(calls),5)
        self.assertIsNotNone(report.overview)
        assert report.overview is not None
        self.assertEqual(report.overview.projects[0].commits,28)
        self.assertEqual([(call['from'][:10],call['to'][:10]) for call in calls[1:]], [('2025-01-01','2025-03-31'),('2025-04-01','2025-06-30'),('2025-07-01','2025-09-30'),('2025-10-01','2025-12-31')])


@patch("routes.contributions.embed_avatars",new=AsyncMock(side_effect=identity_report))
class YearRouteTests(unittest.TestCase):
    def test_year_validation_and_preview_navigation(self) -> None:
        client = TestClient(app)
        with patch('routes.contributions.fetch_contributions',AsyncMock()) as fetch:
            future = datetime.now(timezone.utc).year + 1
            for path in ('/api/contributions','/api/contribution-data','/preview/contributions'):
                for year in (2007,future):
                    self.assertEqual(client.get(f'{path}?username=test&year={year}').status_code,422)
            fetch.assert_not_called()
        overview = ContributionOverview((ProjectContribution('other/project',commits=3),),{'commits':3,'pull_requests':0,'issues':0,'reviews':None},'partial','Public monthly activity.',(2026,2025),'public')
        report = make_report('test',annual_days(2025),AS_OF,'public',year=2025,overview=overview)
        with patch('routes.contributions.fetch_contributions',AsyncMock(return_value=report)) as fetch:
            preview = client.get('/preview/contributions?username=test&year=2025&theme=light')
            data = client.get('/api/contribution-data?username=test&year=2025')
        self.assertEqual(preview.status_code,200)
        self.assertIn('name="year" value="2026"',preview.text)
        self.assertIn('theme=light',preview.text)
        self.assertIn('https://github.com/other/project',preview.text)
        self.assertIn('Search repositories',preview.text)
        self.assertEqual(data.json()['year'],2025)
        self.assertEqual(data.json()['streak_label'],'year_end')
        self.assertIsNone(data.json()['overview']['activity']['reviews'])
        fetch.assert_awaited_with('test',year=2025)


if __name__ == '__main__':
    unittest.main()
