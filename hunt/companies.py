"""Company seed list: which employers a sweep scans, plus employers met while importing jobs."""
import functools
import json
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

DATA = Path(__file__).resolve().parent / 'data' / 'companies.cn.json'
# 按关键词（远端或本地）搜索整个多业务雇主的读取器优先，避免被标签排序挤出扫描范围。
KEYWORD_PROVIDERS = ('tencent', 'alibaba', 'meituan', 'feishu', 'xiaohongshu', 'didi', 'jd', 'netease')
MAX_ENCOUNTERED = 2000
KEY = 'encountered_companies'
# Job platforms and ATS hosts list other companies' jobs (or need a tenant path), and the keyword providers
# are seeded already: none of their origins is a careers page worth remembering. Subdomains match too.
BLOCKED_HOSTS = ('zhipin.com', 'liepin.com', 'lagou.com', 'zhaopin.com', '51job.com', 'linkedin.com', 'indeed.com', 'maimai.cn',
                 'nowcoder.com', 'myworkdayjobs.com', 'smartrecruiters.com', 'greenhouse.io', 'lever.co', 'ashbyhq.com',
                 'mokahr.com', 'workable.com', 'jobs.feishu.cn', 'careers.tencent.com', 'talent.alibaba.com',
                 'zhaopin.meituan.com', 'jobs.bytedance.com')
AGGREGATOR_CHANNELS = ('boss', 'liepin', 'websearch', 'import')
FLAGGED = ('dead', 'needs_adapter')


@functools.lru_cache(maxsize=4)
def _read(path):
    return tuple(json.loads(path.read_text(encoding='utf-8'))['companies'])


def load_seeds():
    return list(_read(DATA))


def _split(url):
    try: parts = urlsplit(url or '')
    except ValueError: return None
    return parts if parts.scheme in ('http', 'https') and parts.hostname else None


def _key(url):
    parts = _split(url)
    return (parts.hostname.lower(), parts.path.rstrip('/')) if parts else None


def _overlap(terms, seed):
    tags = [t.lower() for t in seed.get('tags', []) if len(t) > 1]
    return sum(any(t in tag or tag in t for tag in tags) for t in (x.lower() for x in terms if x.strip()))


def _entry(seed, tier=1):
    # broad: a big multi-business platform whose remote keyword search returns loose matches, so a sweep re-checks them
    # locally; a single company's own board (every role there is the company's) is taken as the search returns it.
    common = dict(id=seed['id'], company=seed['name'], tier=tier, broad='大厂' in seed.get('tags', ()))
    provider = seed.get('provider')
    if provider: return dict(common, kind=provider, careers_url=seed['careers_url'])
    return dict(common, kind='website', url=seed['careers_url'])


def select(terms, limit, extra=(), seeds=None, include_flagged=False, families=()):
    """discovery_sources entries: keyword-search providers first, then family/tag overlap, then `extra`.

    Seeds whose `status` is `dead` or `needs_adapter` are skipped unless include_flagged is set."""
    seeds = load_seeds() if seeds is None else seeds
    if not include_flagged: seeds = [s for s in seeds if s.get('status') not in FLAGGED]
    keyword = [s for s in seeds if s.get('provider') in KEYWORD_PROVIDERS]
    families = set(families)
    def score(s): return len(families.intersection(s.get('tags', ()))), _overlap(terms, s)
    rest = sorted((s for s in seeds if s.get('provider') not in KEYWORD_PROVIDERS), key=lambda s: tuple(-x for x in score(s)))
    # Tier tells a sweep what the search is about: 0 keyword search on a big platform (it hires in every direction) or on a
    # matching tenant, 1 tags match the direction or terms, 2 unrelated seeds and tenants, 3 employers met while importing.
    # Tiers 0-1 get both sweep passes before the rest starts.
    ranked = ([(s, 0 if '大厂' in s.get('tags', ()) or any(score(s)) else 2) for s in keyword]
              + [(s, 1 if any(score(s)) else 2) for s in rest] + [(s, 3) for s in extra])
    chosen, seen = [], set()
    for seed, tier in ranked:
        key = _key(seed.get('careers_url'))
        if key is None or key in seen: continue
        seen.add(key)
        chosen.append(_entry(seed, tier))
        if len(chosen) >= limit: break
    return chosen


def encountered(conn):
    row = conn.execute('SELECT value FROM meta WHERE key=?', (KEY,)).fetchone()
    return json.loads(row[0]) if row else []


def remember(conn, job):
    """Record the employer of an imported job when it is not yet a seed; True if newly added."""
    from .providers import route
    company = str(job.get('company') or '').strip()
    parts = _split(job.get('url'))
    channel = str(job.get('channel') or '')
    if not company or company == '待确认' or not parts or channel in AGGREGATOR_CHANNELS or channel.startswith('inbox'): return False
    host = parts.hostname.lower()
    if any(host == h or host.endswith('.' + h) for h in BLOCKED_HOSTS): return False
    seeds, old = load_seeds(), encountered(conn)
    if len(old) >= MAX_ENCOUNTERED: return False
    if any(c['name'].casefold() == company.casefold() or _split(c['careers_url']).hostname.lower() == host for c in seeds + old): return False
    url = urlunsplit((parts.scheme.lower(), parts.netloc.lower(), '/', '', ''))
    provider = route(dict(careers_url=url))
    row = dict(id='enc-' + re.sub(r'[^a-z0-9]+', '-', host).strip('-'), name=company[:200], careers_url=url,
               provider=provider.id if provider else None, tags=[], source='encountered')
    conn.execute('INSERT OR REPLACE INTO meta VALUES(?,?)', (KEY, json.dumps(old + [row], ensure_ascii=False)))
    return True
