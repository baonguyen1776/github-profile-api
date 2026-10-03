from __future__ import annotations

import json
import unittest
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from datetime import date, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient

from app import app
from services import contributions as service
from services.contributions import ContributionDay, fetch_contributions, make_report, parse_public_calendar
from services.github import GitHubClientError
from renderers.contributions import grid_geometry, render_contributions_svg, snake_route


AS_OF = date(2026, 10, 3)


def days_with_counts(
    counts: Mapping[date, int] | None = None,
    as_of: date = AS_OF,
) -> list[ContributionDay]:
    counts = counts or {}
    start = as_of - timedelta(days=364)
    return [ContributionDay(day, counts.get(day, 0), 1 if counts.get(day, 0) else 0) for day in (start + timedelta(days=i) for i in range(365))]


def calendar_html(year: int, counts: Mapping[date, int] | None = None) -> str:
    counts = counts or {}
    parts = []
    day = date(year, 1, 1)
    while day.year == year:
        count = counts.get(day, 0)
        parts.append(f'<td id="day-{day}" data-date="{day}" data-level="{1 if count else 0}"></td>')
        text = f'{count:,} contributions' if count else 'No contributions'
        parts.append(f'<tool-tip for="day-{day}">{text} on some date.</tool-tip>')
        day += timedelta(days=1)
    return ''.join(parts)


class ContributionStatisticsTests(unittest.TestCase):
    def test_current_streak_keeps_yesterday_open_and_breaks_on_a_gap(self) -> None:
        counts = {AS_OF-timedelta(days=i): 3 for i in (1,2,3,6,7)}
        report = make_report('test', days_with_counts(counts), AS_OF, 'github-public-calendar')
        self.assertEqual(report.current_streak, 3)
        self.assertEqual(report.longest_streak, 3)
        self.assertEqual(report.active_days, 5)
        self.assertEqual(report.total, 15)
        counts[AS_OF] = 2
        self.assertEqual(make_report('test', days_with_counts(counts), AS_OF, 'github-public-calendar').current_streak, 4)
        counts.pop(AS_OF)
        counts.pop(AS_OF-timedelta(days=1))
        self.assertEqual(make_report('test', days_with_counts(counts), AS_OF, 'github-public-calendar').current_streak, 0)

    def test_longest_streak_can_cross_december_january_and_leap_day(self) -> None:
        for end in (date(2026, 2, 1), date(2024, 3, 3)):
            anchor = date(2025,12,30) if end.year == 2026 else date(2024,2,28)
            counts = {anchor+timedelta(days=i): 1 for i in range(4)}
            report = make_report('test', list(reversed(days_with_counts(counts, end))), end, 'github-public-calendar')
            self.assertEqual(report.longest_streak, 4)
            self.assertEqual(len(report.days), 365)
            self.assertEqual(report.days[-1].date, end)

    def test_missing_and_conflicting_dates_are_never_filled_with_fake_zeros(self) -> None:
        days = days_with_counts()
        with self.assertRaises(ValueError):
            make_report('test', days[:-1], AS_OF, 'github-public-calendar')
        with self.assertRaises(ValueError):
            make_report('test', days + [ContributionDay(days[0].date, 2, 1)], AS_OF, 'github-public-calendar')
        for count, level in ((-1,0), (True,1), (1,0), (0,4), (1,5)):
            with self.assertRaises(ValueError):
                make_report('test', [ContributionDay(days[0].date,count,level), *days[1:]], AS_OF, 'github-public-calendar')

    def test_zero_calendar_has_zero_metrics(self) -> None:
        report = make_report('test', days_with_counts(), AS_OF, 'github-public-calendar')
        self.assertEqual((report.total, report.current_streak, report.longest_streak, report.active_days), (0,0,0,0))


class CalendarParserTests(unittest.TestCase):
    def test_html_cells_and_tooltips_are_joined_by_id_with_nested_text(self) -> None:
        html = '<td id="b" data-date="2026-10-03" data-level="4"></td><td id="a" data-date="2026-10-02" data-level="0"></td><tool-tip for="a">No contributions on October 2nd.</tool-tip><tool-tip for="b"><b>1,234</b> contributions on October 3rd.</tool-tip>'
        parsed = {day.date:day.count for day in parse_public_calendar(html)}
        self.assertEqual(parsed, {date(2026,10,2):0, AS_OF:1234})

    def test_missing_count_does_not_estimate_count_from_level(self) -> None:
        with self.assertRaises(ValueError):
            parse_public_calendar('<td id="a" data-date="2026-10-02" data-level="3"></td>')


class ContributionFetchTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        service._CACHE.clear()

    async def asyncTearDown(self) -> None:
        service._CACHE.clear()

    async def test_public_years_are_merged_filtered_and_cached(self) -> None:
        paths = []
        counts = {date(2025,12,31):3, date(2026,1,1):5, AS_OF+timedelta(days=1):50}
        def handle(request: httpx.Request) -> httpx.Response:
            self.assertNotIn('authorization', request.headers)
            paths.append(str(request.url))
            year = int(request.url.params['from'][:4])
            return httpx.Response(200, text=calendar_html(year, counts))
        client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        with patch.dict('os.environ', {}, clear=True), patch('services.contributions.httpx.AsyncClient', return_value=client) as constructor:
            report = await fetch_contributions('Test', as_of=AS_OF)
            cached = await fetch_contributions('TEST', as_of=AS_OF)
        self.assertIs(cached, report)
        constructor.assert_called_once()
        self.assertEqual(len(paths), 2)
        self.assertEqual(report.total, 8)
        self.assertEqual(len(report.days), 365)
        self.assertEqual(report.source, 'github-public-calendar')

    async def test_graphql_uses_variables_and_rejects_partial_errors(self) -> None:
        rows = days_with_counts({AS_OF:5})
        payload: dict[str, Any] = {'data': {'user': {'login': 'Test', 'contributionsCollection': {'contributionCalendar': {'weeks': [{'contributionDays': [{'date':day.date.isoformat(), 'contributionCount':day.count, 'contributionLevel':'FIRST_QUARTILE' if day.count else 'NONE'} for day in rows]}]}}}}}
        def handle(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            self.assertEqual(request.method, 'POST')
            self.assertEqual(body['variables']['login'], 'test')
            self.assertEqual(request.headers['authorization'], 'Bearer test-fixture')
            self.assertNotIn('mutation', body['query'])
            return httpx.Response(200, json=payload)
        client_type = httpx.AsyncClient
        def factory(**kwargs: Any) -> httpx.AsyncClient:
            return client_type(transport=httpx.MockTransport(handle), **kwargs)
        with patch.dict('os.environ', {'GITHUB_TOKEN':'test-fixture'}), patch('services.contributions.httpx.AsyncClient', side_effect=factory):
            report = await fetch_contributions('test', as_of=AS_OF)
        self.assertEqual(report.total, 5)
        self.assertEqual(report.source, 'github-graphql')
        service._CACHE.clear()
        payload['errors'] = [{'type':'RATE_LIMITED','message':'Rate limit'}]
        with patch.dict('os.environ', {'GITHUB_TOKEN':'test-fixture'}), patch('services.contributions.httpx.AsyncClient', side_effect=factory):
            with self.assertRaises(GitHubClientError) as error:
                await fetch_contributions('test', as_of=AS_OF)
        self.assertIsNotNone(error.exception)
        assert error.exception is not None
        self.assertEqual(error.exception.status_code, 429)
        self.assertFalse(service._CACHE)

    async def test_html_failure_and_status_errors_are_not_cached(self) -> None:
        for status, text, expected in ((404,'',404), (429,'',429), (500,'',502), (200,'challenge page',502)):
            def handle_status(_request: httpx.Request, current_status: int = status, current_text: str = text) -> httpx.Response:
                return httpx.Response(current_status, text=current_text)

            client = httpx.AsyncClient(transport=httpx.MockTransport(handle_status))
            with patch.dict('os.environ', {}, clear=True), patch('services.contributions.httpx.AsyncClient', return_value=client):
                with self.assertRaises(GitHubClientError) as error:
                    await fetch_contributions('test', as_of=AS_OF)
            self.assertIsNotNone(error.exception)
            assert error.exception is not None
            self.assertEqual(error.exception.status_code, expected)
            self.assertFalse(service._CACHE)


class ContributionSvgTests(unittest.TestCase):
    def setUp(self) -> None:
        self.report = make_report('test', days_with_counts({AS_OF:5, AS_OF-timedelta(days=1):2}), AS_OF, 'github-public-calendar')
        self.ns = {'s':'http://www.w3.org/2000/svg'}

    def test_snake_route_is_closed_adjacent_and_has_no_self_intersections(self) -> None:
        for columns in (1,2,52,53,54):
            route = snake_route(columns)
            self.assertEqual(route[0], route[-1])
            self.assertEqual(len(route)-1, len(set(route[:-1])))
            self.assertTrue(all(abs(a[0]-b[0])+abs(a[1]-b[1])==1 for a,b in zip(route,route[1:])))
            self.assertTrue({(col,row) for col in range(columns) for row in range(7)}.issubset(set(route)))

    def test_date_alignment_accessibility_no_scripts_and_both_themes(self) -> None:
        _columns, _pitch, positions = grid_geometry(self.report)
        for day in self.report.days:
            self.assertEqual(positions[day.date][1], (day.date.weekday()+1)%7)
        for theme in ('light','dark'):
            svg = render_contributions_svg(report=self.report, theme=theme)
            tree = ET.fromstring(svg)
            cells = tree.findall('.//s:rect[@data-date]',self.ns)
            self.assertEqual(len(cells),365)
            self.assertEqual(sum(int(node.attrib['data-count']) for node in cells),7)
            self.assertEqual(len(tree.findall('.//s:g[@data-segment]',self.ns)),7)
            self.assertIn('prefers-reduced-motion:no-preference',svg)
            self.assertIn('18s linear',svg)
            description = tree.find('s:desc',self.ns)
            self.assertIsNotNone(description)
            assert description is not None
            self.assertIn('current streak 2 days', description.text or '')
            self.assertFalse(tree.findall('.//s:script',self.ns))
            for node in cells:
                self.assertGreaterEqual(float(node.attrib['x']),100)
                self.assertLess(float(node.attrib['x'])+float(node.attrib['width']),1052)
                self.assertLess(float(node.attrib['y'])+float(node.attrib['height']),411)

    def test_snake_loop_is_continuous_shared_and_has_no_cell_delay(self) -> None:
        for seconds in (12,18,120):
            svg = render_contributions_svg(report=self.report, theme='dark', seconds=seconds)
            tree = ET.fromstring(svg)
            style = tree.find('s:style',self.ns)
            self.assertIsNotNone(style)
            assert style is not None
            css = style.text or ''
            self.assertEqual(css.count('@keyframes snake-travel'),1)
            self.assertNotIn('@keyframes snake-0',css)
            self.assertNotIn('cell-return',css)
            self.assertNotIn('class="cell-',svg)
            self.assertIn(f'animation:snake-travel {seconds}s linear',css)
            self.assertIn('0.00000%{transform:translate(',css)
            self.assertIn('100.00000%{transform:translate(',css)
            self.assertNotIn('0%,5%',css)
            self.assertNotIn('83.00000%',css)
            self.assertLess(css.count('@keyframes'),4)

    def test_static_mode_has_no_animation_keyframes(self) -> None:
        svg = render_contributions_svg(report=self.report, theme='light', animate=False)
        self.assertNotIn('@keyframes',svg)
        self.assertIn('STATIC CALENDAR',svg)


class ContributionRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.report = make_report('test',days_with_counts({AS_OF:3}),AS_OF,'github-public-calendar')

    def test_svg_and_json_share_real_counts(self) -> None:
        with patch('routes.contributions.fetch_contributions',AsyncMock(return_value=self.report)):
            svg = self.client.get('/api/contributions?username=test&animate=false&theme=light')
            data = self.client.get('/api/contribution-data?username=test')
        self.assertEqual(svg.status_code,200)
        self.assertTrue(svg.headers['content-type'].startswith('image/svg+xml'))
        self.assertIn('s-maxage=3600',svg.headers['vercel-cdn-cache-control'])
        self.assertEqual(data.json()['total_contributions'],3)
        self.assertEqual(len(data.json()['days']),365)
        self.assertEqual(data.json()['current_streak'],1)
        self.assertNotIn('@keyframes',svg.text)

    def test_invalid_inputs_do_not_call_github(self) -> None:
        with patch('routes.contributions.fetch_contributions',AsyncMock()) as fetch:
            for url in ('/api/contributions', '/api/contributions?username=-invalid', '/api/contributions?username=test&theme=invalid', '/api/contribution-data?username=bad/name'):
                self.assertEqual(self.client.get(url).status_code,422)
            fetch.assert_not_called()

    def test_upstream_failure_and_bad_config_are_uncached_error_cards(self) -> None:
        for status in (404,429,502):
            with patch('routes.contributions.fetch_contributions',AsyncMock(side_effect=GitHubClientError('Unavailable',status))):
                response = self.client.get('/api/contributions?username=test')
            self.assertEqual(response.status_code,status)
            self.assertEqual(response.headers['cache-control'],'no-store')
            ET.fromstring(response.content)
        with patch('routes.contributions.load_profile_config',return_value={'contribution_animation_seconds':0}), patch('routes.contributions.fetch_contributions',AsyncMock()) as fetch:
            self.assertEqual(self.client.get('/api/contributions?username=test').status_code,502)
            fetch.assert_not_called()


if __name__ == '__main__':
    unittest.main()
