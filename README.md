# github-profile-api

Animated SVG cards for a GitHub profile. Header, Tech Stack and yearly Contributions cards are implemented. Featured Projects can be added next.

## Structure

```text
github-profile-api/
├── app.py                  # FastAPI entry point and /health
├── config.py               # Load profile.json from the project root
├── routes/
│   ├── __init__.py
│   ├── header.py           # /api/header
│   ├── stack.py            # /api/stack, /api/languages and /api/technologies
│   └── contributions.py    # Yearly SVG/JSON and /preview/contributions
├── services/
│   ├── __init__.py
│   ├── github.py           # Fetch GitHub profile and avatar
│   ├── languages.py        # Paginated repository scan, byte totals and selection
│   ├── technologies.py     # Manifest evidence, grouping and technology selection
│   ├── contribution_overview.py # Contributed repos and activity, GraphQL/public fallback
│   └── contributions.py    # Daily calendar counts, yearly cache and streaks
├── renderers/
│   ├── __init__.py
│   ├── shared.py           # Colors, fonts, SVG text, keyframes, error card
│   ├── ascii.py            # Dense name sampling from a bundled font
│   ├── header.py           # Header layout and ASCII avatar
│   ├── stack.py            # Grouped badges, usage bars and animated counters
│   ├── contribution_profile.py # Compact README calendar, projects and activity axes
│   └── contributions.py    # Shared snake animation and legacy rolling layout
├── assets/
│   ├── icons/              # Bundled Devicon SVGs and license
│   └── fonts/              # NotoSans-Bold.ttf and its OFL license
├── tests/
│   ├── test_ascii_name.py   # ASCII density, accents and layout
│   ├── test_stack.py        # Language data, selection, cache, SVG and API checks
│   ├── test_technologies.py # Dependencies, evidence, groups, wrapping and API
│   ├── test_contributions.py # Calendar integrity, streaks, snake route and API
│   └── test_contribution_years.py # Years, projects, pagination and preview
├── profile.json
├── requirements.txt
├── .python-version
└── .gitignore
```

Requests flow through `routes` → `services` → `renderers`. `app.py` registers the routers. New cards get their own route and renderer; register each new router in `app.py`.

The SVG reveal repeats automatically every six seconds: intro, name, portrait, details, footer, then a pause and fade before restarting. It uses SVG CSS animations, so no browser refresh or JavaScript is required. Reduced-motion preferences display a static card.

The header uses bundled Noto Sans Bold to sample letter shapes into a dense ASCII grid. The SVG contains the sampled characters rather than a browser-clipped repeating pattern. Stack icons are bundled locally from Devicon and embedded into the SVG as data URLs; unsupported languages use a letter badge. Include `assets/fonts/NotoSans-Bold.ttf` when deploying; its license is in `assets/fonts/OFL.txt`.

## Available endpoints

- `GET /health`
- `GET /api/header?username=baonguyen1776&theme=light`
- `GET /api/header?username=baonguyen1776&theme=dark`
- `GET /api/stack?username=baonguyen1776&theme=dark`
- `GET /api/stack?username=baonguyen1776&theme=light`
- `GET /api/languages?username=baonguyen1776`
- `GET /api/technologies?username=baonguyen1776`
- `GET /api/contributions?username=baonguyen1776&theme=dark`
- `GET /api/contributions?username=baonguyen1776&theme=light`
- `GET /api/contributions?username=baonguyen1776&year=2025&theme=dark`
- `GET /api/contribution-data?username=baonguyen1776&year=2026`
- `GET /preview/contributions?username=baonguyen1776&year=2026&theme=dark`

The header pulls the GitHub display name, username, avatar, location, public repository count, and follower count automatically. Edit `profile.json` for the stack, tagline, and visual-language text. Featured Projects endpoints are not available yet.

## Tech Stack data and configuration

`GET /api/languages?username=baonguyen1776` lists the language choices detected on GitHub, with byte totals and percentages. The service paginates through owned public repositories, excludes forks and private repositories, and sums the `/repos/{owner}/{repo}/languages` byte counts. Empty repositories contribute no bytes. Archived public repositories are included.

The top section uses flat badges grouped into Web Development, Mobile Development, Python / Data / Computer Vision, Systems / Build Tools, and Other Languages. Empty groups are omitted. By default it includes every language detected on GitHub. Set `stack_card_languages` to a nonempty list to explicitly select a subset in your chosen order. Names are matched case-insensitively against the detected GitHub languages; missing names are omitted. The bottom bars use the same language selection, followed by **Other** for all unselected language bytes. The denominator includes all detected code, so choosing fewer icons does not inflate their percentages. Displayed percentages are rounded to one decimal and sum to 100.0%.

Edit `profile.json`:

```json
{
  "stack": ["TypeScript", "C++", "Python"],
  "stack_card_languages": [],
  "stack_card_technologies": [],
  "stack_card_editors": [],
  "tagline": "Build. Learn. Share.",
  "visual_language": "Characters become identity.",
  "focus_areas": ["AI / ML", "Automation"]
}
```

`focus_areas` are your own labels. `stack` supplies only the header's technology line. Empty `stack_card_languages` shows all detected languages automatically; badges wrap within their category to fit the card. A nonempty list selects only matching GitHub languages. To preview a different selection without editing config, use:

```text
/api/stack?username=baonguyen1776&theme=dark&languages=TypeScript,C%2B%2B,Python
```

Encode the plus signs in `C++` as `%2B%2B` in URLs. `/docs` handles this automatically.

`GET /api/technologies?username=baonguyen1776` returns selectable technology names and evidence links to their dependency manifests. The service scans `package.json`, `requirements*.txt`, and `pyproject.toml` in the same owned public non-fork repositories, including nested app directories. It matches exact known dependency names in declarations. For example, `react-native` establishes a React Native badge; `@types/react` alone does not establish React. A native-only React manifest does not add a Web React badge.

Empty `stack_card_technologies` displays all recognized declared technologies. To select only verified choices, use a nonempty list such as `["React", "Vite", "React Native", "Expo", "OpenCV"]`. Unknown or undetected choices are omitted. These badges do not change language percentages. Declarations establish a project dependency, not proficiency or confirmed runtime use. The catalog currently supports common JavaScript and Python dependencies; other ecosystems and unlisted packages are not inferred.

Editors are an explicit personal selection because language statistics and dependency manifests cannot establish your preferred IDE. For example, set `stack_card_editors` to `["Visual Studio Code", "PyCharm"]`. Supported editor names are Visual Studio Code, IntelliJ IDEA, and PyCharm. An empty list hides the editor section; chosen editors are labeled separately from GitHub detection.

The dependency scan excludes vendor, dependency, build, environment, and reference directories. It reads at most 16 recognized manifests per repository, up to 256 KB each, and never executes repository files. The JSON endpoint exposes `incomplete` if a GitHub tree is truncated, a manifest is oversized or malformed, or the manifest limit is reached; the SVG also shows a short notice. Rate-limit and network failures return an error and are not cached as a successful scan. Manifest reports are cached for one hour. A cold stack request now also needs a tree request per nonempty repository plus one blob request per eligible manifest; set `GITHUB_TOKEN` on Vercel for repeated usage.


The SVG grows each bar and counts its label from 0.0% to the real final value, holds the result, fades, and repeats every six seconds. Bars use CSS scale keyframes; percentage labels use timed SVG text frames because scripts do not run when SVG is embedded as an image. Reduced-motion settings show the completed static card. The SVG's accessible description contains the final percentages.

GitHub language reports are cached in-process for one hour (up to 64 usernames); the SVG endpoint also sends one-hour Vercel CDN cache headers. A failed repository scan returns an error instead of a partial chart. `GITHUB_TOKEN` helps with GitHub request limits because a fresh scan needs a languages request for each included repository. Language percentages describe code volume, not proficiency or contribution counts.


## Yearly contributions

Open `http://127.0.0.1:8000/preview/contributions?username=baonguyen1776` to see the animated card, switch years/themes, and open all contributed repositories. The preview is an HTML page with a form and year links. The SVG itself has no scripts; images embedded in a GitHub README do not expose interactive controls or clickable repository links. Use the preview for those controls.

`/api/contributions?username=baonguyen1776&year=2026&theme=dark` returns the animated SVG. Omit `year` to use the server's current UTC year, use `theme=light` for a white card, or add `animate=false` for a static card. Years are integers from 2008 through the current year; future years return 422. `/api/contribution-data` accepts the same username/year and returns exact daily counts, metrics, available history years and the project/activity overview as JSON.

Each card spans January through December. A completed year contains all 365 or 366 dates; the current year contains actual data only through today. Future squares are visually muted placeholders, excluded from JSON dates, totals and streaks. Missing GitHub counts or incomplete calendars return an error instead of estimated values. `fetch_contributions(year=None)` retains the legacy rolling 365-day window for internal callers; HTTP endpoints default to a calendar year.

Metrics are total contributions, current streak (or **Year-end streak** for past years), longest streak within the selected year, and active days. An unfinished, empty today keeps yesterday's streak open; a completed historical December 31 has no such grace. Runs are bounded by the selected year. GitHub calendar totals include eligible contributions beyond commits; they need not equal the four activity categories below.

With `GITHUB_TOKEN`, the service uses the documented [GitHub contribution collection](https://docs.github.com/en/graphql/reference/users#contributionscollection) for the calendar, history years, contributed repositories and counts of commits, opened PRs/issues and reviews. It sums each commit-day node's `commitCount`; an active day is not one commit. If more than 100 commit-day nodes exist for a repository, it fetches quarters of at most 92 days to recover every count. Each category requests up to 100 repositories and reports `partial` if the list may be capped. Token visibility can affect activity totals; private repository names are filtered out of the response and SVG.

Without a token, the calendar comes from GitHub's public calendar HTML, joining dated cells to exact count tooltips. Optional project data comes from the selected year's public monthly activity timeline, with three concurrent requests at most. This is a web-page fallback and depends on GitHub's HTML format. It aggregates visible commit/PR/issue rollups and actual repository links, rather than substituting owned or pinned repos. Review totals and per-project review counts are `null` and shown as unavailable; missing/truncated repository details are disclosed. An unavailable project overview leaves the validated calendar usable. History links come from GitHub's actual year list. Set a valid token in Vercel for the documented API path.

The compact contribution SVG follows the GitHub contribution layout: a full-year calendar above repository controls and a four-axis activity chart. Selecting a repository keeps the full calendar geometry and highlights only that repository's commit days; PRs, issues and reviews remain statistics in the activity chart. Repository controls use short names while preserving the full `owner/name` value internally. Unknown activity categories use a dashed axis with no data point. Percentages use only known event counts. `overview.status`, `message` and `source` disclose completeness and source in JSON and preview.

The seven-segment snake follows one closed route through adjacent squares and returns around the board's edge with a continuous loop. Calendar cells stay visible at all times, so there is no per-cell restore delay. All seven segments share one animation path with phase offsets, which keeps replay smooth and makes the SVG substantially lighter to parse. Backgrounds are neutral charcoal/gray or white/light gray, with green reserved for contribution intensity. Reduced-motion preferences hide the snake and display the complete static calendar.

Set `"contribution_animation_seconds": 18` in `profile.json` for replay speed; supported integers are 12–120. Reports are cached in-process for one hour, with up to 64 username/date/source/year keys. SVG responses also send one-hour Vercel CDN headers; error cards use `no-store`. The header and stack retain their existing behavior.

After deployment, embed the SVG directly in the profile README. The external HTML preview is optional. A complete light/dark example with expandable historical years is in [examples/profile-contributions.md](examples/profile-contributions.md). Replace `YOUR-VERCEL-DOMAIN` with your deployed HTTPS hostname; localhost URLs cannot be used by GitHub visitors.

The native GitHub contribution graph, its year tabs and organization search are GitHub-owned UI. This API generates a README image; it cannot inject controls into that native graph. To expand historical years inside the README, use GitHub-supported [`<details>` sections](https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting/organizing-information-with-collapsed-sections). SVG images themselves cannot run form controls or scripts. The example also provides clickable year image buttons from `/api/contribution-year-button?year=2026`; these open the selected year in the preview. They do not replace the embedded image in place. In the preview, real form buttons select the year beside the calendar, and repository buttons open GitHub. Project buttons drawn inside the main SVG are clickable only when the SVG is opened directly; embedded README images need surrounding Markdown links.

For a simple image linked to the optional preview:

```markdown
[![Contributions](https://YOUR-VERCEL-DOMAIN/api/contributions?username=baonguyen1776&theme=dark)](https://YOUR-VERCEL-DOMAIN/preview/contributions?username=baonguyen1776&theme=dark)
```

Add `&year=2025` to both URLs for a fixed historical year. No deploy or push is needed to review the local preview.

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
