"""miHoYo careers (jobs.mihoyo.com) public job API, served by ats.openout.mihoyo.com.

The site's own front end calls this ATS without login for social recruitment (hireType 0). The list has no keyword
filter (measured 2026-11-15: keyword/keywords/title/searchKey all return the full board) and no job text, so the
board is paged once, filtered locally on title and category, and /v1/job/info is read only for the jobs that match.
"""
import json
import re
import time
from urllib.parse import quote, urlsplit

from ..parse import SourceError, json_data, normalize, plain
from ..query import matches
from . import Provider, record_detail_error, register

HOST = 'jobs.mihoyo.com'
API = 'https://ats.openout.mihoyo.com/ats-portal'
LIST_URL = API + '/v1/job/list'
INFO_URL = API + '/v1/job/info'
DETAIL = 'https://' + HOST + '/position/'
PAGE_SIZE = 100
# One request per second at most, the rate the task's probing rules allow.
PAUSE = 1.0
HEADERS = {'Content-Type': 'application/json', 'Accept': 'application/json', 'Referer': 'https://' + HOST + '/'}


def _body(**fields):
    return json.dumps(dict(fields, channelDetailIds=[1], hireType=0), ensure_ascii=False).encode('utf-8')


def _envelope(raw, what):
    data = json_data(raw)
    if not isinstance(data, dict) or 'code' not in data:
        raise SourceError('parse_error', '米哈游招聘%s结构变化' % what)
    if data.get('code') != 0:
        raise SourceError('fetch_error', '米哈游招聘接口返回错误：code=%s %s' % (data.get('code'), data.get('message') or ''))
    body = data.get('data')
    if not isinstance(body, dict): raise SourceError('parse_error', '米哈游招聘%s结构变化' % what)
    return body


def _page(raw):
    body = _envelope(raw, '列表')
    rows, total = body.get('list'), body.get('total')
    if isinstance(total, str) and re.fullmatch('[0-9]+', total): total = int(total)
    if not isinstance(rows, list) or not isinstance(total, int) or isinstance(total, bool) or total < 0:
        raise SourceError('parse_error', '米哈游招聘列表结构变化')
    return rows, total


def _row_id(row):
    value = row.get('id') if isinstance(row, dict) else None
    if isinstance(value, bool) or not isinstance(value, (str, int)): return None
    return str(value) if str(value).strip() else None


def _job(row, info, company):
    ident = _row_id(row)
    if not ident or not isinstance(row.get('title'), str) or not plain(row['title']):
        raise SourceError('parse_error', '米哈游招聘岗位缺少稳定 ID 或名称')
    sections = []
    for key, label in (('description', '岗位职责'), ('jobRequire', '任职要求'), ('addition', '加分项')):
        value = info.get(key)
        if value is not None and not isinstance(value, str):
            raise SourceError('parse_error', '米哈游招聘岗位正文格式变化')
        if value and plain(value): sections.append(label + ':\n' + value)
    if not sections: raise SourceError('parse_error', '米哈游招聘岗位缺少职责与要求正文')
    meta = [label + ': ' + str(row[key]) for key, label in (('competencyType', '类别'), ('jobNature', '类型'), ('projectName', '项目')) if row.get(key)]
    places = row.get('addressDetailList')
    location = '/'.join(str(p['addressDetail']) for p in places if isinstance(p, dict) and p.get('addressDetail')) if isinstance(places, list) else None
    return normalize('mihoyo', ident, row['title'], '\n'.join(meta + sections), DETAIL + quote(ident, safe=''), company,
                     location or None, status='open', raw=dict(source_kind='mihoyo', record=dict(row, detail=info)))


def detect(entry):
    for key in ('careers_url', 'url'):
        try: parts = urlsplit(entry.get(key) or '')
        except ValueError: continue
        if parts.scheme == 'https' and parts.hostname == HOST: return dict(entry, kind='mihoyo')
    return None


def fetch(entry, ctx):
    company, first = entry.get('company') or '米哈游', True

    def read(url, body):
        nonlocal first
        if not first and PAUSE: time.sleep(PAUSE)
        first = False
        return ctx.read(url, method='POST', data=body, headers=HEADERS)

    seen, count = set(), 0
    for page in range(1, ctx.pages + 1):
        if not ctx.report['search_url']: ctx.report['search_url'] = LIST_URL
        rows, total = _page(read(LIST_URL, _body(pageNo=page, pageSize=PAGE_SIZE)))
        ctx.report['pages'] += 1; ctx.report['fetched'] += len(rows)
        for row in rows:
            ident = _row_id(row)
            if ident is None:
                record_detail_error(ctx.report, None, SourceError('parse_error', '米哈游招聘岗位缺少稳定 ID 或名称'))
                continue
            if ident in seen: continue
            seen.add(ident)
            text = ' '.join(str(row.get(k) or '') for k in ('title', 'competencyType', 'projectName'))
            if not matches(text, ctx.terms): continue
            try:
                job = _job(row, _envelope(read(INFO_URL, _body(id=ident)), '详情'), company)
            except SourceError as e:
                if e.status != 'parse_error': raise
                record_detail_error(ctx.report, ident, e)
                continue
            if ctx.keep and not ctx.keep(job):
                ctx.report['filtered'] = ctx.report.get('filtered', 0) + 1
                continue
            if count >= ctx.limit:
                ctx.report['truncated'] = True
                return
            count += 1
            yield job
        if not rows or page * PAGE_SIZE >= total: return
        if page == ctx.pages: ctx.report['truncated'] = True


PROVIDER = register(Provider('mihoyo', fetch, detect))
