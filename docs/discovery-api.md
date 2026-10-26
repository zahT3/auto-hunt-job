# Discovery v2 integration contract

`from hunt.discovery import discover, default_sources`

`discover(config, profile=None, transport=None) -> {jobs, sources, queries, checked_at, requests, sweep, deadline_reached, started_at, finished_at, entry_requests, entry_check, coverage, expanded_terms, search_provider_configured, note}`

Primary config matches root/frontend: `keywords: [str]`, `sources` (any of `'boss','liepin','anker','greenhouse','lever','ashby','website'`; default `['anker','greenhouse','lever','ashby']`, so boss/liepin are opt-in; a saved config that already lists them keeps them), `company_boards: [{type,slug,company}]`, `max_jobs` (1–100), `max_pages` (1–5), `discovery_requests` (1–100, default40), `source_modes: {boss:'public'|'browser',liepin:'public'|'browser'}`. Compatible advanced `discovery_sources: [{id,kind,board,company,enabled,mode,url,careers_url}]` overrides the simplified source fields. `default_sources()` lists boss and liepin with `enabled: false`.

Source kinds come from the registry in `hunt/providers/`: `greenhouse`, `lever`, `ashby`, `boss`, `liepin`, `anker`, `website`, `websearch`, plus the keyword-search providers `tencent`, `alibaba`, `meituan`, `feishu` (ByteDance and `*.jobs.feishu.cn` tenants) and `mokahr` (`app.mokahr.com` needs the optional `requirements-sources.txt`; without it the source reports `not_configured`). An entry without `kind` is routed by its `careers_url`/`url` host.

Default company seeds are **Anthropic (greenhouse/anthropic), Binance (lever/binance), Cursor (ashby/cursor)**, independently live fetched. OpenAI public feed exceeded the safe 5MiB response cap; intentionally not used as default. These are example seed companies, not a claim to scan all employers.

- `keywords` are user-facing role/skill search strings, max8. Fallback keyword then AI/Agent/Web3. Candidate profile is NEVER transmitted; email, long digit runs, URLs and multiline text rejected as terms.
- Global request cap and fair per-source allocations bound traffic; details count against request budget. `max_pages` bounds each term’s platform pages, all terms still share total request cap. Greenhouse/Ashby APIs return complete boards rather than pages. Greenhouse reads metadata then bounded matching details to avoid huge content feeds.
- Normalized jobs follow Store.import_job schema: channel, platform_id (board-qualified for ATS), title/company/location/salary/url/application_url/jd/requirements_text/status/collected_at/raw. Listing-only items never become fabricated JD-bearing jobs.
- Local matching: a term without whitespace matches itself or its alias group (`expanded_terms`). A term with whitespace matches as the literal phrase, or when every whitespace-separated segment matches through its own alias group (OR within a segment, AND across segments): `AI 产品经理` matches `资深 AI 产品经理` and `大模型产品经理`, not `大模型算法工程师`. Chinese role segments also match English titles: `开发`/`工程师`/`研发` match engineer, engineering, developer, development, `产品经理` matches product manager or product owner, and `应用` adds application or applied, so `AI 应用开发` matches `Machine Learning Engineer` and `AI 产品经理` matches `Senior AI Product Manager` (but not `Product Manager`, since the `AI` segment is still required). Keyword-search providers (tencent, alibaba, meituan, feishu, mokahr) send the whole term to the remote API and do not filter locally; anker and boss/liepin still filter their results locally.
- Source reports: source_id, kind, status, fetched, returned, pages, requests, entry_requests, rendered_pages, elapsed_seconds, passes, error, search_url, checked_at, truncated, mode (plus detail_errors/detail_error_count when single posts failed to parse). Statuses ok|empty|filtered_empty|blocked|login_required|captcha|parse_error|fetch_error|not_configured|budget_exhausted. Failures preserve any already parsed jobs and report partial status.
- Browser mode requires Playwright + Chromium; dedicated profiles `private/browser-discovery/boss` and `liepin`; never attaches to personal Chrome. User login CLI: `.venv/bin/python -m hunt.sources_browser --login boss` (or liepin). Normal scan only GET/HEAD public pages + two explicitly allowlisted Liepin read-only search POST endpoints; no messaging, form entry, upload or submit. Security gates stop current channel; there is no stealth/proxy/token extraction.
- Website source supports JobPosting JSON-LD plus bounded same-host career links. Unsupported sites explicitly parse_error, not empty.
- Optional `search_provider: {provider:'searxng',url:'https://your-instance/search'}` expands discovery with real web index results; only verified target JSON-LD becomes a job. No provider/key automatically borrowed from the assistant environment.
- `discover` optional keyword args: `browser_profile_root` (server-owned data directory), `browser_headless=False`, `should_continue` callable checked before every request, `on_source` callable receiving each first-pass source report, `clock` (monotonic seconds, for tests), `known(job) -> bool` (job already stored; a sweep skips those when choosing which jobs to entry-check). Stopping yields source status `cancelled`. CLI login supports `--data private/app`, storing sessions in its `browser-search` subfolder.

- `expanded_terms` reports the local recall aliases separately from original `queries`. JD extraction preserves paragraphs, line breaks, and plain-text comparisons. Browser list rendering waits up to20s, detail redirects away from job URLs become `blocked`.

- `profile` parameter reserved for interface consistency; local candidate understanding proposes keywords before this function.


Employer catalog and entry validation: see [official-sources](official-sources.md). `check_entries: true` enables bounded public entry checks; `entry_requests` defaults to12, cap50. `official_browser: true` optionally enables a fresh public renderer (no login profile, only explicitly allowed read-only POSTs). Catalog entries remain website sources. CLI `--catalog <id>` is repeatable; `--catalog all`, `--official-browser`, `--skip-entry-checks` are available. Entry checks report separately from source extraction, and cannot grant apply permissions. Moka receiver hash routes are preserved.

## Sweep

`sweep: true` turns on a wide bounded run. Keys (default, clamp): `sweep_max_companies` (300, 1–1000), `sweep_max_jobs` (1500, 1–5000), `sweep_requests` (3000, 1–10000), `sweep_deadline_seconds` (600, 30–3600), `sweep_prepare` (50, 0–200), `sweep_max_pages` (20, 1–50; replaces `max_pages` in a sweep, the per-source request share is the real bound). The result's `sweep` echoes the clamped values. Without `discovery_sources`, `Store.run` fills them from `hunt.companies.select()`, which skips seeds whose `status` is `dead` or `needs_adapter` unless `include_flagged=True`.

- First pass: each source gets `ceil(remaining jobs / remaining sources)` jobs and the same share of the remaining requests.
- Second pass: if the deadline has not passed and jobs and requests remain, sources that ended `ok` but `truncated` rerun from page 1, in original order, with `returned + ceil(remaining jobs / remaining candidates)` as their limit and `ceil(remaining requests / remaining candidates)` requests. Replayed jobs are dropped as duplicates. Their report sums the counters of both passes and shows `passes: 2`. Non-sweep runs have no second pass.
- After the deadline no new request starts; jobs already fetched are kept and `deadline_reached` is true.

## Entry checks

`check_entries: true` (the Store default) checks each job's public application entry. `entry_requests` sets the request budget: default 12 and cap 50 outside a sweep; default `max(12, sweep_prepare)` and cap 200 in a sweep.

- Outside a sweep, checks run inline as each job is found, with the source's public renderer when `official_browser` is on.
- In a sweep, checks run after all sources are scanned, only for the jobs that will be prepared (the first `sweep_prepare` jobs not already stored, in discovery order), and stop at the deadline; unchecked jobs are kept. These deferred checks do not use the public renderer.
- `entry_check: {mode: inline|after_discovery|off, checked, skipped, elapsed_seconds}` reports the stage; each source report keeps its own `entry_requests`.
