from datetime import datetime, timezone
from html import escape
from urllib.parse import urlencode

from services.contribution_overview import ProjectContribution
from services.contributions import ContributionReport


def render_contribution_preview(
    base: ContributionReport,
    report: ContributionReport,
    *,
    username: str,
    year: int,
    theme: str,
    repo: str | None,
) -> str:
    params: dict[str, object] = {'username':username,'year':year,'theme':theme,**({'repo':repo} if repo else {})}

    def link(path: str, **changes: object) -> str:
        return escape(path+'?'+urlencode({**params,**changes}),quote=True)

    def fields(**changes: object) -> str:
        return ''.join(f'<input type="hidden" name="{key}" value="{escape(str(value),quote=True)}">' for key,value in {**params,**changes}.items() if value is not None)
    projects = list(base.overview.projects if base.overview else ())
    if repo and not any(p.name.casefold()==repo.casefold() for p in projects):
        projects.append(next(iter(report.overview.projects),ProjectContribution(repo)) if report.overview else ProjectContribution(repo))
    shown = projects[:3]
    active = next((p for p in projects if repo and p.name.casefold()==repo.casefold()),None)
    if active and active not in shown:
        shown = shown[:2]+[active]
    def button(project: ProjectContribution) -> str:
        selected = bool(repo and repo.casefold()==project.name.casefold())
        image = f'<img class="avatar" src="{project.avatar_data_uri}" alt="" width="20" height="20">' if project.avatar_data_uri else f'<span class="avatar fallback" aria-hidden="true">{escape(project.name[0].upper())}</span>'
        return f'<button type="submit" class="repo-option {"selected" if selected else ""}" name="repo" value="{escape(project.name,quote=True)}" aria-pressed="{str(selected).lower()}" title="{escape(project.name,quote=True)}" data-search="{escape(project.name.casefold(),quote=True)}">{image}<span>{escape(project.short_name)}</span></button>'
    chips = ''.join(button(project) for project in shown)
    options = ''.join(button(project) for project in projects)
    years = sorted({year,*(base.overview.years if base.overview else ())},reverse=True)
    year_buttons = ''.join(f'<button type="submit" class="year {"active" if value==year else ""}" name="year" value="{value}" {"aria-current=\"page\"" if value==year else ""}>{value}</button>' for value in years)
    theme_options = ''.join(f'<option value="{value}" {"selected" if value==theme else ""}>{label}</option>' for value,label in [('auto','System'),('light','Light'),('dark','Dark')])
    repos = report.overview.projects if report.overview else ()
    repo_links = ''.join(f'<a class="repo-link" href="{escape(project.url,quote=True)}" target="_blank" rel="noopener noreferrer">{escape(project.short_name)} ↗</a>' for project in repos)
    message = report.overview.message if report.overview else 'Project activity is unavailable.'
    dark = '--bg:#0d1117;--panel:#161b22;--ink:#e6edf3;--muted:#8b949e;--border:#30363d;--accent:#58a6ff;color-scheme:dark;'
    css = ''':root{--bg:#ffffff;--panel:#f6f8fa;--ink:#1f2328;--muted:#656d76;--border:#d0d7de;--accent:#0969da;color-scheme:light} :root[data-theme=dark]{DARK}@media(prefers-color-scheme:dark){:root[data-theme=auto]{DARK}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}main{max-width:1034px;padding:28px 24px;margin:auto}h1{font-size:23px;margin:0 0 20px;font-weight:600}p{color:var(--muted);line-height:1.5}form.settings{display:flex;flex-wrap:wrap;align-items:end;gap:12px;margin:0 0 24px}label{display:grid;gap:6px;font-size:12px}input,select,button,summary{font:inherit;border:1px solid var(--border);border-radius:6px;background:var(--panel);color:var(--ink);padding:8px 12px}button,summary{cursor:pointer}button:hover,summary:hover{border-color:var(--accent)}button.primary,button.selected,button.active{background:#0969da;border-color:#0969da;color:white}button:disabled{opacity:.6;cursor:wait}.contribution-layout{display:grid;grid-template-columns:minmax(0,850px) 116px;align-items:start;gap:20px}.calendar,.activity{display:block;width:100%;height:auto}.repo-filters{display:flex;align-items:center;gap:7px;flex-wrap:wrap;margin:0;padding:13px 19px;border-left:1px solid var(--border);border-right:1px solid var(--border);min-height:53px}.repo-option{display:inline-flex;align-items:center;gap:6px;max-width:210px;min-height:30px;padding:4px 8px;background:var(--bg);font-size:12px;white-space:nowrap}.repo-option span:not(.avatar){overflow:hidden;text-overflow:ellipsis}.avatar{display:block;width:20px;height:20px;flex:none;border-radius:4px;object-fit:cover;background:var(--panel)}.fallback{display:grid;place-items:center;color:var(--muted)}.repo-more{position:relative}.repo-more summary{list-style:none;font-size:12px;padding:6px 15px}.repo-more summary::-webkit-details-marker{display:none}.repo-menu{position:absolute;top:35px;right:0;z-index:2;width:300px;padding:10px;background:var(--bg);border:1px solid var(--border);border-radius:7px;box-shadow:0 8px 24px #0002}.repo-menu strong{display:block;font-size:12px;margin:2px 2px 10px}.repo-menu input{width:100%;background:var(--bg);margin-bottom:8px}.repo-list{max-height:240px;overflow-y:auto}.repo-list .repo-option{display:flex;width:100%;max-width:none;border-color:transparent;text-align:left;margin:2px 0}.repo-list .repo-option[hidden]{display:none}.repo-list .repo-option:hover{background:var(--panel)}.repo-list .repo-option.selected:hover{background:#0969da}.empty-search{margin:10px;font-size:12px}.year-switcher{display:grid;gap:8px;margin:37px 0 0}.year{text-align:left;border-color:transparent;background:transparent;color:var(--muted);font-size:12px;font-weight:500;padding:8px 16px;min-height:34px}a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}.tools,.repo-links{display:flex;flex-wrap:wrap;gap:10px;margin:18px 0}.tools a,.repo-link{border:1px solid var(--border);border-radius:6px;padding:7px 10px;font-size:12px}details.info{margin:18px 0;font-size:12px}details.info summary{display:inline-block}details.info p{max-width:850px}:focus-visible{outline:2px solid var(--accent);outline-offset:2px}@media(max-width:680px){main{padding:20px 12px}.contribution-layout{display:flex;flex-direction:column;gap:12px}.contribution-layout nav{order:-1}.year-switcher{display:flex;flex-wrap:wrap;margin:0}.repo-filters{padding:10px;gap:6px}.repo-option{max-width:165px}.repo-menu{right:auto;left:0;width:min(300px,85vw)}}
'''.replace('DARK',dark)
    return f'''<!doctype html><html lang="en" data-theme="{theme}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Contributions {year} / {escape(username)}</title><style>{css}</style></head><body><main data-selected-repo="{escape(repo or '',quote=True)}"><h1>Contributions</h1>
<form class="settings" action="/preview/contributions" method="get"><label>GitHub username<input name="username" value="{escape(username,quote=True)}" required maxlength="39"></label><label>Year<input type="number" name="year" min="2008" max="{datetime.now(timezone.utc).year}" value="{year}" required></label><label>Theme<select name="theme">{theme_options}</select></label>{f'<input type="hidden" name="repo" value="{escape(repo,quote=True)}">' if repo else ''}<button class="primary" type="submit">Show year</button></form>
<div class="contribution-layout"><div class="profile-card"><img class="calendar" src="{link('/api/contributions',section='calendar')}" width="850" height="210" alt="Contribution calendar for {escape(repo or username,quote=True)} in {year}">
<form class="repo-filters" action="/preview/contributions" method="get">{fields(repo=None)}<button type="submit" class="repo-option {"selected" if not repo else ""}" name="repo" value="" aria-pressed="{str(not repo).lower()}">All</button>{chips}<details class="repo-more"><summary>More ▾</summary><div class="repo-menu"><strong>Repositories</strong><input class="repo-search" type="search" aria-label="Search repositories" placeholder="Search by name" autocomplete="off"><div class="repo-list">{options}</div><p class="empty-search" hidden>No matching repositories</p></div></details></form>
<img class="activity" src="{link('/api/contributions',section='activity')}" width="850" height="240" alt="Activity distribution for {escape(repo or username,quote=True)}"></div><nav aria-label="Contribution years"><form class="year-switcher" action="/preview/contributions" method="get">{fields(year=None)}{year_buttons}</form></nav></div>
<div class="tools"><a href="{link('/api/contributions')}" target="_blank" rel="noopener noreferrer">Open SVG</a><a href="{link('/api/contributions',animate='false')}" target="_blank" rel="noopener noreferrer">Static SVG</a><a href="{link('/api/contribution-data')}" target="_blank" rel="noopener noreferrer">View data</a></div><div class="repo-links">{repo_links}</div><details class="info"><summary>About these counts</summary><p>{escape(message)}</p></details></main>
<script>const search=document.querySelector('.repo-search'); search.addEventListener('input',()=>{{const term=search.value.toLowerCase().trim();let visible=0;document.querySelectorAll('.repo-list .repo-option').forEach(button=>{{button.hidden=!button.dataset.search.includes(term);if(!button.hidden)visible++;}});document.querySelector('.empty-search').hidden=visible>0;}});document.querySelectorAll('.repo-more').forEach(menu=>{{menu.addEventListener('toggle',()=>{{if(menu.open)search.focus();}});menu.addEventListener('keydown',event=>{{if(event.key==='Escape'){{menu.open=false;menu.querySelector('summary').focus();}}}});}});</script></body></html>'''
