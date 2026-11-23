"""携程官网社招列表。岗位详情页以 fromId 标识职位。"""
import json
import re
import time
from datetime import date
from urllib.parse import urlsplit

from ..parse import SourceError, json_data, normalize
from . import Provider, paged_jobs, register

HOST = 'job.ctrip.com'
API = 'https://' + HOST + '/api/hrrecruit/getJobAd'
DETAIL = 'https://' + HOST + '/#/experienced/job-detail/'
PAGE_SIZE = 20
PAUSE = 0.4


def _page(raw):
    data = json_data(raw)
    if not isinstance(data, dict) or 'retCode' not in data:
        raise SourceError('parse_error', '携程招聘响应结构变化')
    if data['retCode'] != '201':
        raise SourceError('fetch_error', '携程招聘列表请求未成功')
    body = data.get('retValue')
    rows = body.get('recruitJobAdList') if isinstance(body, dict) else None
    total = body.get('total') if isinstance(body, dict) else None
    if not isinstance(rows, list) or type(total) is not int or total < 0:
        raise SourceError('parse_error', '携程招聘列表结构变化')
    return rows, total


def _row_id(row):
    ident = row.get('fromId') if isinstance(row, dict) else None
    return ident if isinstance(ident, str) and re.fullmatch('[A-Za-z0-9_-]+', ident) else None


def _job(row, company):
    ident = _row_id(row)
    if not ident or not isinstance(row.get('jobTitle'), str):
        raise SourceError('parse_error', '携程招聘岗位缺少详情页编号或名称')
    fields = ('duty', 'requirements', 'cityName')
    if any(row.get(k) is not None and not isinstance(row[k], str) for k in fields):
        raise SourceError('parse_error', '携程招聘岗位正文或地点结构变化')
    jd = '\n'.join(row[k] for k in ('duty', 'requirements') if row.get(k))
    try:
        posted = date.fromisoformat(row.get('publishDate') or '').isoformat()
    except (TypeError, ValueError):
        posted = None
    # The list contains staff names and internal HR identifiers. Keep only the normalized job fields.
    return normalize('ctrip', ident, row['jobTitle'], jd, DETAIL + ident, company, row.get('cityName'),
                     published_at=posted, status='open')


def detect(entry):
    for key in ('careers_url', 'url'):
        value = entry.get(key)
        if not isinstance(value, str): continue
        try: parts = urlsplit(value)
        except ValueError: continue
        if parts.scheme == 'https' and parts.hostname in (HOST, 'careers.ctrip.com'):
            return dict(entry, kind='ctrip')
    return None


def fetch(entry, ctx):
    ctx.report['search_url'] = API
    first = True

    def fetch_page(term, page):
        nonlocal first
        if not first: time.sleep(PAUSE)
        first = False
        condition = dict(keyword=term, category=1, fromId=[], kind=[], country=[], city=[], bucode=[],
                         jobFamilyCode=[], jobFamilyGroupCode=[])
        body = dict(condition=condition, pager=dict(index=str(page), size=str(PAGE_SIZE)))
        raw = ctx.read(API, method='POST', data=json.dumps(body, ensure_ascii=False).encode(),
                       headers={'Content-Type': 'application/json'})
        return _page(raw)

    return paged_jobs(ctx, fetch_page, lambda row: _job(row, entry.get('company') or '携程'), _row_id, PAGE_SIZE)


PROVIDER = register(Provider('ctrip', fetch, detect))
