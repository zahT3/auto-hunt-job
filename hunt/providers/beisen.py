"""北森 (Beisen) recruiting portals, {tenant}.zhiye.com: one public job-list API shared by every tenant.

Verified 2026-10-28 on njzq / chinalife: POST /api/Jobad/GetJobAdPageList with a 0-based PageIndex; KeyWords is
searched on the server; no signature or cookie is needed. Banks, brokerages and insurers often use it.
"""
import json
import re
from urllib.parse import urlencode, urlsplit

from ..sources import SourceError, json_data, normalize
from . import Provider, paged_jobs, register

DOMAIN = '.zhiye.com'
PAGE_SIZE = 100
NOT_TENANTS = ('www', 'portal-oss', 'acdn', 'api')


def _host(entry):
    for key in ('careers_url', 'url'):
        value = entry.get(key)
        if not isinstance(value, str): continue
        try: parts = urlsplit(value)
        except ValueError: continue
        host = (parts.hostname or '').lower()
        tenant = host[:-len(DOMAIN)] if host.endswith(DOMAIN) else ''
        if parts.scheme == 'https' and re.fullmatch(r'[a-z0-9-]{2,63}', tenant) and tenant not in NOT_TENANTS:
            return host
    return None


def _row_id(row):
    ident = row.get('Id') if isinstance(row, dict) else None
    return ident if isinstance(ident, str) and re.fullmatch(r'[0-9a-fA-F-]{8,64}', ident) else None


def _posted(value):
    # The list answers '0001-01-01T00:00:00' when a tenant hides post dates.
    return value[:10] if isinstance(value, str) and re.match(r'(19|20)\d\d-\d\d-\d\d', value) else None


def _job(row, host, company):
    ident = _row_id(row)
    if not ident or not isinstance(row.get('JobAdName'), str) or not row['JobAdName'].strip():
        raise SourceError('parse_error', '北森招聘岗位缺少稳定 ID 或名称')
    if any(row.get(k) is not None and not isinstance(row[k], str) for k in ('Duty', 'Require')):
        raise SourceError('parse_error', '北森招聘岗位正文结构变化')
    places = row.get('LocNames') or []
    if not isinstance(places, list): raise SourceError('parse_error', '北森招聘岗位地点结构变化')
    jd = '\n'.join(part for part in (row.get('Duty') and '工作职责：\n' + row['Duty'], row.get('Require') and '任职资格：\n' + row['Require']) if part)
    url = 'https://' + host + '/social/detail?' + urlencode(dict(jobAdId=ident))
    return normalize('beisen', ident, row['JobAdName'], jd, url, company, '、'.join(str(p) for p in places) or None,
                     published_at=_posted(row.get('PostDate')), raw=dict(source_kind='beisen', record=row))


def detect(entry):
    return dict(entry, kind='beisen') if _host(entry) else None


def fetch(entry, ctx):
    host = _host(entry)
    if not host: raise SourceError('not_configured', '北森招聘页地址无效')
    api = 'https://' + host + '/api/Jobad/GetJobAdPageList'
    headers = {'Content-Type': 'application/json', 'Referer': 'https://' + host + '/social', 'Origin': 'https://' + host}

    def fetch_page(term, page):
        if not ctx.report['search_url']: ctx.report['search_url'] = api
        data = json.dumps(dict(PageIndex=page - 1, PageSize=PAGE_SIZE, KeyWords=term, SpecialType=0, PortalId=''), ensure_ascii=False).encode()
        body = json_data(ctx.read(api, method='POST', data=data, headers=headers))
        rows = body.get('Data') if isinstance(body, dict) else None
        total = body.get('Count') if isinstance(body, dict) else None
        if not isinstance(rows, list) or not isinstance(total, int) or isinstance(total, bool) or total < 0:
            raise SourceError('parse_error', '北森招聘列表结构变化')
        return rows, total

    return paged_jobs(ctx, fetch_page, lambda row: _job(row, host, entry.get('company') or '待确认'), _row_id, PAGE_SIZE)


PROVIDER = register(Provider('beisen', fetch, detect))
