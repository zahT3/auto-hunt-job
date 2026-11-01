"""DiDi careers public list API; filtering is local to one board traversal."""
from datetime import date
from urllib.parse import urlencode, urlsplit

from ..parse import SourceError, json_data, normalize, plain
from . import Provider, record_detail_error, register
from ..query import matches

HOST = 'talent.didiglobal.com'
API = 'https://' + HOST + '/recruit-portal-service/api/job/front/list'
SOCIAL = 'https://' + HOST + '/social'
PAGE_SIZE = 100


def _url(page):
    return API + '?' + urlencode(dict(page=page, size=PAGE_SIZE))


def _page(raw):
    data = json_data(raw)
    body = data.get('data') if isinstance(data, dict) else None
    posts = body.get('items') if isinstance(body, dict) else None
    total = body.get('total') if isinstance(body, dict) else None
    if isinstance(total, str) and total.isascii() and total.isdigit(): total = int(total)
    if not isinstance(posts, list) or not isinstance(total, int) or isinstance(total, bool) or total < 0:
        raise SourceError('parse_error', '滴滴招聘列表结构变化')
    return posts, total


def _row_id(row):
    value = row.get('jdId') if isinstance(row, dict) else None
    if isinstance(value, bool) or not isinstance(value, (str, int)): return None
    return str(value) if str(value).strip() else None


def _posted(value):
    if not isinstance(value, str): return None
    try: return date.fromisoformat(value[:10]).isoformat()
    except ValueError: return None


def _job(row, company):
    ident = _row_id(row)
    if not ident or not isinstance(row.get('jobName'), str) or not plain(row['jobName']):
        raise SourceError('parse_error', '滴滴招聘岗位缺少稳定 ID 或名称')
    sections = []
    for key, label in (('jobDuty', '岗位职责'), ('jobQualification', '任职要求')):
        value = row.get(key)
        if value is not None and not isinstance(value, str):
            raise SourceError('parse_error', '滴滴招聘岗位正文格式变化')
        if value and plain(value): sections.append(label + ':\n' + value)
    if not sections:
        raise SourceError('parse_error', '滴滴招聘岗位缺少职责与要求正文')
    metadata = [label + ': ' + str(row[key]) for key, label in
                (('jobTypeName', '类别'), ('deptName', '部门')) if row.get(key)]
    jd = '\n'.join(metadata + sections)
    try: url = SOCIAL + '/jobDetail?' + urlencode(dict(jdId=ident))
    except UnicodeError as e: raise SourceError('parse_error', '滴滴招聘岗位 ID 无法编码') from e
    return normalize('didi', ident, row['jobName'], jd, url, company, row.get('workArea'), status='open',
                     published_at=_posted(row.get('refreshTime')), raw=dict(source_kind='didi', record=row))


def detect(entry):
    for key in ('careers_url', 'url'):
        value = entry.get(key)
        if not isinstance(value, str): continue
        try: parts = urlsplit(value)
        except ValueError: continue
        if parts.scheme == 'https' and parts.hostname == HOST: return dict(entry, kind='didi')
    return None


def fetch(entry, ctx):
    # discovery imports providers during startup, so this dependency must remain lazy.

    company = entry.get('company') or '滴滴'
    seen, count = set(), 0
    for page in range(1, ctx.pages + 1):
        url = _url(page)
        if not ctx.report['search_url']: ctx.report['search_url'] = url
        posts, total = _page(ctx.read(url, method='GET', headers={'Referer': SOCIAL, 'Origin': 'https://' + HOST}))
        ctx.report['pages'] += 1
        ctx.report['fetched'] += len(posts)
        for row in posts:
            try: job = _job(row, company)
            except SourceError as e:
                if e.status != 'parse_error': raise
                record_detail_error(ctx.report, _row_id(row), e)
                continue
            ident = job['platform_id']
            if ident in seen: continue
            seen.add(ident)
            if not matches(job['title'] + ' ' + job['jd'], ctx.terms): continue
            if ctx.keep and not ctx.keep(job):
                ctx.report['filtered'] = ctx.report.get('filtered', 0) + 1
                continue
            if count >= ctx.limit:
                ctx.report['truncated'] = True
                return
            count += 1
            yield job
        if not posts or page * PAGE_SIZE >= total: return
        if page == ctx.pages: ctx.report['truncated'] = True


PROVIDER = register(Provider('didi', fetch, detect))
