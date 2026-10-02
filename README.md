# github-profile-api

Animated SVG cards for a GitHub profile. The header card is implemented; Tech Stack and Contributions are the next cards to build.

## Structure

```text
github-profile-api/
├── app.py                  # FastAPI entry point and /health
├── config.py               # Load profile.json from the project root
├── routes/
│   ├── __init__.py
│   └── header.py           # /api/header, validation and cache headers
├── services/
│   ├── __init__.py
│   └── github.py           # Fetch GitHub profile and avatar
├── renderers/
│   ├── __init__.py
│   ├── shared.py           # Colors, fonts, SVG text, keyframes, error card
│   ├── ascii.py            # Dense name sampling from a bundled font
│   └── header.py           # Header layout and ASCII avatar
├── assets/
│   ├── icons/              # Reserved for technology icons
│   └── fonts/              # NotoSans-Bold.ttf and its OFL license
├── tests/
│   └── test_ascii_name.py   # Density, Vietnamese accents, layout and SVG checks
├── profile.json
├── requirements.txt
├── .python-version
└── .gitignore
```

Requests flow through `routes` → `services` → `renderers`. `app.py` registers the routers. Add `stack.py` and `contributions.py` to `routes/` and `renderers/` when those cards are implemented; register each new router in `app.py`.

The SVG reveal repeats automatically every six seconds: intro, name, portrait, details, footer, then a pause and fade before restarting. It uses SVG CSS animations, so no browser refresh or JavaScript is required. Reduced-motion preferences display a static card.

The header uses bundled Noto Sans Bold to sample letter shapes into a dense ASCII grid. The SVG contains the sampled characters rather than a browser-clipped repeating pattern. Technology icons are reserved for the future stack card. Include `assets/fonts/NotoSans-Bold.ttf` when deploying; its license is in `assets/fonts/OFL.txt`.

## Available endpoints

- `GET /health`
- `GET /api/header?username=baonguyen1776&theme=light`
- `GET /api/header?username=baonguyen1776&theme=dark`

The header pulls the GitHub display name, username, avatar, location, public repository count, and follower count automatically. Edit `profile.json` for the stack, tagline, and visual-language text. Tech Stack and Contributions endpoints are not available yet.

## Local development

Use Python 3.12, as specified in `.python-version`:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn app:app --reload
```

If `.venv` is already set up, start with `source .venv/bin/activate`.

Open `http://127.0.0.1:8000/api/header?username=baonguyen1776&theme=light`. API documentation is available at `http://127.0.0.1:8000/docs`. Press Ctrl+C to stop the server.

Select `.venv/bin/python` as the Python interpreter in your editor.

`GITHUB_TOKEN` is optional locally. Set it in the server environment to authenticate GitHub API requests; never put it in `profile.json` or commit it.

## Vercel

The FastAPI entry point remains `app:app` in `app.py`. When deploying, import this repository into Vercel and store `GITHUB_TOKEN`, if used, as a Vercel environment variable.

## Local checks

```bash
python -m unittest discover -s tests -v
```

These checks do not call GitHub.
