from __future__ import annotations

import time
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient

from app import app
from renderers.stack import render_stack_svg
from services.github import GitHubClientError
from services.languages import LanguageReport, all_language_rows, fetch_language_report, select_language_rows
from services import languages as service


class LanguageSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.report = LanguageReport("test", 3, {"TypeScript": 3400, "C++": 2900, "Python": 2100, "HTML": 600, "CSS": 1000})

    def test_selected_languages_match_github_and_preserve_order(self) -> None:
        rows = select_language_rows(self.report, ["python", "Missing", " TypeScript ", "PYTHON"])
        self.assertEqual([row.name for row in rows], ["Python", "TypeScript", "Other"])
        self.assertEqual([row.code_bytes for row in rows], [2100, 3400, 4500])
        self.assertEqual([row.percentage for row in rows], [21.0, 34.0, 45.0])

    def test_other_preserves_the_full_code_denominator(self) -> None:
        rows = select_language_rows(self.report, ["C++"])
        self.assertEqual([(row.name, row.percentage) for row in rows], [("C++", 29.0), ("Other", 71.0)])

    def test_rounding_sums_to_one_hundred(self) -> None:
        report = LanguageReport("test", 3, {"A": 1, "B": 1, "C": 1})
        self.assertEqual(sum(row.tenths for row in all_language_rows(report)), 1000)
        self.assertEqual(sum(row.tenths for row in select_language_rows(report, ["A"])), 1000)

    def test_no_selection_shows_every_github_language(self) -> None:
        rows = select_language_rows(self.report, [])
        self.assertEqual(rows[0].name, "TypeScript")
        self.assertEqual({row.name for row in rows}, set(self.report.language_bytes))
        self.assertEqual(sum(row.tenths for row in rows), 1000)

    def test_empty_repositories_have_no_fake_percentages(self) -> None:
        self.assertEqual(select_language_rows(LanguageReport("test", 0, {}), ["Python"]), [])

    def test_unknown_choices_do_not_fabricate_languages(self) -> None:
        rows = select_language_rows(self.report, ["Ruby"])
        self.assertEqual([(row.name, row.percentage) for row in rows], [("Other", 100.0)])


class GitHubLanguageFetchTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        service._CACHE.clear()

    async def asyncTearDown(self) -> None:
        service._CACHE.clear()

    async def test_pagination_fork_filter_and_cache(self) -> None:
        paths = []
        def repo(name, fork=False, private=False):
            return {"name": name, "owner": {"login": "Test"}, "fork": fork, "private": private}
        page_one = [repo("one"), repo("two")] + [repo(f"fork-{i}", fork=True) for i in range(98)]
        page_two = [repo("empty"), repo("private", private=True)]
        def handle(request):
            paths.append(request.url.path)
            if request.url.path == "/users/test":
                return httpx.Response(200, json={"login": "Test"})
            if request.url.path == "/users/Test/repos":
                return httpx.Response(200, json=page_one if request.url.params['page'] == '1' else page_two)
            payload = {
                '/repos/Test/one/languages': {"TypeScript": 300, "Python": 100},
                '/repos/Test/two/languages': {"TypeScript": 100, "C++": 400},
                '/repos/Test/empty/languages': {},
            }
            return httpx.Response(200, json=payload[request.url.path])
        client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        with patch('services.languages.httpx.AsyncClient', return_value=client) as constructor:
            report = await fetch_language_report('test')
            cached = await fetch_language_report('TEST')
        self.assertIs(cached, report)
        constructor.assert_called_once()
        self.assertEqual(report.repositories_scanned, 3)
        self.assertEqual(report.language_bytes, {"TypeScript": 400, "Python": 100, "C++": 400})
        self.assertEqual(report.total_bytes, 900)
        self.assertEqual(paths.count('/users/Test/repos'), 2)
        self.assertFalse(any('fork-' in path or '/private/' in path for path in paths))

    async def test_rate_limit_is_not_cached_as_partial_results(self) -> None:
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(403, headers={'x-ratelimit-remaining': '0'})))
        with patch('services.languages.httpx.AsyncClient', return_value=client):
            with self.assertRaises(GitHubClientError) as raised:
                await fetch_language_report('test')
        self.assertEqual(raised.exception.status_code, 429)
        self.assertNotIn('test', service._CACHE)

    async def test_expired_report_fetches_again(self) -> None:
        service._CACHE['test'] = (time.monotonic() - service.CACHE_TTL - 1, LanguageReport('test', 1, {'Old': 100}))
        def handle(request):
            return httpx.Response(200, json={'login': 'test'} if request.url.path == '/users/test' else [])
        client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        with patch('services.languages.httpx.AsyncClient', return_value=client):
            report = await fetch_language_report('test')
        self.assertEqual(report.language_bytes, {})

    async def test_upstream_failure_returns_no_invented_stats(self) -> None:
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(500)))
        with patch('services.languages.httpx.AsyncClient', return_value=client):
            with self.assertRaises(GitHubClientError) as raised:
                await fetch_language_report('test')
        self.assertEqual(raised.exception.status_code, 502)


class StackSvgTests(unittest.TestCase):
    def setUp(self) -> None:
        self.report = LanguageReport("test", 2, {"TypeScript": 3400, "Python": 6600})

    def test_static_counts_and_one_shot_bars(self) -> None:
        rows = select_language_rows(self.report, ['TypeScript', 'Missing', 'Python'])
        ns = {'svg': 'http://www.w3.org/2000/svg'}
        for theme in ('light', 'dark'):
            with self.subTest(theme=theme):
                svg = render_stack_svg(report=self.report, rows=rows, theme=theme)
                tree = ET.fromstring(svg)
                self.assertEqual([node.attrib['data-usage'] for node in tree.findall(".//svg:g[@data-usage]", ns)], ['TypeScript', 'Python'])
                self.assertFalse(tree.findall('.//svg:image', ns))
                self.assertNotIn('data-technology=', svg)
                self.assertNotIn('data-editor=', svg)
                self.assertNotIn('data-tool=', svg)
                self.assertIn('Language Usage', svg)
                for group, row in zip(tree.findall('.//svg:g[@data-usage]', ns), rows):
                    counters = group.findall('svg:text[@class="final-count"]', ns)
                    self.assertEqual(len(counters), 1)
                    self.assertEqual(counters[0].text, f'{row.percentage:.1f}%')
                self.assertNotIn('count-step', svg)
                self.assertNotIn('infinite', svg)
                self.assertIn('animation:stack-fill 1.3s ease-out 1 both', svg)
                self.assertFalse(tree.findall('.//svg:script', ns))
                self.assertIn('34.0%', svg)
                self.assertIn('prefers-reduced-motion', svg)

    def test_empty_data_and_unknown_language_fallback(self) -> None:
        empty = render_stack_svg(report=LanguageReport('test', 0, {}), rows=[], theme='dark')
        self.assertIn('Add code to a public repository to populate this card.', empty)
        report = LanguageReport('test', 1, {'UnknownLanguage': 100})
        svg = render_stack_svg(report=report, rows=select_language_rows(report, []), theme='light')
        self.assertIn('UnknownLanguage', svg)
        ET.fromstring(svg)

    def test_accessible_description_is_escaped(self) -> None:
        report = LanguageReport('test&demo', 1, {'C++': 100})
        svg = render_stack_svg(report=report, rows=select_language_rows(report, []), theme='dark')
        self.assertIn('@test&amp;demo', svg)
        ET.fromstring(svg)


class StackRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.report = LanguageReport('test', 1, {'TypeScript': 34, 'Python': 66})

    def test_languages_and_stack_use_same_report(self) -> None:
        with patch('routes.stack.fetch_language_report', AsyncMock(return_value=self.report)):
            choices = self.client.get('/api/languages?username=test')
            response = self.client.get('/api/stack?username=test&theme=dark&languages=typescript,Unknown')
        self.assertEqual(choices.status_code, 200)
        self.assertEqual(choices.json()['total_bytes'], 100)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers['content-type'].startswith('image/svg+xml'))
        self.assertIn('s-maxage=3600', response.headers['vercel-cdn-cache-control'])
        self.assertIn('data-usage="TypeScript"', response.text)
        self.assertNotIn('data-usage="Unknown"', response.text)
        self.assertIn('Other: 66.0%', response.text)

    def test_default_rows_match_all_github_languages(self) -> None:
        with patch('routes.stack.fetch_language_report', AsyncMock(return_value=self.report)), patch('config.load_profile_config', side_effect=AssertionError('Stack must not read server profile settings')):
            response = self.client.get('/api/stack?username=test')
        tree = ET.fromstring(response.content)
        ns = {'svg': 'http://www.w3.org/2000/svg'}
        names = {node.attrib['data-usage'] for node in tree.findall('.//svg:g[@data-usage]', ns)}
        self.assertEqual(names, set(self.report.language_bytes))

    def test_encoded_cpp_language_filter(self) -> None:
        report = LanguageReport('test', 1, {'C++': 25, 'Python': 75})
        with patch('routes.stack.fetch_language_report', AsyncMock(return_value=report)):
            response = self.client.get('/api/stack?username=test&languages=C%2B%2B')
        self.assertEqual(response.status_code, 200)
        self.assertIn('data-usage="C++"', response.text)
        self.assertNotIn('data-usage="Python"', response.text)
        self.assertIn('Other: 75.0%', response.text)

    def test_oversized_language_choices_are_rejected_before_fetching(self) -> None:
        with patch('routes.stack.fetch_language_report', AsyncMock()) as fetch:
            response = self.client.get('/api/stack', params={'username': 'test', 'languages': 'x' * 301})
            self.assertEqual(response.status_code, 422)
            fetch.assert_not_called()

    def test_technology_endpoint_has_been_removed(self) -> None:
        self.assertEqual(self.client.get('/api/technologies?username=test').status_code, 404)

    def test_invalid_inputs_do_not_fetch_github(self) -> None:
        with patch('routes.stack.fetch_language_report', AsyncMock()) as fetch:
            for url in ('/api/stack', '/api/stack?username=-bad', '/api/stack?username=test&theme=invalid', '/api/languages?username=bad/name'):
                self.assertEqual(self.client.get(url).status_code, 422)
            fetch.assert_not_called()

    def test_upstream_errors_render_svg_and_are_not_cached(self) -> None:
        for status in (404, 429, 502):
            with patch('routes.stack.fetch_language_report', AsyncMock(side_effect=GitHubClientError('Unavailable', status))):
                response = self.client.get('/api/stack?username=test')
            self.assertEqual(response.status_code, status)
            self.assertEqual(response.headers['cache-control'], 'no-store')
            ET.fromstring(response.content)

    def test_health_remains_available(self) -> None:
        self.assertEqual(self.client.get('/health').json(), {'status': 'ok'})


if __name__ == '__main__':
    unittest.main()
