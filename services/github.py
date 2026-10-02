from __future__ import annotations

import os
from dataclasses import dataclass

import httpx


API_BASE = "https://api.github.com"
TIMEOUT = httpx.Timeout(8.0, connect=5.0)


@dataclass(frozen=True)
class GitHubProfile:
    login: str
    name: str
    avatar_url: str
    location: str
    public_repos: int
    followers: int


class GitHubClientError(RuntimeError):
    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


def _headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "github-profile-svg-api",
    }
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def fetch_profile(username: str) -> tuple[GitHubProfile, bytes]:
    try:
        with httpx.Client(timeout=TIMEOUT, follow_redirects=True, headers=_headers()) as client:
            response = client.get(f"{API_BASE}/users/{username}")
            if response.status_code == 404:
                raise GitHubClientError("GitHub profile not found", status_code=404)
            if response.status_code == 403 and response.headers.get("x-ratelimit-remaining") == "0":
                raise GitHubClientError("GitHub API rate limit reached", status_code=429)
            response.raise_for_status()
            payload = response.json()

            avatar_url = payload.get("avatar_url") or ""
            if not avatar_url:
                raise GitHubClientError("GitHub profile has no avatar")

            avatar_response = client.get(avatar_url)
            avatar_response.raise_for_status()

    except GitHubClientError:
        raise
    except (httpx.HTTPError, ValueError) as exc:
        raise GitHubClientError("GitHub data is temporarily unavailable") from exc

    profile = GitHubProfile(
        login=payload.get("login") or username,
        name=(payload.get("name") or payload.get("login") or username).strip(),
        avatar_url=avatar_url,
        location=(payload.get("location") or "Somewhere on Earth").strip(),
        public_repos=int(payload.get("public_repos") or 0),
        followers=int(payload.get("followers") or 0),
    )
    return profile, avatar_response.content
