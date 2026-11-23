"""Bounded multi-source job discovery: orchestration, budgets and dedup; each source lives in hunt.search.sources.

Public pages and employer job APIs are read-only. Browser mode is an explicit
opt-in and uses a dedicated local profile. Failure is never an empty-success.
"""
import math
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from collections import Counter
from contextlib import nullcontext
from urllib.parse import urlsplit
from ..net.network import fetch, FetchError, TransientFetchError
from .sources import Context, route
from .query import MODEL_COMPANIES, ai_product_title, expanded_terms, is_ai_pm_term, matches, search_terms
from .parse import SourceError, now

DEFAULT_BOARDS = [
    dict(type='greenhouse', slug='anthropic', company='Anthropic'),
    dict(type='lever', slug='binance', company='Binance'),
    dict(type='ashby', slug='cursor', company='Cursor'),
]
LOGIN_GATED = ('boss', 'liepin')
DEFAULT_KINDS = ['anker', 'greenhouse', 'lever', 'ashby']


def default_sources():
    return [dict(id=k, kind=k, enabled=k not in LOGIN_GATED, mode='public') for k in (*LOGIN_GATED, 'anker')] + [
        dict(id=b['type'] + ':' + b['slug'], kind=b['type'], board=b['slug'], company=b['company'], enabled=True)
        for b in DEFAULT_BOARDS]


def bounded(value, default, low, high):
    try: return max(low, min(high, int(value)))
    except (ValueError, TypeError): return default


def source_configs(config, cap=20):
    if 'discovery_sources' in config:
        rows = config['discovery_sources']
        if not isinstance(rows, list): raise ValueError('discovery_sources 必须是数组')
        result = []
        for row in rows[:cap]:
            if isinstance(row, dict) and row.get('enabled', True):
                item = dict(row)
                item.setdefault('kind', item.get('type'))
                item.setdefault('board', item.get('slug'))
                if item.get('kind'): item.setdefault('id', str(item['kind']) + (':' + str(item['board']) if item.get('board') else ''))
                result.append(item)
        return [s for s in result if not config.get('official_only') or s.get('kind') not in ('boss', 'liepin', 'websearch')]
    kinds = config.get('sources', DEFAULT_KINDS)
    if not isinstance(kinds, list): raise ValueError('sources 必须是数组')
    boards = config.get('company_boards', DEFAULT_BOARDS)
    if not isinstance(boards, list): raise ValueError('company_boards 必须是数组')
    result = []
    modes = config.get('source_modes') or {}
    if not isinstance(modes, dict): modes = {}
    for kind in kinds[:12]:
        if not isinstance(kind, str): continue
        if kind in ('greenhouse', 'lever', 'ashby'):
            found = [b for b in boards[:cap] if isinstance(b, dict) and b.get('type') == kind]
            if not found: result.append(dict(id=kind, kind=kind))
            for b in found:
                result.append(dict(id=kind + ':' + str(b.get('slug', '')), kind=kind, board=b.get('slug'), company=b.get('company')))
        elif kind == 'website':
            for b in boards[:cap]:
                if isinstance(b, dict) and b.get('type') == 'website':
                    result.append(dict(id='website:' + str(b.get('url')), kind=kind, url=b.get('url'), company=b.get('company')))
        else:
            result.append(dict(id=kind, kind=kind, mode=modes.get(kind, 'public')))
            if kind == 'liepin' and config.get('liepin_cards') is True: result[-1]['cards'] = True
    if config.get('search_provider'):
        if not isinstance(config['search_provider'], dict): raise ValueError('search_provider 必须是配置对象')
        result.append(dict(id='websearch', kind='websearch', provider=config['search_provider'].get('provider'), url=config['search_provider'].get('url')))
    return [s for s in result[:cap] if not config.get('official_only') or s.get('kind') not in ('boss', 'liepin', 'websearch')]


RETRY_BACKOFF = 1.5  # seconds before the one retry of a dropped connection


class Budget:
    """A shared request budget, safe for several source threads; `child()` counts one source's share of it."""
    def __init__(self, transport, maximum, should_continue=None, parent=None):
        self.transport, self.maximum, self.used, self.retries = transport, maximum, 0, 0
        self.should_continue, self.parent = should_continue, parent
        self.root = parent.root if parent else self
        self.lock = self.root.lock if parent else threading.Lock()
    def child(self):
        return Budget(self.transport, self.maximum, self.should_continue, parent=self)
    def _charge(self, retry=False):
        """Spends one request of the root budget, or returns False when none is left."""
        with self.lock:
            if self.root.used >= self.root.maximum: return False
            node = self
            while node:
                node.used += 1
                if retry: node.retries += 1
                node = node.parent
            return True
    def charge(self):
        if not self._charge(): raise SourceError('budget_exhausted', '本轮公开请求预算已用完；保留已取得结果')
    def get(self, url, **kwargs):
        if self.should_continue and not self.should_continue(): raise SourceError('cancelled', '扫描已停止；没有继续发起请求')
        self.charge()
        try:
            return self.transport(url, **kwargs)
        except TransientFetchError:
            # One retry, only for a dropped connection or timeout, never for an HTTP status or a parse problem. It costs
            # a request of the budget; with none left (or the scan stopped) the original error stands.
            if self.should_continue and not self.should_continue() or not self._charge(retry=True): raise
        time.sleep(RETRY_BACKOFF)
        return self.transport(url, **kwargs)


SUMMED = ('pages', 'fetched', 'filtered', 'requests', 'retries', 'entry_requests', 'rendered_pages', 'elapsed_seconds')


def sweep_limits(config):
    if config.get('sweep') is not True: return None
    return dict(max_companies=bounded(config.get('sweep_max_companies'), 300, 1, 1000),
                max_jobs=bounded(config.get('sweep_max_jobs'), 1500, 1, 5000),
                requests=bounded(config.get('sweep_requests'), 3000, 1, 10000),
                deadline_seconds=bounded(config.get('sweep_deadline_seconds'), 600, 30, 3600),
                prepare=bounded(config.get('sweep_prepare'), 50, 0, 200),
                max_pages=bounded(config.get('sweep_max_pages'), 20, 1, 50),
                workers=bounded(config.get('sweep_workers'), 4, 1, 8))


SHARED_HOST_KINDS = ('mokahr', 'dayee', 'greenhouse', 'lever', 'ashby')
SHARED_HOSTS = ('app.mokahr.com', 'mokahr.com', 'boards-api.greenhouse.io', 'boards.greenhouse.io', 'api.lever.co', 'jobs.lever.co',
                'api.ashbyhq.com', 'jobs.ashbyhq.com')


def host_key(source):
    """Sources with the same key never run at the same moment: the request host, or kind plus tenant where one provider
    serves many employers from a single host. Browser-driven sources share one key and run one at a time."""
    kind = source.get('kind')
    if kind in LOGIN_GATED and source.get('mode') == 'browser' or kind == 'website' and source.get('official_browser'): return 'browser'
    parts = urlsplit(str(source.get('careers_url') or source.get('url') or ''))
    host = parts.netloc.lower()
    if source.get('board'): return '%s:%s' % (kind, source['board'])
    if kind in SHARED_HOST_KINDS or host in SHARED_HOSTS or host.endswith('.mokahr.com'): return host + parts.path.rstrip('/')
    return host or 'kind:%s' % kind


def _source_queries(source, terms, sweep):
    """Extra remote probes run only with a local title check before the provider spends a job slot."""
    if not sweep or not any(is_ai_pm_term(t) for t in terms) or not all(ai_product_title(t) for t in terms):
        return terms
    kind, company = source.get('kind'), source.get('company')
    if kind in ('mokahr', 'feishu') and (company in MODEL_COMPANIES or company == '知乎'):
        # Small model-company boards and Zhihu's small product listing can be searched by role alone.
        return list(dict.fromkeys(['产品', *terms]))
    if kind in ('xiaohongshu', 'didi'):
        # These adapters scan a list and apply their terms to title + JD before calling keep(job).
        return list(dict.fromkeys([*terms, '产品']))
    if source.get('broad', True) and kind in ('tencent', 'meituan', 'alibaba', 'feishu', 'jd', 'netease'):
        probes = ['MaaS', '多模态', 'AI产品', 'Agent产品']
        if kind == 'jd':
            # JD's literal matching misses qualifiers inside a phrase such as “AI 助手产品经理”.
            probes.append('产品经理')
        return list(dict.fromkeys([*terms, *probes]))
    return terms


def discover(config, profile=None, transport=None, *, browser_profile_root=None, browser_headless=False, should_continue=None, on_source=None, clock=time.monotonic, known=None):
    """`known(job)` is True for a job already stored; a sweep spends its entry checks only on the others."""
    terms = search_terms(config, profile)
    if not terms: raise ValueError('没有搜索词：请先确定方向或填写搜索关键词')
    sweep, started_at = sweep_limits(config), now()
    timing = dict(reached=False)
    if sweep:
        deadline = clock() + sweep['deadline_seconds']
        user_continue = should_continue
        def should_continue():
            if timing['reached'] or clock() >= deadline:
                timing['reached'] = True
                return False
            return user_continue() if user_continue else True
    jobs, reports, seen, owners = [], [], set(), {}
    lock, taken = threading.RLock(), [0]  # `taken` counts kept jobs while a pass is still running; `jobs` is filled in source order after it
    if not terms: raise ValueError('请提供 1 至 8 个岗位或技能关键词；不接受联系方式或整段简历作为搜索词')
    sources = source_configs(config, sweep['max_companies'] if sweep else 20)
    if config.get('official_only') and not sources:
        raise ValueError('官网模式没有可搜索的公司来源；请选择安克、招聘看板或添加公司招聘页')
    limit = sweep['max_jobs'] if sweep else bounded(config.get('max_jobs', config.get('discovery_limit')), 30, 1, 100)
    # In a sweep the per-source request share, not the page count, is the real bound.
    pages = sweep['max_pages'] if sweep else bounded(config.get('max_pages', config.get('discovery_pages')), 2, 1, 5)
    maximum = sweep['requests'] if sweep else bounded(config.get('discovery_requests'), 40, 1, 100)
    budget = Budget(transport or fetch, maximum, should_continue=should_continue)
    entry_budget = Budget(transport or fetch, bounded(config.get('entry_requests'), max(12, sweep['prepare']) if sweep else 12, 1, 200 if sweep else 50),
                          should_continue=should_continue)
    # A sweep checks entries after discovery, so slow entry pages cannot eat the time other companies need.
    inline_checks = bool(config.get('check_entries')) and not sweep
    entry = dict(mode='inline' if inline_checks else 'after_discovery' if config.get('check_entries') else 'off', checked=0, skipped=0, elapsed_seconds=0.0)

    def new_report(source):
        return dict(source_id=source.get('id') or str(source.get('kind')), kind=source.get('kind'), company=source.get('company'), status='empty',
                    fetched=0, returned=0, filtered=0, pages=0, requests=0, retries=0, error=None, search_url=None, checked_at=now(), truncated=False,
                    mode=source.get('mode', 'public'), passes=1)

    def run_source(source, report, quota, request_quota, pages, mine):
        kind = source.get('kind'); sid = report['source_id']
        began, spent, entry_spent = clock(), budget.child(), entry_budget.child()
        renderer = None; context = None
        def read(url, **kwargs):
            if spent.used >= request_quota:
                raise SourceError('budget_exhausted', '此渠道已用完公平分配的请求预算；其他渠道继续扫描')
            return spent.get(url, **kwargs)
        try:
            if should_continue and not should_continue(): raise SourceError('cancelled', '扫描已停止；没有继续发起请求')
            if taken[0] >= limit: raise SourceError('budget_exhausted', '已达到本轮保留岗位上限')
            if kind in ('boss', 'liepin') and source.get('mode') == 'browser':
                from .sources_browser import BrowserReader
                context = BrowserReader(kind, profile_root=browser_profile_root, headless=browser_headless,
                                        channel=config.get('browser_channel'))
            elif kind == 'website' and config.get('official_browser'):
                from .official_browser import PublicRenderer
                from .sources.catalog import lookup
                entry_row = lookup(source.get('url', ''))
                render_budget = min(3,pages) + 2*min(quota,pages) if entry_row and entry_row['id'] == 'minimax' else pages+3
                context = PublicRenderer(maximum=render_budget, should_continue=should_continue)
            else: context = nullcontext(None)
            with context as browser:
                if kind == 'website': renderer = browser
                if browser and kind in ('boss', 'liepin'):
                    def read(url, **kwargs):
                        if should_continue and not should_continue(): raise SourceError('cancelled', '扫描已停止；没有继续发起请求')
                        if spent.used >= request_quota: raise SourceError('budget_exhausted', '浏览器页面请求预算已用完')
                        spent.charge()
                        return browser.read(url)
                provider = route(source)
                if not provider: raise SourceError('not_configured', '未知岗位渠道：' + str(kind))
                if provider.id != kind:
                    source = provider.detect(source)
                    parts = urlsplit(str(source.get('careers_url') or source.get('url') or ''))
                    report['kind'] = provider.id
                    report['source_id'] = sid = source.get('id') or (
                        provider.id + (':' + parts.netloc + parts.path.rstrip('/') if parts.netloc else ''))
                # In a sweep, a broad platform's remote keyword search must also match the terms locally (by title, as the
                # job is named) before it takes a job slot; a company's own board, and any search outside a sweep, is
                # trusted as before. Sources configured without the flag count as broad.
                queries = _source_queries(source, terms, sweep)
                if queries != terms:
                    report['queries'] = queries
                    def keep(job):
                        return ai_product_title(job['title'], source.get('company')) or matches(job['title'], terms)
                elif sweep and source.get('broad', True):
                    keep = lambda job: matches(job['title'], terms)
                else:
                    keep = None
                generator = provider.fetch(source, Context(read, queries, quota, pages, report, renderer, keep=keep))
                for item in generator:
                    key = (item['channel'], item['platform_id'])
                    with lock:
                        if key in seen: continue
                        # A provider that ignores ctx.limit must not eat the shares of later sources.
                        if sweep and (report['returned'] >= quota or taken[0] >= limit):
                            report['truncated'] = True
                            break
                        seen.add(key); taken[0] += 1
                    item.setdefault('raw', {})['discovery'] = dict(source_id=sid, queries=queries, mode=report['mode'], checked_at=report['checked_at'])
                    # A login-gated platform's job page only answers a logged-in browser; a plain read of it proves nothing
                    # (猎聘 gave identity_mismatch every time) and adds requests from this IP.
                    if inline_checks and kind not in LOGIN_GATED:
                        from .entries import check_job
                        checking = clock()
                        try: check_job(item, entry_spent.get, renderer=renderer)
                        except SourceError as e:
                            # The fetched job is real; only its entry check was cut off by the deadline.
                            if e.status == 'cancelled' and timing['reached']: keep_job(item, report, mine)
                            raise
                        finally:
                            with lock: entry['elapsed_seconds'] += clock() - checking
                        with lock: entry['checked'] += 1
                    keep_job(item, report, mine)
            report['status'] = 'ok' if report['returned'] else 'filtered_empty' if report['fetched'] else 'empty'
            if report.get('detail_errors'):
                report['status'] = 'parse_error'
                report['error'] = str(report.get('detail_error_count') or len(report['detail_errors'])) + ' 个岗位详情无法解析；已保留其余真实结果'
        except SourceError as e:
            report['status'], report['error'] = e.status, str(e)
            if e.status == 'budget_exhausted' or e.status == 'cancelled' and timing['reached']: report['truncated'] = True
        except FetchError as e:
            report['status'] = 'blocked' if re.search(r'HTTP (401|403|429)', str(e)) else 'fetch_error'
            report['error'] = str(e)
        except (ValueError, TypeError, KeyError, AttributeError) as e:
            report['status'], report['error'] = 'parse_error', str(e)[:400]
        report['requests'] = spent.used
        report['retries'] = spent.retries
        report['entry_requests'] = entry_spent.used
        report['rendered_pages'] = getattr(renderer, 'used', 0)
        denied = getattr(context, 'denied_requests', None)
        if denied:
            tally = Counter((d['method'], d['url'], d.get('why')) for d in denied)
            report['blocked_requests'] = [dict(method=m, url=u, why=w, count=n) for (m, u, w), n in tally.most_common(20)]
        driver = getattr(context, 'driver', None)
        if driver:
            report['browser_driver'] = driver
            if driver == 'playwright':
                from .sources_browser import FALLBACK_NOTE
                report['browser_note'] = FALLBACK_NOTE
        report['elapsed_seconds'] = round(clock() - began, 2)

    def keep_job(item, report, mine):
        mine.append(item)
        report['returned'] += 1

    def run_pass(items, launch, finish):
        """Runs `items` on the sweep's worker pool, started in order; two sources with one host_key never overlap.
        launch(position, running) -> run_source args, or None to stop, is called on this thread when the source starts, finish(position, result)
        when it ends. A source that finds the scan stopped is still started, so it is marked cancelled."""
        if not items: return
        pending, running, blocked = list(range(len(items))), {}, set()
        with ThreadPoolExecutor(max_workers=sweep['workers'] if sweep else 1) as pool:
            while pending or running:
                for position in list(pending):
                    if len(running) >= (sweep['workers'] if sweep else 1): break
                    host = host_key(items[position][0]) if sweep else None
                    if host is not None and host in blocked: continue
                    args = launch(position, len(running))
                    if args is None:  # the scan is over; nothing further starts
                        pending.clear()
                        break
                    pending.remove(position)
                    if host is not None: blocked.add(host)
                    running[pool.submit(run_source, *args)] = (position, host)
                done, _ = wait(running, return_when=FIRST_COMPLETED)
                for future in done:
                    position, host = running.pop(future)
                    blocked.discard(host)
                    future.result()
                    finish(position)

    def scan(group):
        pairs = [(source, new_report(source)) for source in group]
        reports.extend(report for _, report in pairs)
        mines, started = [[] for _ in group], [0]
        def launch(position, running):
            source, report = pairs[position]
            # Reserve work for later sources, so one large board cannot starve all others.
            remaining = len(group) - started[0] + running
            started[0] += 1
            with lock:
                quota, request_quota = max(1, math.ceil((limit - taken[0]) / remaining)), max(1, math.ceil((maximum - budget.used) / remaining))
            return source, report, quota, request_quota, pages, mines[position]
        def finish(position):
            source, report = pairs[position]
            for item in mines[position]: owners[id(item)] = report
            if on_source: on_source(dict(report))
        run_pass(pairs, launch, finish)
        for mine in mines: jobs.extend(mine)
        if not sweep: return
        # Shares that small sources left unused flow back to the ones cut off by their share or page cap.
        candidates = [(s, r) for s, r in pairs if r['status'] == 'ok' and r['truncated']]
        reruns, mines, started = {}, [[] for _ in candidates], [0]
        def launch_again(position, running):
            source, report = candidates[position]
            if taken[0] >= limit or budget.used >= maximum or not should_continue(): return None
            remaining = len(candidates) - started[0] + running
            started[0] += 1
            again = reruns[position] = dict(new_report(source), source_id=report['source_id'], returned=report['returned'])
            # Reruns from page 1; `seen` drops the replayed jobs, which still count towards ctx.limit.
            return source, again, report['returned'] + math.ceil((limit - taken[0]) / remaining), math.ceil((maximum - budget.used) / remaining), pages, mines[position]
        def finish_again(position):
            source, report = candidates[position]; again = reruns[position]
            for item in mines[position]: owners[id(item)] = report
            report.update(again, passes=2, search_url=report['search_url'] or again['search_url'], checked_at=report['checked_at'],
                          **{k: report[k] + again[k] for k in SUMMED})
            report['elapsed_seconds'] = round(report['elapsed_seconds'], 2)
        run_pass(candidates, launch_again, finish_again)
        for mine in mines: jobs.extend(mine)

    # companies.select marks a sweep's sources by relevance (tier 0 keyword search, 1 matching tags, 2+ the rest).
    # Relevant sources get both passes, sharing jobs and requests among themselves, before the unrelated tail starts,
    # so the deadline cuts the tail instead of the big boards' top-up. Untiered sources all count as relevant.
    tiered = sweep and any('tier' in s for s in sources)
    for group in ([s for s in sources if s.get('tier', 1) <= 1], [s for s in sources if s.get('tier', 1) > 1]) if tiered else (sources,):
        scan(group)
    if sweep:
        if config.get('check_entries'):
            from .entries import check_job
            began = clock()
            # Only the jobs a sweep will prepare: the first `prepare` not stored before, in discovery order.
            planned = [item for item in jobs if not (known and known(item))][:sweep['prepare']]
            for item in planned:
                if not should_continue(): break
                owner, used = owners[id(item)], entry_budget.used
                try: check_job(item, entry_budget.get)
                except SourceError as e:
                    if e.status != 'cancelled': raise
                    break
                finally: owner['entry_requests'] += entry_budget.used - used
                entry['checked'] += 1
            entry['skipped'] = len(planned) - entry['checked']
            entry['elapsed_seconds'] = clock() - began
    entry['elapsed_seconds'] = round(entry['elapsed_seconds'], 2)
    return dict(jobs=jobs, sources=reports, queries=terms, checked_at=now(), requests=budget.used,
                sweep=sweep, deadline_reached=timing['reached'], started_at=started_at, finished_at=now(),
                entry_requests=entry_budget.used, entry_check=entry, coverage='configured_sources_only', expanded_terms=expanded_terms(terms), search_provider_configured=bool(config.get('search_provider')),
                note='仅扫描配置渠道与公司看板；关键词用于发现，不代表候选人胜任、工作许可或岗位仍可投递。')
