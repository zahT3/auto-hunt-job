"""Bounded multi-source job discovery, independent of any coding-agent tools.

Public pages and employer job APIs are read-only. Browser mode is an explicit
opt-in and uses a dedicated local profile. Failure is never an empty-success.
"""
import json
import math
import re
import time
from contextlib import nullcontext
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit
from .network import fetch, FetchError
from .providers import REGISTRY, Context, route
from .sources import (SourceError, Document, now, json_data, at_board, plain, normalize,
                      greenhouse_row, lever_row, ashby_row, jsonld_jobs, platform_links,
                      platform_detail, gate, public_url)

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


def search_terms(config, profile=None):
    # The entire candidate profile is intentionally ignored at the network layer.
    # Local understanding proposes role labels; only explicit search fields leave.
    terms = config.get('keywords', config.get('search_terms'))
    if not isinstance(terms, list) or not terms: terms = [config.get('keyword')] if config.get('keyword') else ['AI', 'Agent', 'Web3']
    result = []
    for term in terms[:12]:
        if not isinstance(term, str): continue
        term = term.strip()
        if not term or len(term) > 100: continue
        if re.search(r'@|https?://|\d{7,}|[\r\n]', term): continue
        if term not in result: result.append(term)
        if len(result) == 8: break
    return result


ROLE_ALIASES = [
    (('开发', '工程师', '研发'), ['engineer', 'engineering', 'developer', 'development']),
    (('产品经理',), ['product manager', 'product owner']),
]


def _segment_aliases(segment):
    # Only a segment of a multi-word term gets role aliases; a lone '开发' keeps matching narrowly.
    extra = [a for roles, values in ROLE_ALIASES if any(r in segment for r in roles) for a in values]
    if '应用' in segment and extra: extra += ['application', 'applied']
    return extra


def expanded_terms(terms):
    """Explicit, inspectable recall aliases; this does not assert candidate fit."""
    groups = {
        'ai': ['AI', '人工智能', 'machine learning', '机器学习', 'LLM', '大模型', '深度学习'],
        'web3': ['web3', 'blockchain', '区块链', 'smart contract', '智能合约'],
        'agent': ['agent', '智能体'],
        'rag': ['RAG', 'retrieval augmented generation', '检索增强', 'retrieval'],
    }
    result = {}
    for term in terms:
        aliases = [term]
        lower = term.lower()
        for key, values in groups.items():
            triggers = [key] + [v for v in values if any(ord(c) > 127 for c in v)]
            if any((re.search(r'(?<![a-z0-9_])' + re.escape(t) + r'(?![a-z0-9_])', lower) if t.isascii() else t in lower) for t in triggers):
                aliases.extend(values)
        if len(term.split()) > 1:
            for segment in term.split(): aliases.extend(_segment_aliases(segment))
        result[term] = list(dict.fromkeys(aliases))
    return result


def _found(words, text):
    for word in words:
        pattern = re.escape(word)
        if word[0].isascii() and word[0].isalnum(): pattern = r'(?<![A-Za-z0-9_])' + pattern
        if word[-1].isascii() and word[-1].isalnum(): pattern += r'(?![A-Za-z0-9_])'
        if re.search(pattern, text, re.I): return True
    return False


def matches(text, terms):
    """Local filter. A multi-word term matches as the whole phrase, or when every segment
    (each through its own alias group) matches: '大模型算法工程师' is not an 'AI 产品经理'."""
    if not terms: return False
    text = plain(text)
    for term, words in expanded_terms(terms).items():
        segments = term.split()
        if len(segments) < 2:
            if _found(words, text): return True
        elif _found([term], text) or all(_found(expanded_terms([s])[s] + _segment_aliases(s), text) for s in segments): return True
    return False


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
    if config.get('search_provider'):
        if not isinstance(config['search_provider'], dict): raise ValueError('search_provider 必须是配置对象')
        result.append(dict(id='websearch', kind='websearch', provider=config['search_provider'].get('provider'), url=config['search_provider'].get('url')))
    return [s for s in result[:cap] if not config.get('official_only') or s.get('kind') not in ('boss', 'liepin', 'websearch')]


class Budget:
    def __init__(self, transport, maximum, should_continue=None):
        self.transport, self.maximum, self.used = transport, maximum, 0
        self.should_continue = should_continue
    def get(self, url, **kwargs):
        if self.should_continue and not self.should_continue(): raise SourceError('cancelled', '扫描已停止；没有继续发起请求')
        if self.used >= self.maximum: raise SourceError('budget_exhausted', '本轮公开请求预算已用完；保留已取得结果')
        self.used += 1
        return self.transport(url, **kwargs)


def _html(raw):
    try: return raw.decode('utf-8') if isinstance(raw, bytes) else str(raw)
    except UnicodeError as e: raise SourceError('parse_error', '网页编码无法解析') from e


def _api(source, read, terms, limit, pages, report):
    kind, board = source['kind'], at_board(source['kind'], source.get('board'))
    company = source.get('company') or board
    if kind == 'greenhouse':
        # The full content feed can exceed 5 MiB. Discover IDs first, then read
        # bounded matching details. Greenhouse's public list is not paginated.
        url = 'https://boards-api.greenhouse.io/v1/boards/' + board + '/jobs'
        report['search_url'] = url
        data = json_data(read(url)); rows = data.get('jobs') if isinstance(data, dict) else None
        if not isinstance(rows, list): raise SourceError('parse_error', 'Greenhouse 列表结构变化')
        report['pages'] = 1; report['fetched'] = len(rows)
        matching = [r for r in rows if isinstance(r, dict) and r.get('id') and matches(r.get('title', ''), terms)]
        report['filter_scope'] = 'title'
        for row in matching[:limit]:
            detail_url = url + '/' + str(row['id'])
            detail = json_data(read(detail_url))
            if str(detail.get('id')) != str(row['id']): raise SourceError('parse_error', 'Greenhouse 详情身份不一致')
            yield greenhouse_row(detail, board, company)
        report['truncated'] = len(matching) > limit
    elif kind == 'ashby':
        url = 'https://api.ashbyhq.com/posting-api/job-board/' + board + '?includeCompensation=true'
        report['search_url'] = url
        data = json_data(read(url)); rows = data.get('jobs') if isinstance(data, dict) else None
        if not isinstance(rows, list): raise SourceError('parse_error', 'Ashby 列表结构变化')
        report['pages'] = 1; report['fetched'] = len(rows); count = 0
        for row in rows:
            if not isinstance(row, dict): raise SourceError('parse_error', 'Ashby 岗位结构变化')
            if row.get('isListed') is False: continue
            if not matches(row.get('title', '') + ' ' + str(row.get('descriptionPlain', '')), terms): continue
            if count >= limit: report['truncated'] = True; break
            yield ashby_row(row, board, company); count += 1
    else:
        count, seen = 0, set()
        for page in range(pages):
            url = 'https://api.lever.co/v0/postings/' + board + '?' + urlencode(dict(mode='json', skip=page * 50, limit=50))
            if not report['search_url']: report['search_url'] = url
            rows = json_data(read(url))
            if not isinstance(rows, list): raise SourceError('parse_error', 'Lever 列表结构变化')
            report['pages'] += 1; report['fetched'] += len(rows)
            new = 0
            for row in rows:
                if not isinstance(row, dict) or not row.get('id'): raise SourceError('parse_error', 'Lever 岗位缺少身份')
                if row['id'] in seen: continue
                seen.add(row['id']); new += 1
                if not matches(row.get('text', '') + ' ' + str(row.get('descriptionPlain', '')), terms): continue
                if count >= limit: report['truncated'] = True; return
                yield lever_row(row, board, company); count += 1
            if len(rows) < 50: break
            if not new: raise SourceError('parse_error', 'Lever 分页重复，已停止而不是继续请求')
            if page == pages - 1: report['truncated'] = True


def _platform(source, read, terms, limit, pages, report):
    kind = source['kind']; seen = set(); count = 0; failures = []
    for term in terms:
        for page in range(pages):
            url = ('https://www.zhipin.com/web/geek/job?' + urlencode(dict(query=term, city='100010000', page=page + 1)) if kind == 'boss'
                   else 'https://www.liepin.com/zhaopin/?' + urlencode(dict(key=term, currentPage=page, pageSize=40, scene='input', inputFrom='www_index')))
            if not report['search_url']: report['search_url'] = url
            html = _html(read(url)); text = gate(html)
            report['pages'] += 1
            links = platform_links(html, url, kind)
            if not links:
                if re.search(r'暂无.{0,8}(职位|岗位)|没有找到.{0,8}(职位|岗位)|未找到.{0,8}(职位|岗位)', text): break
                raise SourceError('blocked', '公开页面未提供岗位列表，需要浏览器渲染或登录；不是零岗位。可启用独立浏览器只读模式')
            fresh = [link for link in links if link not in seen]
            report['fetched'] += len(fresh)
            if not fresh: break
            for link in fresh:
                seen.add(link)
                if count >= limit: report['truncated'] = True; return
                try:
                    item = platform_detail(_html(read(link)), link, kind)
                except SourceError as e:
                    if e.status != 'parse_error': raise
                    failures.append(dict(url=link, status=e.status, error=str(e)))
                    report['detail_errors'] = failures
                    continue
                if item['status'] == 'closed': continue
                if matches(item['title'] + ' ' + item['jd'], terms):
                    yield item; count += 1
            if page == pages - 1: report['truncated'] = True
    if failures: raise SourceError('parse_error', str(len(failures)) + ' 个岗位详情无法解析；已保留其余真实结果')


def _anker(source, read, terms, limit, pages, report):
    from .anker import Anker, BASE, WEBSITE, ChannelError, _json, platform_id
    seen = set(); count = 0; adapter = Anker(transport=read)
    for term in terms:
        for page in range(1, pages + 1):
            url = BASE + '/lark/openapi/getJobPosts/' + WEBSITE + '?' + urlencode(dict(page=page, size=20))
            if not report['search_url']: report['search_url'] = url
            data = _json(read(url, method='POST', data=json.dumps(dict(job_function_id=[], city_code=[], subject_id=[], language_key=[], keywords=term)).encode(), headers={'Content-Type': 'application/json'}))
            rows = data.get('data')
            if not isinstance(rows, list): raise SourceError('parse_error', '安克岗位列表结构变化')
            report['pages'] += 1; report['fetched'] += len(rows)
            fresh = 0
            for row in rows:
                pid = platform_id(row.get('id', ''))
                if pid in seen: continue
                seen.add(pid); fresh += 1
                if not matches(row.get('title', ''), terms): continue
                if count >= limit: report['truncated'] = True; return
                try:
                    item = adapter.detail(pid)
                except ChannelError as error:
                    report.setdefault('detail_errors', []).append(dict(platform_id=pid, status='parse_error', error=str(error)))
                    continue
                if item['status'] == 'open': yield item; count += 1
            if len(rows) < 20: break
            if not fresh: break
            if page == pages: report['truncated'] = True


def _website(source, read, terms, limit, pages, report, renderer=None):
    from .careers import linked_boards, attach_route
    url = public_url(source.get('url') or '')
    if not url: raise SourceError('not_configured', '请配置公司官网公开 HTTPS 招聘页')
    from .catalog import lookup
    if lookup(url):
        from .domestic import read_jobs
        yield from read_jobs(source, read, terms, limit, pages, report, renderer)
        return
    report['search_url'] = url; queue = [url]; seen = set(); emitted = set(); count = 0; boards_seen = set()
    while queue and report['pages'] < pages:
        current = queue.pop(0)
        if current in seen: continue
        seen.add(current)
        html = _html(read(current)); gate(html); report['pages'] += 1
        rows = jsonld_jobs(html, current)
        report['fetched'] += len(rows)
        for item in rows:
            if item['url'] in emitted or item['status'] == 'closed': continue
            emitted.add(item['url'])
            if not matches(item['title'] + ' ' + item['jd'], terms): continue
            if count >= limit: report['truncated'] = True; return
            yield item; count += 1
        for board in linked_boards(html, current):
            key = (board['kind'], board['board'])
            if key in boards_seen: continue
            boards_seen.add(key)
            report.setdefault('linked_boards', []).append(board)
            if count >= limit or report['pages'] >= pages:
                report['truncated'] = True
                return
            child = dict(pages=0, fetched=0, truncated=False, search_url=None)
            try:
                for item in _api(dict(board, company=source.get('company') or urlsplit(url).hostname),
                                 read, terms, limit-count, pages-report['pages'], child):
                    identity = (item['channel'], item['platform_id'])
                    if identity in emitted: continue
                    emitted.add(identity)
                    attach_route(item, board)
                    from .entries import official_job_link
                    alternate = official_job_link(html, current, item['title'])
                    if alternate: item['raw']['application_route']['official_job_url'] = alternate
                    yield item; count += 1
            finally:
                report['pages'] += child['pages']
                report['fetched'] += child['fetched']
                report['truncated'] = report['truncated'] or child['truncated']
        for n in Document(html).root.nodes():
            if n.tag != 'a': continue
            link = public_url(urljoin(current, n.attrs.get('href', '')))
            if urlsplit(link).hostname == urlsplit(url).hostname and re.search(r'job|career|position|recruit', urlsplit(link).path, re.I) and link not in seen and link not in queue:
                queue.append(link)
    report['truncated'] = report['truncated'] or bool(queue)
    if not emitted and not boards_seen: raise SourceError('parse_error', '官网未提取到 JobPosting 正文或受支持的招聘看板；当前页需专用适配，不能视作无岗位')


def _websearch(source, read, terms, limit, pages, report):
    if source.get('provider') != 'searxng':
        raise SourceError('not_configured', '全网索引扩展需配置自有 SearXNG HTTPS JSON 搜索端点；不依赖 Codex 搜索工具')
    endpoint = public_url(source.get('url') or '')
    if not endpoint: raise SourceError('not_configured', 'SearXNG 端点无效，仅支持公开 HTTPS')
    seen = set(); count = 0
    for term in terms:
        for page in range(1, pages + 1):
            p = urlsplit(endpoint)
            url = urlunsplit((p.scheme, p.netloc, p.path or '/search', urlencode(dict(q=term + ' jobs careers', format='json', pageno=page)), ''))
            if not report['search_url']: report['search_url'] = url
            data = json_data(read(url)); rows = data.get('results') if isinstance(data, dict) else None
            if not isinstance(rows, list): raise SourceError('parse_error', '搜索端点未返回 results 数组或未启用 JSON')
            report['pages'] += 1; report['fetched'] += len(rows)
            for row in rows[:10]:
                target = public_url(row.get('url') or '')
                if not target or target in seen: continue
                seen.add(target)
                # Only the employer/platform page can supply the actual JD;
                # snippets are never fabricated into job descriptions.
                html = _html(read(target)); gate(html)
                for item in jsonld_jobs(html, target):
                    if item['status'] != 'closed' and matches(item['title'] + ' ' + item['jd'], terms):
                        if count >= limit: report['truncated'] = True; return
                        yield item; count += 1
            if not rows: break
            if page == pages: report['truncated'] = True


SUMMED = ('pages', 'fetched', 'requests', 'entry_requests', 'rendered_pages', 'elapsed_seconds')


def sweep_limits(config):
    if config.get('sweep') is not True: return None
    return dict(max_companies=bounded(config.get('sweep_max_companies'), 300, 1, 1000),
                max_jobs=bounded(config.get('sweep_max_jobs'), 1500, 1, 5000),
                requests=bounded(config.get('sweep_requests'), 3000, 1, 10000),
                deadline_seconds=bounded(config.get('sweep_deadline_seconds'), 600, 30, 3600),
                prepare=bounded(config.get('sweep_prepare'), 50, 0, 200),
                max_pages=bounded(config.get('sweep_max_pages'), 20, 1, 50))


def discover(config, profile=None, transport=None, *, browser_profile_root=None, browser_headless=False, should_continue=None, on_source=None, clock=time.monotonic, known=None):
    """`known(job)` is True for a job already stored; a sweep spends its entry checks only on the others."""
    terms = search_terms(config, profile)
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
                    fetched=0, returned=0, pages=0, requests=0, error=None, search_url=None, checked_at=now(), truncated=False,
                    mode=source.get('mode', 'public'), passes=1)

    def run_source(source, report, quota, request_quota, pages):
        kind = source.get('kind'); sid = report['source_id']
        began, start, entry_start = clock(), budget.used, entry_budget.used
        renderer = None
        def read(url, **kwargs):
            if budget.used - start >= request_quota:
                raise SourceError('budget_exhausted', '此渠道已用完公平分配的请求预算；其他渠道继续扫描')
            return budget.get(url, **kwargs)
        try:
            if should_continue and not should_continue(): raise SourceError('cancelled', '扫描已停止；没有继续发起请求')
            if len(jobs) >= limit: raise SourceError('budget_exhausted', '已达到本轮保留岗位上限')
            if kind in ('boss', 'liepin') and source.get('mode') == 'browser':
                from .sources_browser import BrowserReader
                context = BrowserReader(kind, profile_root=browser_profile_root, headless=browser_headless,
                                        channel=config.get('browser_channel'))
            elif kind == 'website' and config.get('official_browser'):
                from .official_browser import PublicRenderer
                from .catalog import lookup
                entry_row = lookup(source.get('url', ''))
                render_budget = min(3,pages) + 2*min(quota,pages) if entry_row and entry_row['id'] == 'minimax' else pages+3
                context = PublicRenderer(maximum=render_budget, should_continue=should_continue)
            else: context = nullcontext(None)
            with context as browser:
                if kind == 'website': renderer = browser
                if browser and kind in ('boss', 'liepin'):
                    def read(url, **kwargs):
                        if should_continue and not should_continue(): raise SourceError('cancelled', '扫描已停止；没有继续发起请求')
                        if budget.used - start >= request_quota or budget.used >= maximum:
                            raise SourceError('budget_exhausted', '浏览器页面请求预算已用完')
                        budget.used += 1
                        return browser.read(url)
                provider = route(source)
                if not provider: raise SourceError('not_configured', '未知岗位渠道：' + str(kind))
                if provider.id != kind:
                    source = provider.detect(source)
                    parts = urlsplit(str(source.get('careers_url') or source.get('url') or ''))
                    report['kind'] = provider.id
                    report['source_id'] = sid = source.get('id') or (
                        provider.id + (':' + parts.netloc + parts.path.rstrip('/') if parts.netloc else ''))
                generator = provider.fetch(source, Context(read, terms, quota, pages, report, renderer))
                for item in generator:
                    key = (item['channel'], item['platform_id'])
                    if key in seen: continue
                    # A provider that ignores ctx.limit must not eat the shares of later sources.
                    if sweep and report['returned'] >= quota:
                        report['truncated'] = True
                        break
                    seen.add(key)
                    item.setdefault('raw', {})['discovery'] = dict(source_id=sid, queries=terms, mode=report['mode'], checked_at=report['checked_at'])
                    if inline_checks:
                        from .entries import check_job
                        checking = clock()
                        try: check_job(item, entry_budget.get, renderer=renderer)
                        except SourceError as e:
                            # The fetched job is real; only its entry check was cut off by the deadline.
                            if e.status == 'cancelled' and timing['reached']:
                                jobs.append(item); report['returned'] += 1
                            raise
                        finally: entry['elapsed_seconds'] += clock() - checking
                        entry['checked'] += 1
                    jobs.append(item); report['returned'] += 1
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
        report['requests'] = budget.used - start
        report['entry_requests'] = entry_budget.used - entry_start
        report['rendered_pages'] = getattr(renderer, 'used', 0)
        report['elapsed_seconds'] = round(clock() - began, 2)

    for index, source in enumerate(sources):
        report = new_report(source)
        reports.append(report)
        remaining, before = len(sources) - index, len(jobs)
        # Reserve work for later sources, so one large board cannot starve all others.
        run_source(source, report, max(1, math.ceil((limit - len(jobs)) / remaining)),
                   max(1, math.ceil((maximum - budget.used) / remaining)), pages)
        for item in jobs[before:]: owners[id(item)] = report
        if on_source: on_source(dict(report))
    if sweep:
        # Shares that small sources left unused flow back to the ones cut off by their share or page cap.
        candidates = [(s, r) for s, r in zip(sources, reports) if r['status'] == 'ok' and r['truncated']]
        for index, (source, report) in enumerate(candidates):
            if len(jobs) >= limit or budget.used >= maximum or not should_continue(): break
            remaining, before = len(candidates) - index, len(jobs)
            again = dict(new_report(source), source_id=report['source_id'], returned=report['returned'])
            # Reruns from page 1; `seen` drops the replayed jobs, which still count towards ctx.limit.
            run_source(source, again, report['returned'] + math.ceil((limit - len(jobs)) / remaining),
                       math.ceil((maximum - budget.used) / remaining), pages)
            for item in jobs[before:]: owners[id(item)] = report
            report.update(again, passes=2, search_url=report['search_url'] or again['search_url'], checked_at=report['checked_at'],
                          **{k: report[k] + again[k] for k in SUMMED})
            report['elapsed_seconds'] = round(report['elapsed_seconds'], 2)
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


def main():
    import argparse
    from pathlib import Path
    parser = argparse.ArgumentParser(description='本地多渠道只读岗位搜索；不发送简历或申请')
    parser.add_argument('--source', action='append', choices=sorted(REGISTRY))
    parser.add_argument('--keyword', action='append', default=[])
    parser.add_argument('--browser-source', action='append', choices=['boss','liepin'], default=[])
    parser.add_argument('--headless', action='store_true')
    parser.add_argument('--browser', choices=('chromium', 'chrome'), default='chromium')
    parser.add_argument('--official-only', action='store_true', help='本轮只查公司招聘来源，跳过 BOSS、猎聘与网页索引')
    parser.add_argument('--catalog', action='append', help='内置公司 ID，可重复；all 表示全部')
    parser.add_argument('--official-browser', action='store_true', help='启用无登录资料的公开页面渲染，仅只读')
    parser.add_argument('--skip-entry-checks', action='store_true')
    parser.add_argument('--career-url', action='append', default=[], help='公司招聘页 HTTPS URL；可重复')
    parser.add_argument('--profile-root', type=Path)
    parser.add_argument('--data', type=Path, help='与工作台相同的数据目录')
    parser.add_argument('--max-jobs', type=int, default=12)
    parser.add_argument('--max-pages', type=int, default=2)
    parser.add_argument('--requests', type=int, default=30)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    config = dict(sources=list(dict.fromkeys((args.source or DEFAULT_KINDS) + args.browser_source)), keywords=args.keyword or ['AI','Agent','Web3'],
                  source_modes={kind:'browser' for kind in args.browser_source}, max_jobs=args.max_jobs,
                  max_pages=args.max_pages, discovery_requests=args.requests)
    config.update(official_only=args.official_only, browser_channel='chrome' if args.browser == 'chrome' else None)
    config.update(check_entries=not args.skip_entry_checks, official_browser=args.official_browser)
    if args.catalog:
        from .catalog import boards
        config['company_boards'] = boards(None if 'all' in args.catalog else args.catalog)
        if not config['company_boards']: parser.error('没有匹配的内置公司 ID')
        config['sources'] = ['website']
    if args.career_url:
        config['company_boards'] = config.get('company_boards',[]) + [dict(type='website', url=url) for url in args.career_url]
        config['sources'] = ['website']
    profile_root = args.profile_root or (args.data / 'browser-search' if args.data else None)
    result = discover(config, browser_profile_root=profile_root, browser_headless=args.headless)
    serialized = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized)
    print(json.dumps(dict(jobs=len(result['jobs']), queries=result['queries'], sources=result['sources']),ensure_ascii=False,indent=2))


if __name__ == '__main__': main()
