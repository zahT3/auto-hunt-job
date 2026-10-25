"""Company seed list: which employers a sweep scans, plus employers met while importing jobs."""
import functools
import json
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

DATA = Path(__file__).resolve().parent / 'data' / 'companies.cn.json'
KEYWORD_PROVIDERS = ('tencent', 'alibaba', 'meituan', 'feishu')
MAX_ENCOUNTERED = 2000
KEY = 'encountered_companies'
# Job platforms and ATS hosts list other companies' jobs (or need a tenant path), and the keyword providers
# are seeded already: none of their origins is a careers page worth remembering. Subdomains match too.
BLOCKED_HOSTS = ('zhipin.com', 'liepin.com', 'lagou.com', 'zhaopin.com', '51job.com', 'linkedin.com', 'indeed.com', 'maimai.cn',
                 'nowcoder.com', 'myworkdayjobs.com', 'smartrecruiters.com', 'greenhouse.io', 'lever.co', 'ashbyhq.com',
                 'mokahr.com', 'workable.com', 'jobs.feishu.cn', 'careers.tencent.com', 'talent.alibaba.com',
                 'zhaopin.meituan.com', 'jobs.bytedance.com')
AGGREGATOR_CHANNELS = ('boss', 'liepin', 'websearch', 'import')


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


def _entry(seed):
    provider = seed.get('provider')
    if provider: return dict(id=seed['id'], kind=provider, careers_url=seed['careers_url'], company=seed['name'])
    return dict(id=seed['id'], kind='website', url=seed['careers_url'], company=seed['name'])


def select(terms, limit, extra=(), seeds=None):
    """discovery_sources entries: keyword-search providers first, then seeds by tag overlap, then `extra`."""
    seeds = load_seeds() if seeds is None else seeds
    keyword = [s for s in seeds if s.get('provider') in KEYWORD_PROVIDERS]
    rest = sorted((s for s in seeds if s.get('provider') not in KEYWORD_PROVIDERS), key=lambda s: -_overlap(terms, s))
    chosen, seen = [], set()
    for seed in keyword + rest + list(extra):
        key = _key(seed.get('careers_url'))
        if key is None or key in seen: continue
        seen.add(key)
        chosen.append(_entry(seed))
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
