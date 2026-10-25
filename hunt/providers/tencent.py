"""Tencent careers (careers.tencent.com) public JSON API.

Ported from career-ops providers/tencent.mjs (https://github.com/career-ops-hq/career-ops,
commit f4d7477c8d25f81e6e4a952b724378913ea8c86e, MIT License).
"""
import re
import time
from datetime import date
from urllib.parse import urlencode, urlsplit

from ..sources import SourceError, json_data, normalize
from . import Provider, paged_jobs, register

HOST = 'careers.tencent.com'
PAGE_SIZE = 100


def _url(keyword, page):
    # `timestamp` is part of the upstream request shape (cache buster).
    query = dict(timestamp=int(time.time() * 1000), keyword=keyword, pageIndex=page, pageSize=PAGE_SIZE, language='zh-cn')
    return 'https://' + HOST + '/tencentcareer/api/post/Query?' + urlencode(query)


def _posted(value):
    m = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', str(value or ''))
    try: return date(*map(int, m.groups())).isoformat() if m else None
    except ValueError: return None


def _page(raw):
    data = json_data(raw)
    body = data.get('Data') if isinstance(data, dict) else None
    posts = body.get('Posts') if isinstance(body, dict) else None
    total = body.get('Count') if isinstance(body, dict) else None
    if isinstance(total, str) and re.fullmatch('[0-9]+', total): total = int(total)
    if not isinstance(posts, list) or not isinstance(total, int) or isinstance(total, bool):
        raise SourceError('parse_error', '腾讯招聘列表结构变化')
    return posts, total


def _job(row, company):
    if not isinstance(row, dict) or not row.get('PostId') or not row.get('RecruitPostName'):
        raise SourceError('parse_error', '腾讯招聘岗位缺少稳定 ID 或名称')
    ident = str(row['PostId'])
    # The list carries only 职责 (no 要求 field, verified 2026-10); no detail request is made, as upstream.
    jd = '\n'.join(str(part) for part in (
        row.get('BGName') and 'BG: ' + str(row['BGName']),
        row.get('CategoryName') and '类别: ' + str(row['CategoryName']),
        row.get('RequireWorkYearsName') and '经验: ' + str(row['RequireWorkYearsName']),
        row.get('Responsibility') and '岗位职责:\n' + str(row['Responsibility'])) if part)
    location = '-'.join(str(row[k]) for k in ('CountryName', 'LocationName') if row.get(k))
    return normalize('tencent', ident, row['RecruitPostName'], jd, 'https://' + HOST + '/jobdesc.html?postId=' + ident,
                     company, location, status='open', published_at=_posted(row.get('LastUpdateTime')),
                     raw=dict(source_kind='tencent', record=row))


def detect(entry):
    for key in ('careers_url', 'url'):
        try: parts = urlsplit(entry.get(key) or '')
        except ValueError: continue
        if parts.scheme == 'https' and parts.hostname == HOST: return dict(entry, kind='tencent')
    return None


def _row_id(row):
    return str(row['PostId']) if isinstance(row, dict) and row.get('PostId') else None


def fetch(entry, ctx):
    company = entry.get('company') or '腾讯'

    def fetch_page(term, page):
        url = _url(term, page)
        if not ctx.report['search_url']: ctx.report['search_url'] = url
        return _page(ctx.read(url))
    return paged_jobs(ctx, fetch_page, lambda row: _job(row, company), _row_id, PAGE_SIZE)


PROVIDER = register(Provider('tencent', fetch, detect))
