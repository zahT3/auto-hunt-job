"""Feishu Jobs (飞书招聘) public JSON API: ByteDance's own site and *.jobs.feishu.cn tenants.

Ported from career-ops providers/feishu-jobs.mjs (https://github.com/career-ops-hq/career-ops,
commit f4d7477c8d25f81e6e4a952b724378913ea8c86e, MIT License). Pages are requested one after
another; the upstream's concurrent paging is not ported.
"""
import json
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlsplit

from ..sources import SourceError, json_data, normalize
from . import Provider, paged_jobs, register

BYTEDANCE = 'jobs.bytedance.com'
TENANT = re.compile(r'[a-z0-9-]+\.jobs\.feishu\.cn')
PAGE_SIZE = 100
# Upstream paces every request after the first.
PAUSE = 0.3
# jobs.bytedance.com rejects a Windows Chrome UA (405) but accepts this macOS one; verbatim from
# career-ops user-agent.mjs MACOS_BROWSER_LIKE_USER_AGENT.
USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'
CST = timezone(timedelta(hours=8))


def _origin(value):
    try: parts = urlsplit(value) if isinstance(value, str) else None
    except ValueError: return None
    host = parts and parts.hostname
    if parts and parts.scheme == 'https' and host and (host == BYTEDANCE or TENANT.fullmatch(host)):
        return 'https://' + host
    return None


def _entry_origin(entry):
    for key in ('careers_url', 'url'):
        origin = _origin(entry.get(key))
        if origin: return origin
    return None


def _body(keyword, page):
    body = dict(limit=PAGE_SIZE, offset=(page - 1) * PAGE_SIZE)
    if keyword: body['keyword'] = keyword
    return json.dumps(body, ensure_ascii=False).encode('utf-8')


def _page(raw):
    data = json_data(raw)
    code = data.get('code') if isinstance(data, dict) else None
    if isinstance(data, dict) and code not in (0, None):
        raise SourceError('fetch_error', '飞书招聘接口返回错误：code=%s %s' % (code, data.get('message') or ''))
    body = data.get('data') if isinstance(data, dict) else None
    posts = body.get('job_post_list') if isinstance(body, dict) else None
    total = body.get('count') if isinstance(body, dict) else None
    if isinstance(total, str) and re.fullmatch('[0-9]+', total): total = int(total)
    if code != 0 or not isinstance(posts, list) or not isinstance(total, int) or isinstance(total, bool):
        raise SourceError('parse_error', '飞书招聘列表结构变化')
    return posts, total


def _posted(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
        # Upstream does not state the unit; values under 1e12 are read as epoch seconds.
        try: return datetime.fromtimestamp(value / 1000 if value > 1e12 else value, CST).date().isoformat()
        except (OverflowError, OSError, ValueError): return None
    return None


def _name(item):
    return str(item['name']) if isinstance(item, dict) and item.get('name') else ''


def _job(row, origin, company):
    if not isinstance(row, dict) or row.get('id') in (None, '') or not row.get('title'):
        raise SourceError('parse_error', '飞书招聘岗位缺少稳定 ID 或名称')
    ident = str(row['id'])
    try: encoded = quote(ident, safe='')
    except UnicodeError as e: raise SourceError('parse_error', '飞书招聘岗位 ID 无法编码') from e
    path = '/experienced/position/' if origin == 'https://' + BYTEDANCE else '/index/position/'
    cities = row.get('city_list')
    category, recruit = _name(row.get('job_category')), _name(row.get('recruit_type'))
    jd = '\n'.join(str(part) for part in (
        category and '类别: ' + category, recruit and '类型: ' + recruit,
        row.get('description'), row.get('requirement')) if part)
    location = '/'.join(n for n in map(_name, cities) if n) if isinstance(cities, list) else ''
    return normalize('feishu', ident, row['title'], jd, origin + path + encoded + '/detail', company, location or None,
                     status='open', published_at=_posted(row.get('publish_time')), raw=dict(source_kind='feishu', record=row))


def _row_id(row):
    return str(row['id']) if isinstance(row, dict) and row.get('id') not in (None, '') else None


def detect(entry):
    return dict(entry, kind='feishu') if _entry_origin(entry) else None


def fetch(entry, ctx):
    # An explicit kind skips detect(), so the host check is repeated here; no URL at all means ByteDance's own site.
    origin = _entry_origin(entry) if (entry.get('careers_url') or entry.get('url')) else 'https://' + BYTEDANCE
    if not origin: raise SourceError('not_configured', '飞书招聘来源需要 jobs.bytedance.com 或 *.jobs.feishu.cn 的 HTTPS 链接')
    api, first = origin + '/api/v1/search/job/posts', True
    company = entry.get('company') or ('字节跳动' if origin == 'https://' + BYTEDANCE else urlsplit(origin).hostname)
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json', 'User-Agent': USER_AGENT, 'Referer': origin + '/'}

    def fetch_page(term, page):
        nonlocal first
        if not ctx.report['search_url']: ctx.report['search_url'] = api
        if not first and PAUSE: time.sleep(PAUSE)
        first = False
        return _page(ctx.read(api, method='POST', data=_body(term, page), headers=headers))
    return paged_jobs(ctx, fetch_page, lambda row: _job(row, origin, company), _row_id, PAGE_SIZE)


PROVIDER = register(Provider('feishu', fetch, detect))
