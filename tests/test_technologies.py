from __future__ import annotations

import base64
import json
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient

from app import app
from renderers.stack import render_stack_svg
from services.github import GitHubClientError
from services.languages import LanguageReport, select_language_rows
from services.technologies import TechnologyReport, detect_dependencies, fetch_technology_report, is_manifest
from services import technologies as service


class DependencyDetectionTests(unittest.TestCase):
    def test_exact_package_keys_and_native_react_context(self):
        content = json.dumps({'dependencies': {'react': '1', 'react-native': '2', 'expo': '3'}, 'devDependencies': {'@types/react': '4', 'vite-plugin-react': '5'}})
        self.assertEqual(detect_dependencies('package.json', content), {'React Native', 'Expo'})
        self.assertEqual(detect_dependencies('web/package.json', '{"devDependencies":{"vite":"1"},"dependencies":{"react":"2"}}'), {'React', 'Vite'})
        self.assertEqual(detect_dependencies('package.json', '{"devDependencies":{"@types/react":"1"}}'), set())

    def test_python_declarations_do_not_match_comments_or_similar_names(self):
        content = '# tensorflow is not installed\nNumPy>=2\nopencv_contrib_python==4\nscikit-learn[extra]>=1\nnot-torch==1\n-r requirements-other.txt'
        self.assertEqual(detect_dependencies('requirements.txt', content), {'NumPy', 'OpenCV', 'scikit-learn'})
        self.assertEqual(detect_dependencies('pyproject.toml', '[project]\ndependencies=["fastapi>=1"]\n[project.optional-dependencies]\nvision=["opencv-python>=4"]\n[tool.poetry.dependencies]\npandas="2"'), {'FastAPI', 'OpenCV', 'Pandas'})

    def test_generated_vendor_and_reference_paths_are_excluded(self):
        for path in ('node_modules/react/package.json', 'external/foo/requirements.txt', 'references/design/package.json', '.venv/pyproject.toml', 'package-lock.json', 'notes.txt'):
            self.assertFalse(is_manifest(path), path)
        for path in ('package.json', 'apps/web/package.json', 'backend/pyproject.toml', 'requirements-dev.txt'):
            self.assertTrue(is_manifest(path), path)


class TechnologyFetchTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        service._CACHE.clear()

    async def asyncTearDown(self):
        service._CACHE.clear()

    async def test_nested_manifest_sources_cache_and_skipped_files(self):
        calls = []
        report = LanguageReport('Test', 1, {'TypeScript': 100}, (('app', 'feature/ui'),))
        def handle(request):
            calls.append(request.url.path)
            if '/git/trees/' in request.url.path:
                self.assertEqual(request.url.params['recursive'], '1')
                return httpx.Response(200, json={'sha': 'tree', 'truncated': True, 'tree': [
                    {'path': 'apps/mobile/package.json', 'type': 'blob', 'mode': '100644', 'sha': 'native', 'size': 80},
                    {'path': 'node_modules/react/package.json', 'type': 'blob', 'sha': 'vendor', 'size': 30},
                    {'path': 'requirements.txt', 'type': 'blob', 'sha': 'large', 'size': 999999},
                ]})
            self.assertTrue(request.url.path.endswith('/git/blobs/native'))
            content = '{"dependencies":{"react-native":"1","expo":"2"}}'
            return httpx.Response(200, json={'encoding': 'base64', 'content': base64.b64encode(content.encode()).decode()})
        client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        with patch('services.technologies.httpx.AsyncClient', return_value=client) as constructor:
            found = await fetch_technology_report(report)
            cached = await fetch_technology_report(report)
        constructor.assert_called_once()
        self.assertIs(found, cached)
        self.assertEqual(set(found.evidence), {'React Native', 'Expo'})
        self.assertEqual(found.manifests_scanned, 1)
        self.assertTrue(found.incomplete)
        source = found.evidence['Expo'][0]
        self.assertEqual(source['path'], 'apps/mobile/package.json')
        self.assertEqual(source['blob_sha'], 'native')
        self.assertIn('/blob/feature%2Fui/apps/mobile/package.json', source['url'])
        self.assertEqual(len(calls), 2)

    async def test_failure_is_not_cached_as_verified_report(self):
        report = LanguageReport('test', 1, {'Python': 1}, (('one', 'main'),))
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(403, headers={'x-ratelimit-remaining': '0'})))
        with patch('services.technologies.httpx.AsyncClient', return_value=client):
            with self.assertRaises(GitHubClientError) as raised:
                await fetch_technology_report(report)
        self.assertEqual(raised.exception.status_code, 429)
        self.assertFalse(service._CACHE)


class GroupedBadgeTests(unittest.TestCase):
    def setUp(self):
        self.report = LanguageReport('test', 2, {'TypeScript': 60, 'Python': 30, 'C++': 10})
        self.rows = select_language_rows(self.report, [])
        self.tech = TechnologyReport({'React': [{'repository': 'test/web', 'path': 'package.json', 'url': 'https://github.com/test/web/blob/main/package.json'}], 'Expo': []}, 1)
        self.ns = {'s': 'http://www.w3.org/2000/svg'}

    def test_categories_and_selection_filter_against_verified_choices(self):
        svg = render_stack_svg(report=self.report, rows=self.rows, theme='light', requested_technologies=['react', 'TensorFlow'], editors=['PyCharm'], technologies=self.tech)
        tree = ET.fromstring(svg)
        names = [node.attrib['data-technology'] for node in tree.findall('.//s:g[@data-technology]', self.ns)]
        self.assertEqual(names, ['React'])
        categories = [node.attrib['data-category'] for node in tree.findall('.//s:g[@data-category]', self.ns)]
        self.assertIn('Web Development', categories)
        self.assertIn('Systems / Build Tools', categories)
        self.assertIn('IDEs / Text Editors — Your Selection', categories)
        self.assertIn('test/web/package.json', svg)
        self.assertIn('chosen by you', svg)
        self.assertNotIn('data-technology="TensorFlow"', svg)
        self.assertIn('TypeScript: 60.0%', svg)

    def test_wrapped_badges_stay_inside_card_and_above_chart(self):
        data = {f'Long language number {i}': 10 for i in range(17)}
        report = LanguageReport('test', 1, data)
        tree = ET.fromstring(render_stack_svg(report=report, rows=select_language_rows(report, []), theme='dark'))
        height = float(tree.attrib['height'])
        graph_y = float(next(node for node in tree.findall('s:rect', self.ns) if node.attrib.get('x') == '32').attrib['y'])
        for group in tree.findall('.//s:g[@data-language]', self.ns):
            rect = group.find('s:rect', self.ns)
            self.assertLessEqual(float(rect.attrib['x']) + float(rect.attrib['width']), 1052)
            self.assertLess(float(rect.attrib['y']) + 34, graph_y)
        for group in tree.findall('.//s:g[@data-usage]', self.ns):
            self.assertLess(float(group.find('s:circle', self.ns).attrib['cy']), height - 30)

    def test_new_api_exposes_evidence_and_stack_uses_it(self):
        client = TestClient(app)
        with patch('routes.stack.fetch_language_report', AsyncMock(return_value=self.report)), patch('routes.stack.fetch_technology_report', AsyncMock(return_value=self.tech)):
            choices = client.get('/api/technologies?username=test')
            stack = client.get('/api/stack?username=test&theme=light')
        self.assertEqual(choices.status_code, 200)
        self.assertEqual(choices.json()['technologies'][1]['sources'][0]['path'], 'package.json')
        self.assertEqual(stack.status_code, 200)
        self.assertIn('data-technology="React"', stack.text)
        self.assertIn('data-category="Mobile Development"', stack.text)


if __name__ == '__main__':
    unittest.main()
