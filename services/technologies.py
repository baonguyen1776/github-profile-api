from __future__ import annotations

import asyncio
import base64
import json
import re
import time
import tomllib
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import quote

import httpx

from services.github import TIMEOUT, GitHubClientError, _headers
from services.languages import CACHE_LIMIT, CACHE_TTL, MAX_PARALLEL_REQUESTS, LanguageReport, _get_json


# Exact dependency names only: @types/react does not establish React usage.
JS_PACKAGES = {
    'react': 'React', 'react-native': 'React Native', 'expo': 'Expo',
    'next': 'Next.js', 'vue': 'Vue.js', 'svelte': 'Svelte', 'express': 'Express.js',
    'bootstrap': 'Bootstrap', 'handlebars': 'Handlebars', 'vite': 'Vite',
    'three': 'Three.js', 'gsap': 'GSAP', 'tailwindcss': 'Tailwind CSS',
}
PY_PACKAGES = {
    'numpy': 'NumPy', 'opencv-python': 'OpenCV', 'opencv-contrib-python': 'OpenCV',
    'opencv-python-headless': 'OpenCV', 'mediapipe': 'MediaPipe', 'jax': 'JAX',
    'matplotlib': 'Matplotlib', 'scipy': 'SciPy', 'pandas': 'Pandas',
    'scikit-learn': 'scikit-learn', 'tensorflow': 'TensorFlow', 'torch': 'PyTorch',
    'jupyter': 'Jupyter', 'fastapi': 'FastAPI', 'flask': 'Flask', 'django': 'Django',
}
GROUP_ORDER = ('Web Development', 'Mobile Development', 'Python / Data / Computer Vision', 'Systems / Build Tools', 'Other Languages')
GROUP_MEMBERS = {
    'Web Development': {'TypeScript', 'JavaScript', 'HTML', 'CSS', *JS_PACKAGES.values(), 'FastAPI', 'Flask', 'Django'},
    'Mobile Development': {'React Native', 'Expo', 'Swift', 'Kotlin', 'Dart'},
    'Python / Data / Computer Vision': {'Python', 'Jupyter Notebook', *PY_PACKAGES.values()},
    'Systems / Build Tools': {'C', 'C++', 'C#', 'CMake', 'Rust', 'Go', 'Java', 'Shell'},
}
EDITORS = {'Visual Studio Code': 'vscode', 'IntelliJ IDEA': 'intellij', 'PyCharm': 'pycharm'}
EXCLUDED_DIRS = {'node_modules', 'vendor', '.venv', 'venv', 'build', 'dist', 'references', 'third_party', 'third-party', 'external', 'site-packages', '.git'}
MAX_MANIFEST_BYTES = 256_000
MAX_MANIFESTS_PER_REPO = 16


@dataclass(frozen=True)
class TechnologyReport:
    evidence: dict[str, list[dict[str, str]]]
    manifests_scanned: int = 0
    incomplete: bool = False


_CACHE: OrderedDict[tuple, tuple[float, TechnologyReport]] = OrderedDict()


def is_manifest(path: str) -> bool:
    parts = PurePosixPath(path).parts
    if any(part.casefold() in EXCLUDED_DIRS for part in parts[:-1]):
        return False
    return bool(parts and (parts[-1] in {'package.json', 'pyproject.toml'} or re.fullmatch(r'requirements(?:[-.][\w-]+)?\.txt', parts[-1])))


def detect_dependencies(path: str, content: str) -> set[str]:
    """Read declarations, never execute repository code or dependency installers."""
    filename = PurePosixPath(path).name
    if filename == 'package.json':
        payload = json.loads(content)
        dependencies = set()
        for section in ('dependencies', 'devDependencies', 'optionalDependencies'):
            dependencies.update(payload.get(section, {}))
        detected = {JS_PACKAGES[name] for name in dependencies if name in JS_PACKAGES}
        # React is also required by native apps; give it a Web badge only for web manifests.
        if 'react-native' in dependencies and 'react-dom' not in dependencies:
            detected.discard('React')
        return detected
    if filename == 'pyproject.toml':
        payload = tomllib.loads(content)
        project = payload.get('project', {})
        declarations = list(project.get('dependencies', []))
        for group in project.get('optional-dependencies', {}).values():
            declarations.extend(group)
        declarations.extend(payload.get('tool', {}).get('poetry', {}).get('dependencies', {}).keys())
    else:
        declarations = content.splitlines()
    found = set()
    for declaration in declarations:
        match = re.match(r'^\s*([A-Za-z0-9][A-Za-z0-9_.-]*)', declaration)
        if match:
            name = re.sub(r'[-_.]+', '-', match[1]).lower()
            if name in PY_PACKAGES:
                found.add(PY_PACKAGES[name])
    return found


async def fetch_technology_report(report: LanguageReport) -> TechnologyReport:
    key = (report.username.casefold(), report.repositories)
    cached = _CACHE.get(key)
    if cached and time.monotonic() - cached[0] < CACHE_TTL:
        _CACHE.move_to_end(key)
        return cached[1]
    if not report.repositories:
        return TechnologyReport({})
    semaphore = asyncio.Semaphore(MAX_PARALLEL_REQUESTS)
    evidence: dict[str, list[dict[str, str]]] = {}
    scanned = 0
    incomplete = False
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, headers=_headers(), follow_redirects=True) as client:
            async def get(path: str, params=None):
                async with semaphore:
                    return await _get_json(client, path, params)

            async def scan_repository(repo):
                nonlocal scanned, incomplete
                name, branch = repo
                prefix = f'/repos/{quote(report.username, safe="")}/{quote(name, safe="")}'
                tree = await get(prefix + '/git/trees/' + quote(branch, safe=''), {'recursive': '1'})
                if tree.get('truncated'):
                    incomplete = True
                candidates = [item for item in tree['tree'] if item.get('type') == 'blob' and item.get('mode') != '120000' and is_manifest(item['path'])]
                candidates.sort(key=lambda item: (item['path'].count('/'), item['path']))
                eligible = [item for item in candidates if item.get('size', MAX_MANIFEST_BYTES + 1) <= MAX_MANIFEST_BYTES]
                if len(eligible) != len(candidates) or len(eligible) > MAX_MANIFESTS_PER_REPO:
                    incomplete = True

                async def scan_manifest(item):
                    nonlocal scanned, incomplete
                    blob = await get(prefix + '/git/blobs/' + quote(item['sha'], safe=''))
                    if blob.get('encoding') != 'base64':
                        raise ValueError('Invalid GitHub blob encoding')
                    content = base64.b64decode(blob['content']).decode('utf-8-sig')
                    try:
                        names = detect_dependencies(item['path'], content)
                    except (ValueError, TypeError, AttributeError):
                        incomplete = True
                        return
                    scanned += 1
                    source = {
                        'repository': f'{report.username}/{name}', 'path': item['path'],
                        'blob_sha': item['sha'],
                        'url': f'https://github.com/{quote(report.username)}/{quote(name)}/blob/{quote(branch, safe="")}/{quote(item["path"], safe="/")}',
                    }
                    for technology in sorted(names):
                        evidence.setdefault(technology, []).append(source)

                results = await asyncio.gather(*(scan_manifest(item) for item in eligible[:MAX_MANIFESTS_PER_REPO]), return_exceptions=True)
                for result in results:
                    if isinstance(result, BaseException):
                        raise result

            results = await asyncio.gather(*(scan_repository(repo) for repo in report.repositories), return_exceptions=True)
            for result in results:
                if isinstance(result, BaseException):
                    raise result
    except GitHubClientError:
        raise
    except (httpx.HTTPError, ValueError, TypeError, AttributeError, KeyError) as exc:
        raise GitHubClientError('GitHub technology data is temporarily unavailable') from exc
    for sources in evidence.values():
        sources.sort(key=lambda source: (source['repository'], source['path']))
    result = TechnologyReport(evidence, scanned, incomplete)
    _CACHE[key] = (time.monotonic(), result)
    _CACHE.move_to_end(key)
    while len(_CACHE) > CACHE_LIMIT:
        _CACHE.popitem(last=False)
    return result


def select_technologies(report: TechnologyReport, requested: list[str]) -> list[str]:
    available = {name.casefold(): name for name in report.evidence}
    if not requested:
        return sorted(report.evidence)
    return list(dict.fromkeys(available[name.strip().casefold()] for name in requested if name.strip().casefold() in available))


def grouped_names(languages: list[str], technologies: list[str]) -> list[tuple[str, list[str]]]:
    groups: dict[str, list[str]] = {title: [] for title in GROUP_ORDER}
    for name in dict.fromkeys([*languages, *technologies]):
        # Mobile takes precedence over web, Python APIs take web precedence over data.
        title = next((group for group in ('Mobile Development', 'Web Development', 'Python / Data / Computer Vision', 'Systems / Build Tools') if name in GROUP_MEMBERS[group]), 'Other Languages')
        groups[title].append(name)
    return [(title, names) for title, names in groups.items() if names]
