"""Xiaohongshu careers (job.xiaohongshu.com) public social-recruiting list."""
import json
import re
from urllib.parse import quote, urlsplit

from ..sources import SourceError, json_data, normalize
from . import Provider, record_detail_error, register
from ..search.query import matches

HOST = 'job.xiaohongshu.com'
ORIGIN = 'https://' + HOST
LIST = ORIGIN + '/social/position'
REFERER = ORIGIN + '/?type=social'
API = ORIGIN + '/websiterecruit/position/pageQueryPosition'
PAGE_SIZE = 100


def _int(value):
    return int(value) if isinstance(value, str) and re.fullmatch('[0-9]+', value) else value


def _page(raw):
    data = json_data(raw)
    body = data.get('data') if isinstance(data, dict) else None
    posts = body.get('list') if isinstance(body, dict) else None
    total = _int(body.get('total')) if isinstance(body, dict) else None
    total_page = _int(body.get('totalPage')) if isinstance(body, dict) else None
    if (not isinstance(posts, list) or
            any(not isinstance(n, int) or isinstance(n, bool) or n < 0 for n in (total, total_page))):
        raise SourceError('parse_error', '小红书招聘列表结构变化')
    return posts, total, total_page


def _row_id(row):
    ident = row.get('positionId') if isinstance(row, dict) else None
    if isinstance(ident, (str, int)) and not isinstance(ident, bool) and str(ident).strip():
        return str(ident)
    return None


def _job(row, company):
    ident = _row_id(row)
    if ident is None or not isinstance(row.get('positionName'), str):
        raise SourceError('parse_error', '小红书招聘岗位缺少稳定 ID 或名称')
    if any(row.get(key) is not None and not isinstance(row[key], str) for key in ('duty', 'qualification')):
        raise SourceError('parse_error', '小红书招聘岗位职责或要求格式变化')
    # Only the actual responsibilities and qualifications count as the posting body.
    jd = '\n'.join(row.get(key) or '' for key in ('duty', 'qualification')).strip()
    try:
        url = LIST + '/' + quote(ident, safe='')
    except UnicodeError as e:
        raise SourceError('parse_error', '小红书招聘岗位 ID 无法编码') from e
    return normalize('xiaohongshu', ident, row['positionName'], jd, url, company,
                     row.get('workplace') if isinstance(row.get('workplace'), str) else None,
                     published_at=row.get('publishTime') if isinstance(row.get('publishTime'), str) else None,
                     raw=dict(source_kind='xiaohongshu', record=row))


def detect(entry):
    for key in ('careers_url', 'url'):
        try: parts = urlsplit(entry.get(key) or '')
        except ValueError: continue
        if parts.scheme == 'https' and parts.hostname == HOST: return dict(entry, kind='xiaohongshu')
    return None


def fetch(entry, ctx):
    # This endpoint lists the whole board; keywords are matched locally in one paging pass.

    company = entry.get('company') or '小红书'
    seen, count = set(), 0
    if not ctx.report['search_url']: ctx.report['search_url'] = API
    for page in range(1, ctx.pages + 1):
        body = json.dumps(dict(pageNum=page, pageSize=PAGE_SIZE, recruitType='social')).encode('utf-8')
        posts, total, total_page = _page(ctx.read(API, method='POST', data=body, headers={
            'Content-Type': 'application/json', 'Referer': REFERER, 'Origin': ORIGIN}))
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
            if not matches(job['title'] + ' ' + job['jd'], ctx.terms) or ctx.keep and not ctx.keep(job):
                ctx.report['filtered'] = ctx.report.get('filtered', 0) + 1
                continue
            if count >= ctx.limit:
                ctx.report['truncated'] = True
                return
            count += 1
            yield job
        if not posts or page * PAGE_SIZE >= total or page >= total_page: return
        if page == ctx.pages: ctx.report['truncated'] = True


PROVIDER = register(Provider('xiaohongshu', fetch, detect))
