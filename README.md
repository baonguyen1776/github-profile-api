# GitHub Profile API

> **On-demand Animated SVG Engine** for personal GitHub Profile READMEs.
> 
> Automatically transforms your avatar into custom **ASCII Art**, visualizes your codebase with **real-world languages & detected technologies**, and renders a **yearly contribution graph with a continuous, looping snake animation**.

**Live Production API:** `https://github-profile-api-azure.vercel.app`

---

## 1. Core Purpose

- **Personalize GitHub Profiles**: Replace generic static badges with dynamic, living vector cards that showcase your engineering identity.
- **Real-Time Data Synchronization**: Direct integration with the GitHub API calculates exact language byte shares, scans project manifests for active frameworks, and calculates your true daily streaks.
- **Smooth Animation with Zero Client JavaScript**: All visual transitions and the looping snake game are built using **100% pure CSS `@keyframes`** embedded directly within standard SVG tags, guaranteeing seamless rendering inside GitHub's restricted markdown environments.

---

## 2. Quick Start (Embed into your Profile README)

Simply copy and paste the Markdown snippets below into your personal repository's `README.md` (replace `baonguyen1776` with your GitHub username):

### Card 1: ASCII Identity Header
Artistic ASCII portrait avatar, personal bio, location, repository counts, and follower statistics:
```markdown
![Header](https://github-profile-api-azure.vercel.app/api/header?username=baonguyen1776&theme=dark)
```

### Card 2: Tech Stack & Language Share
Language distribution based on actual repository byte counts, technology badges, and animated progress bars:
```markdown
![Tech Stack](https://github-profile-api-azure.vercel.app/api/stack?username=baonguyen1776&theme=dark)
```

### Card 3: Yearly Contributions & Snake Replay
Full-year contribution calendar, an animated snake navigating commit cells, streak metrics, and a 4-axis activity radar (click the image to open the interactive web preview):
```markdown
[![Contributions](https://github-profile-api-azure.vercel.app/api/contributions?username=baonguyen1776&theme=dark)](https://github-profile-api-azure.vercel.app/preview/contributions?username=baonguyen1776&theme=dark)
```

---

## 3. Key Features

| Feature | Description |
|---|---|
| **Pixel-to-ASCII Portrait** | Samples your actual GitHub avatar and maps pixel luminance values to an ASCII density ramp, blended harmoniously with the selected theme. |
| **Automatic Tech Detection** | Inspects manifests (`package.json`, `requirements.txt`, `pyproject.toml`) across public repositories to automatically surface framework badges (React, FastAPI, Docker, etc.). |
| **Accurate Language Metrics** | Computes byte counts directly across non-fork repositories, rendering smooth growing progress bars from `0.0%` to exact proportions. |
| **Full 365-Day Calendar** | Supports historical annual graphs from 2008 to the present day, intelligently calculating active `Current streak` vs historical `Year-end streak`. |
| **4-Axis Activity Radar** | Visualizes relative distribution across four contribution types: *Commits*, *Pull Requests*, *Issues*, and *Code Reviews*. |
| **Per-Repository Filtering** | Supports the `repo=owner/name` parameter to inspect commit patterns and contributions for any specific project. |
| **Adaptive Themes & Accessibility** | Built-in support for `light`, `dark`, and `auto` (system preference) modes. Automatically halts motion animations when `prefers-reduced-motion` is detected. |

---

## 4. Technical Implementation & Architecture

```text
HTTP Request  ──►  Routes (FastAPI)  ──►  Services (Data & Logic)  ──►  Renderers (SVG Engine)  ──►  Response SVG
```

1. **Pixel-to-ASCII Pipeline**:
   - Uses `Pillow` to resample the user avatar into a normalized **66 cols × 52 rows** grid.
   - Calculates relative luminance:
     $$\text{Luminance} = 0.2126R + 0.7152G + 0.0722B$$
   - Maps each luminance value to a character ramp (`" .:-=+*#%@"`) while tinting each character with a blend of source pixel color and theme foreground.

2. **Pure CSS Animation Engine (No Client Scripts)**:
   - Because GitHub strips `<script>` tags from images, all dynamic effects rely entirely on CSS `@keyframes`.
   - **Continuous Snake Route**: The `snake_route()` algorithm determines a closed-loop traversal around contribution cells. All seven body segments share a single `@keyframes snake-travel` definition with staggered `animation-delay` offsets, achieving a lightweight SVG footprint and buttery-smooth 60fps movement.

3. **Hybrid Data Collection (GraphQL + Scraper Fallback)**:
   - **Authenticated Mode**: Queries GitHub's GraphQL API (`contributionsCollection`) in quarterly slices (<= 92 days) to retrieve comprehensive commit days and activity breakdowns without omission.
   - **Fallback Mode**: If no `GITHUB_TOKEN` is provided or if limits are approached, falls back to parsing public GitHub contribution calendars via an HTML scraper to ensure high availability.

4. **Multi-Tier Caching & Performance**:
   - **In-Memory LRU Cache**: Stores parsed reports in RAM with a 1-hour TTL (`TTL = 3600s`), eliminating redundant upstream calls.
   - **Edge CDN Caching**: Sends `Vercel-CDN-Cache-Control` headers for global edge caching, serving images in **< 50ms** and safeguarding against GitHub rate limits.

---

## 5. API Endpoints & Parameters

| Endpoint | Method | Key Parameters | Purpose |
|---|---|---|---|
| `/api/header` | `GET` | `username` (required), `theme` (`light` \| `dark`) | ASCII avatar header card with profile metrics |
| `/api/stack` | `GET` | `username` (required), `theme` (`light` \| `dark`), `languages` (optional) | Tech stack card & language percentage bars |
| `/api/contributions` | `GET` | `username` (required), `year` (e.g. `2026`), `theme` (`auto` \| `light` \| `dark`), `animate` (`true` \| `false`), `repo` (optional) | Annual contribution calendar card with snake & radar |
| `/preview/contributions` | `GET` | `username`, `year`, `theme`, `repo` | Interactive web dashboard for browsing years & projects |
| `/api/contribution-data` | `GET` | `username`, `year`, `repo` | Raw contribution JSON payload |
| `/api/languages` | `GET` | `username` | Detected languages and byte count breakdown |
| `/api/technologies` | `GET` | `username` | Detected technologies with manifest proof references |
| `/health` | `GET` | *(none)* | Health check status (`{"status": "ok"}`) |

---

## 6. Profile Configuration (`profile.json`)

Customize the personal data rendered by cards in the root [`profile.json`](profile.json) file:

```json
{
  "stack": ["TypeScript", "C++", "Python"],
  "stack_card_languages": ["TypeScript", "C++", "Python"],
  "stack_card_technologies": ["React", "FastAPI", "Tauri", "Docker"],
  "stack_card_editors": ["Visual Studio Code", "PyCharm"],
  "tagline": "Build. Learn. Share.",
  "visual_language": "Characters become identity.",
  "focus_areas": ["Systems", "Fullstack", "AI"],
  "contribution_animation_seconds": 18
}
```

- Leave `stack_card_languages` or `stack_card_technologies` empty (`[]`) to let the engine automatically display all technologies detected from your public repositories.
- `contribution_animation_seconds`: Configure the loop duration of the snake animation (between `12` and `120` seconds).

---

## 7. Local Development & Deployment

### Local Setup
```bash
# 1. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Start the development server
uvicorn app:app --reload
```
- Interactive API Documentation (Swagger): `http://127.0.0.1:8000/docs`
- Interactive Contribution Preview: `http://127.0.0.1:8000/preview/contributions?username=baonguyen1776`

### Running Tests
```bash
python -m unittest discover tests
```

### Vercel Deployment
1. Import this repository into [Vercel](https://vercel.com).
2. Vercel automatically detects the FastAPI application in `app.py`.
3. *(Recommended)* Configure a `GITHUB_TOKEN` environment variable under **Settings → Environment Variables** on Vercel to increase the GitHub API rate limit from 60 to 5,000 requests/hour.
