"""Alibaba Group careers (talent.alibaba.com) public JSON API.

Ported from career-ops providers/alibaba.mjs (https://github.com/career-ops-hq/career-ops,
commit f4d7477c8d25f81e6e4a952b724378913ea8c86e, MIT License).
"""
import json
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlsplit

from ..sources import SourceError, json_data, normalize
from . import Provider, paged_jobs, register

HOST = 'talent.alibaba.com'
API = 'https://' + HOST + '/position/search'
DETAIL = 'https://' + HOST + '/off-campus/position-detail?positionId='
PAGE_SIZE = 100
# Upstream paces every request after the first; a whole-board pull is 40+ requests.
PAUSE = 0.3
CST = timezone(timedelta(hours=8))


def _body(key, page):
    return json.dumps(dict(channel='group_official_site', language='zh', batchId='', categories='', deptCodes=[],
                           key=key, pageIndex=page, pageSize=PAGE_SIZE, regions='', subCategories=''),
                      ensure_ascii=False).encode('utf-8')


def _headers(token):
    # The endpoint accepts any XSRF-TOKEN cookie that equals the x-xsrf-token header (no session).
    return {'Content-Type': 'application/json', 'x-xsrf-token': token, 'Cookie': 'XSRF-TOKEN=' + token}


def _int(value):
    return int(value) if isinstance(value, str) and re.fullmatch('[0-9]+', value) else value


def _page(raw):
    data = json_data(raw)
    if isinstance(data, dict) and data.get('success') is False:
        # The API reports failures in-band with HTTP 200; a dead board must not read as an empty one.
        raise SourceError('fetch_error', '阿里招聘接口返回错误：' + str(data.get('errorMsg') or data.get('errorCode') or 'success=false'))
    body = data.get('content') if isinstance(data, dict) else None
    posts = body.get('datas') if isinstance(body, dict) else None
    total = _int(body.get('totalCount')) if isinstance(body, dict) else None
    if not isinstance(posts, list) or not isinstance(total, int) or isinstance(total, bool):
        raise SourceError('parse_error', '阿里招聘列表结构变化')
    return posts, total


def _posted(row):
    for key in ('publishTime', 'modifyTime'):
        value = row.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            try: return datetime.fromtimestamp(value / 1000, CST).date().isoformat()
            except (OverflowError, OSError, ValueError): continue
    return None


def _experience(exp):
    if not isinstance(exp, dict): return ''
    number = lambda v: v if isinstance(v, (int, float)) and not isinstance(v, bool) else None
    low, high = number(exp.get('from')), number(exp.get('to'))
    if low is not None and high is not None: return '%s-%s年' % (low, high)
    if low is not None: return '%s年以上' % low
    if high is not None: return '%s年以下' % high
    return ''


def _job(row, company):
    if not isinstance(row, dict) or row.get('id') in (None, '') or not row.get('name'):
        raise SourceError('parse_error', '阿里招聘岗位缺少稳定 ID 或名称')
    ident = str(row['id'])
    # The API's own positionUrl embeds a per-request track_id, so the detail URL is built from the id.
    try: url = DETAIL + quote(ident, safe='')
    except UnicodeError as e: raise SourceError('parse_error', '阿里招聘岗位 ID 无法编码') from e
    categories = row.get('categories')
    locations = row.get('workLocations')
    experience = _experience(row.get('experience'))
    jd = '\n'.join(str(part) for part in (
        isinstance(categories, list) and any(categories) and '类别: ' + '/'.join(str(c) for c in categories if c),
        experience and '经验: ' + experience,
        row.get('description'), row.get('requirement')) if part)
    location = '/'.join(str(x) for x in locations if x) if isinstance(locations, list) else None
    return normalize('alibaba', ident, row['name'], jd, url, company, location, status='open',
                     published_at=_posted(row), raw=dict(source_kind='alibaba', record=row))


def detect(entry):
    for key in ('careers_url', 'url'):
        try: parts = urlsplit(entry.get(key) or '')
        except ValueError: continue
        if parts.scheme == 'https' and parts.hostname == HOST: return dict(entry, kind='alibaba')
    return None


def _row_id(row):
    return str(row['id']) if isinstance(row, dict) and row.get('id') not in (None, '') else None


def fetch(entry, ctx):
    company, token, first = entry.get('company') or '阿里巴巴', str(uuid.uuid4()), True

    def fetch_page(term, page):
        nonlocal first
        if not ctx.report['search_url']: ctx.report['search_url'] = API
        if not first and PAUSE: time.sleep(PAUSE)
        first = False
        return _page(ctx.read(API, method='POST', data=_body(term, page), headers=_headers(token)))
    return paged_jobs(ctx, fetch_page, lambda row: _job(row, company), _row_id, PAGE_SIZE)


PROVIDER = register(Provider('alibaba', fetch, detect))
