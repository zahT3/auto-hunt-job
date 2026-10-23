# Discovery v2 integration contract

`from hunt.discovery import discover, default_sources`

`discover(config, profile=None, transport=None) -> {jobs, sources, queries, checked_at, requests, coverage, search_provider_configured, note}`

Primary config matches root/frontend: `keywords: [str]`, `sources: ['boss','liepin','anker','greenhouse','lever','ashby']`, `company_boards: [{type,slug,company}]`, `max_jobs` (1–100), `max_pages` (1–5), `discovery_requests` (1–100, default40), `source_modes: {boss:'public'|'browser',liepin:'public'|'browser'}`. Compatible advanced `discovery_sources: [{id,kind,board,company,enabled,mode,url}]` overrides the simplified source fields.

Default company seeds are **Anthropic (greenhouse/anthropic), Binance (lever/binance), Cursor (ashby/cursor)**, independently live fetched. OpenAI public feed exceeded the safe 5MiB response cap; intentionally not used as default. These are example seed companies, not a claim to scan all employers.

- `keywords` are user-facing role/skill search strings, max8. Fallback keyword then AI/Agent/Web3. Candidate profile is NEVER transmitted; email, long digit runs, URLs and multiline text rejected as terms.
- Global request cap and fair per-source allocations bound traffic; details count against request budget. `max_pages` bounds each term’s platform pages, all terms still share total request cap. Greenhouse/Ashby APIs return complete boards rather than pages. Greenhouse reads metadata then bounded matching details to avoid huge content feeds.
- Normalized jobs follow Store.import_job schema: channel, platform_id (board-qualified for ATS), title/company/location/salary/url/application_url/jd/requirements_text/status/collected_at/raw. Listing-only items never become fabricated JD-bearing jobs.
- Source reports: source_id, kind, status, fetched, returned, pages, requests, error, search_url, checked_at, truncated, mode. Statuses ok|empty|filtered_empty|blocked|login_required|captcha|parse_error|fetch_error|not_configured|budget_exhausted. Failures preserve any already parsed jobs and report partial status.
- Browser mode requires Playwright + Chromium; dedicated profiles `private/browser-discovery/boss` and `liepin`; never attaches to personal Chrome. User login CLI: `.venv/bin/python -m hunt.sources_browser --login boss` (or liepin). Normal scan only GET/HEAD public pages + two explicitly allowlisted Liepin read-only search POST endpoints; no messaging, form entry, upload or submit. Security gates stop current channel; there is no stealth/proxy/token extraction.
- Website source supports JobPosting JSON-LD plus bounded same-host career links. Unsupported sites explicitly parse_error, not empty.
- Optional `search_provider: {provider:'searxng',url:'https://your-instance/search'}` expands discovery with real web index results; only verified target JSON-LD becomes a job. No provider/key automatically borrowed from the assistant environment.
- `discover` optional keyword args: `browser_profile_root` (server-owned data directory), `browser_headless=False`, `should_continue` callable checked before every request, `on_source` callable receiving each completed source report. Stopping yields source status `cancelled`. CLI login supports `--data private/app`, storing sessions in its `browser-search` subfolder.

- `expanded_terms` reports the local recall aliases separately from original `queries`. JD extraction preserves paragraphs, line breaks, and plain-text comparisons. Browser list rendering waits up to20s, detail redirects away from job URLs become `blocked`.

- `profile` parameter reserved for interface consistency; local candidate understanding proposes keywords before this function.


Employer catalog and entry validation: see [official-sources](official-sources.md). `check_entries: true` enables bounded public entry checks; `entry_requests` defaults to12, cap50. `official_browser: true` optionally enables a fresh public renderer (no login profile, only explicitly allowed read-only POSTs). Catalog entries remain website sources. CLI `--catalog <id>` is repeatable; `--catalog all`, `--official-browser`, `--skip-entry-checks` are available. Entry checks report separately from source extraction, and cannot grant apply permissions. Moka receiver hash routes are preserved.
