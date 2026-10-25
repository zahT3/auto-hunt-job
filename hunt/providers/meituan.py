"""Meituan careers (zhaopin.meituan.com) public JSON API.

Ported from career-ops providers/meituan.mjs (https://github.com/career-ops-hq/career-ops,
commit f4d7477c8d25f81e6e4a952b724378913ea8c86e, MIT License).
"""
import json
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlsplit

from ..sources import SourceError, json_data, normalize
from . import Provider, paged_jobs, register

HOST = 'zhaopin.meituan.com'
API = 'https://' + HOST + '/api/official/job/getJobList'
DETAIL = 'https://' + HOST + '/web/position/detail?jobUnionId='
PAGE_SIZE = 100
# Upstream paces every request after the first; this board rate-limits harder than most.
PAUSE = 0.4
# The board sporadically answers a mid-pagination request with an empty list (reads as
# rate-limiting), so an empty page is retried with backoff before it counts as the end.
EMPTY_RETRIES = 2
BACKOFF = 1.5
CST = timezone(timedelta(hours=8))


def _body(keyword, page):
    # The pagination object must be nested: a flat pageNo is ignored and page 1 is returned every time.
    return json.dumps(dict(page=dict(pageNo=page, pageSize=PAGE_SIZE), keywords=keyword, jobShareType='1',
                           jobType=[dict(code='3', subCode=[])], cityList=[], department=[], jfJgList=[],
                           typeCode=[], specialCode=[]), ensure_ascii=False).encode('utf-8')


def _page(raw):
    data = json_data(raw)
    body = data.get('data') if isinstance(data, dict) else None
    posts = body.get('list') if isinstance(body, dict) else None
    paging = body.get('page') if isinstance(body, dict) else None
    total = paging.get('totalCount') if isinstance(paging, dict) else None
    if isinstance(total, str) and re.fullmatch('[0-9]+', total): total = int(total)
    if not isinstance(posts, list) or not isinstance(total, int) or isinstance(total, bool):
        raise SourceError('parse_error', '美团招聘列表结构变化')
    return posts, total


def _posted(row):
    for key in ('refreshTime', 'firstPostTime'):
        value = row.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            # Upstream: values under 1e12 are epoch seconds.
            try: return datetime.fromtimestamp(value / 1000 if value > 1e12 else value, CST).date().isoformat()
            except (OverflowError, OSError, ValueError): continue
        if isinstance(value, str):
            m = re.match(r'\s*(\d{4})-(\d{2})-(\d{2})', value)
            if m: return '-'.join(m.groups())
    return None


def _names(items):
    if not isinstance(items, list): return ''
    return '/'.join(str(x.get('name') if isinstance(x, dict) else x) for x in items
                    if (x.get('name') if isinstance(x, dict) else x))


def _job(row, company):
    if not isinstance(row, dict) or row.get('jobUnionId') in (None, '') or not row.get('name'):
        raise SourceError('parse_error', '美团招聘岗位缺少稳定 ID 或名称')
    ident = str(row['jobUnionId'])
    try: url = DETAIL + quote(ident, safe='')
    except UnicodeError as e: raise SourceError('parse_error', '美团招聘岗位 ID 无法编码') from e
    department = _names(row.get('department'))
    jd = '\n'.join(str(part) for part in (
        department and '部门: ' + department,
        row.get('jobFamily') and '序列: ' + str(row['jobFamily']),
        row.get('workYear') and '经验: ' + str(row['workYear']),
        row.get('jobDuty'), row.get('jobRequirement')) if part)
    return normalize('meituan', ident, row['name'], jd, url, company, _names(row.get('cityList')) or None, status='open',
                     published_at=_posted(row), raw=dict(source_kind='meituan', record=row))


def _row_id(row):
    return str(row['jobUnionId']) if isinstance(row, dict) and row.get('jobUnionId') not in (None, '') else None


def detect(entry):
    for key in ('careers_url', 'url'):
        try: parts = urlsplit(entry.get(key) or '')
        except ValueError: continue
        if parts.scheme == 'https' and parts.hostname == HOST: return dict(entry, kind='meituan')
    return None


def fetch(entry, ctx):
    company, first, known = entry.get('company') or '美团', True, {}

    def fetch_page(term, page):
        nonlocal first
        if not ctx.report['search_url']: ctx.report['search_url'] = API
        for attempt in range(EMPTY_RETRIES + 1):
            delay = BACKOFF * attempt if attempt else PAUSE
            if not first and delay: time.sleep(delay)
            first = False
            posts, total = _page(ctx.read(API, method='POST', data=_body(term, page), headers={'Content-Type': 'application/json'}))
            # An empty answer may also carry totalCount 0, so the last positive total for this keyword stands.
            total = known[term] = total or known.get(term, 0)
            if posts or (total and (page - 1) * PAGE_SIZE >= total): return posts, total
        if total:
            # Silently stopping here would pass a rate-limited board off as a short one.
            raise SourceError('fetch_error', '美团招聘第 %d 页重试 %d 次仍为空（共 %d 条）' % (page, EMPTY_RETRIES, total))
        return posts, total
    return paged_jobs(ctx, fetch_page, lambda row: _job(row, company), _row_id, PAGE_SIZE)


PROVIDER = register(Provider('meituan', fetch, detect))
