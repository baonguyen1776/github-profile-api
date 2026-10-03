import json
import unittest
import xml.etree.ElementTree as ET
from datetime import date
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient

from app import app
from services import repository_contributions as service
from services.repository_contributions import repository_report, fetch_repository_contributions
from services.contribution_overview import ContributionOverview, ProjectContribution
from services.github import GitHubClientError
from renderers.contributions import render_contributions_svg
from tests.test_contribution_years import annual_days
from services.contributions import ContributionReport, make_report

TODAY=date(2026,10,3)


def identity_report(report: ContributionReport) -> ContributionReport:
    return report


class RepositoryReportTests(unittest.TestCase):
    def test_calendar_keeps_full_year_geometry_and_highlights_only_repo_commits(self) -> None:
        events={'c1':('commits',date(2026,5,25),2),'p1':('pull_requests',date(2026,6,28),1),'old':('commits',date(2025,12,31),20)}
        report=repository_report('test','other/project',2026,TODAY,events,source='github-rest-repository',reviews_known=False)
        self.assertEqual(report.total,2)
        self.assertEqual((report.days[0].date,report.days[-1].date),(date(2026,1,1),TODAY))
        self.assertEqual(len(report.days),276)
        self.assertEqual(report.current_streak,0)
        self.assertIsNotNone(report.overview)
        assert report.overview is not None
        self.assertIsNotNone(report.overview.activity)
        assert report.overview.activity is not None
        self.assertEqual(report.overview.activity['pull_requests'],1)
        self.assertIsNone(report.overview.activity['reviews'])
        self.assertEqual(report.repository,'other/project')
        ns={'s':'http://www.w3.org/2000/svg'}
        svg=ET.fromstring(render_contributions_svg(report=report,theme='auto'))
        cells=svg.findall('.//s:rect[@data-date]',ns)
        self.assertEqual(len(cells),276)
        self.assertEqual(sum(int(c.attrib['data-count']) for c in cells),2)
        self.assertEqual(len(svg.findall('.//s:rect[@data-future-date]',ns)),89)
        self.assertIn('prefers-color-scheme:dark',ET.tostring(svg).decode())
        self.assertEqual(len(svg.findall('.//s:path[@data-radar-grid]',ns)),4)

    def test_verified_empty_repo_year_has_no_fabricated_active_period(self) -> None:
        report=repository_report('test','other/project',2024,TODAY,{},source='rest',reviews_known=False)
        self.assertEqual(len(report.days),366)
        self.assertEqual(report.total,0)
        self.assertEqual(report.active_days,0)
        self.assertIsNotNone(report.overview)
        assert report.overview is not None
        self.assertFalse(report.overview.projects)


class RepositoryFetchTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        service._CACHE.clear()
    async def asyncTearDown(self) -> None:
        service._CACHE.clear()

    async def test_rest_pagination_authors_dates_and_cache_are_repo_specific(self) -> None:
        paths=[]
        def commit(sha: str, author: str, day: str) -> dict[str, Any]:
            return {'sha':sha,'author':{'login':author},'commit':{'author':{'date':day}}}
        def handle(request: httpx.Request) -> httpx.Response:
            paths.append(str(request.url))
            if request.url.path.endswith('/commits'):
                if request.url.params['page']=='1':
                    return httpx.Response(200,json=[commit('one','test','2026-05-25T10:00:00Z'),commit('other','someone','2026-05-26T10:00:00Z')],headers={'Link':'<https://api.github.com/repos/other/project/commits?page=2>; rel="next"'})
                return httpx.Response(200,json=[commit('one','test','2026-05-25T10:00:00Z'),commit('two','test','2026-06-28T10:00:00Z')])
            if request.url.path.endswith('/issues'):
                return httpx.Response(200,json=[{'number':1,'user':{'login':'test'},'created_at':'2026-06-04T12:00:00Z','pull_request':{}},{'number':2,'user':{'login':'test'},'created_at':'2025-12-31T12:00:00Z'},{'number':3,'user':{'login':'other'},'created_at':'2026-06-04T12:00:00Z'}])
            return httpx.Response(200,json={'full_name':'other/project','private':False})
        client_type=httpx.AsyncClient
        def factory(**kwargs: Any) -> httpx.AsyncClient:
            return client_type(transport=httpx.MockTransport(handle),**kwargs)
        with patch.dict('os.environ',{},clear=True),patch('services.repository_contributions.httpx.AsyncClient',side_effect=factory):
            report=await fetch_repository_contributions('test','other/project',year=2026,as_of=TODAY)
            again=await fetch_repository_contributions('TEST','OTHER/PROJECT',year=2026,as_of=TODAY)
        self.assertIs(report,again)
        self.assertEqual(len(paths),4)
        self.assertEqual(report.total,2)
        self.assertIsNotNone(report.overview)
        assert report.overview is not None
        self.assertEqual(report.overview.activity,{'commits':2,'pull_requests':1,'issues':0,'reviews':None})

    async def test_failures_and_private_repositories_are_not_zero_or_cached(self) -> None:
        for mode in ('private','rate-limit'):
            def handle(request: httpx.Request, current_mode: str = mode) -> httpx.Response:
                if current_mode=='private':
                    return httpx.Response(200,json={'full_name':'other/project','private':True})
                return httpx.Response(429,json={'message':'Rate limit'})
            client=httpx.AsyncClient(transport=httpx.MockTransport(handle))
            with patch.dict('os.environ',{},clear=True),patch('services.repository_contributions.httpx.AsyncClient',return_value=client):
                with self.assertRaises(GitHubClientError):
                    await fetch_repository_contributions('test','other/project',year=2026,as_of=TODAY)
            self.assertFalse(service._CACHE)

    async def test_graphql_review_cursor_scopes_repo_and_preserves_review_dates(self) -> None:
        def handle(request: httpx.Request) -> httpx.Response:
            if request.method=='GET':
                return httpx.Response(200,json={'full_name':'other/project','private':False})
            body=json.loads(request.content); query=body['query']
            if 'commitContributionsByRepository' in query:
                payload: dict[str, Any] = {'commitContributionsByRepository':[{'repository':{'nameWithOwner':'other/project','isPrivate':False},'contributions':{'nodes':[{'occurredAt':'2026-06-01T00:00:00Z','commitCount':4}],'pageInfo':{'hasNextPage':False}}}]}
            else:
                field=next(f for f in ('pullRequestReviewContributions','pullRequestContributions','issueContributions') if f+'(' in query)
                nodes=[]; more=False; cursor=None
                if field=='pullRequestReviewContributions':
                    if body['variables']['cursor'] is None:
                        nodes=[{'occurredAt':'2026-06-02T00:00:00Z','pullRequest':{'id':'elsewhere','repository':{'nameWithOwner':'elsewhere/project','isPrivate':False}}}];more=True;cursor='second'
                    else:
                        nodes=[{'occurredAt':'2026-06-03T00:00:00Z','pullRequest':{'id':'wanted','repository':{'nameWithOwner':'other/project','isPrivate':False}}}]
                payload={field:{'nodes':nodes,'pageInfo':{'hasNextPage':more,'endCursor':cursor}}}
            return httpx.Response(200,json={'data':{'user':{'contributionsCollection':payload}}})
        client_type=httpx.AsyncClient
        def factory(**kwargs: Any) -> httpx.AsyncClient:
            return client_type(transport=httpx.MockTransport(handle),**kwargs)
        with patch.dict('os.environ',{'GITHUB_TOKEN':'fixture'}),patch('services.repository_contributions.httpx.AsyncClient',side_effect=factory):
            report=await fetch_repository_contributions('test','other/project',year=2026,as_of=TODAY)
        self.assertEqual(report.total,4)
        self.assertIsNotNone(report.overview)
        assert report.overview is not None
        self.assertIsNotNone(report.overview.activity)
        assert report.overview.activity is not None
        self.assertEqual(report.overview.activity['reviews'],1)
        self.assertEqual(report.days[-1].date,TODAY)


class RepoRouteTests(unittest.TestCase):
    def test_selecting_repo_uses_scoped_report_and_preview_marks_button(self) -> None:
        base=make_report('test',annual_days(2026),TODAY,'public',year=2026,overview=ContributionOverview((ProjectContribution('other/project',commits=20),ProjectContribution('other/different',commits=100)),years=(2026,2025)))
        scoped=repository_report('test','other/project',2026,TODAY,{'c':('commits',date(2026,6,4),2)},source='rest',reviews_known=False)
        with patch('routes.contributions.fetch_contributions',AsyncMock(return_value=base)),patch('routes.contributions.fetch_repository_contributions',AsyncMock(return_value=scoped)) as fetch,patch('routes.contributions.embed_avatars',AsyncMock(side_effect=identity_report)):
            client=TestClient(app)
            data=client.get('/api/contribution-data?username=test&year=2026&repo=other/project').json()
            response=client.get('/preview/contributions?username=test&year=2026&repo=other/project&theme=auto')
        self.assertEqual(data['total_contributions'],2)
        self.assertEqual(data['from'],'2026-01-01')
        self.assertEqual(data['to'],'2026-10-03')
        self.assertEqual(data['repository'],'other/project')
        self.assertIn('value="other/project" aria-pressed="true"',response.text)
        self.assertIn('data-theme="auto"',response.text)
        self.assertIn('Search repositories',response.text)
        self.assertIn('section=calendar',response.text)
        fetch.assert_awaited_with('test','other/project',year=2026)

    def test_bad_repository_inputs_do_not_fetch(self) -> None:
        with patch('routes.contributions.fetch_repository_contributions',AsyncMock()) as fetch:
            client=TestClient(app)
            for path in ('/api/contributions','/api/contribution-data','/preview/contributions'):
                for repo in ('bad','other/..','https://evil.test/x','other/repo/extra'):
                    self.assertEqual(client.get(path,params={'username':'test','repo':repo}).status_code,422)
            fetch.assert_not_called()
