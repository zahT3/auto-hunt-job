"""大易 WinTalent recruiting portals on hotjob.cn and wintalent.cn (/wt/<tenant>/...): one public JSON job list.

Verified 2026-10-28 on 旭辉, 华润银行, 兴业证券 and 万达: GET /wt/<tenant>/web/json/position/list with a 1-based `page`,
`rowSize` (50 honoured, 100 not), `keyWord` searched on the server, recruitType=2 for 社会招聘; no token needed.
Many state-owned, property, energy and finance groups use it.
"""
import re
from urllib.parse import urlencode, urlsplit

from ..parse import SourceError, json_data, normalize
from . import Provider, paged_jobs, register

DOMAINS = ('hotjob.cn', 'wintalent.cn')
STATIC = ('hztp.hotjob.cn',)
PAGE_SIZE = 50
# The job page template differs by tenant (N300, N310, 210); N310 is what the tenants checked link to.
DETAIL = '/wt/{tenant}/web/index/webPositionN310!getOnePosition?'


def _site(entry):
    """(host, tenant code) from a careers URL on a 大易 domain, or None."""
    for key in ('careers_url', 'url'):
        value = entry.get(key)
        if not isinstance(value, str): continue
        try: parts = urlsplit(value)
        except ValueError: continue
        host = (parts.hostname or '').lower()
        tenant = re.match(r'/wt/([A-Za-z0-9_]{1,40})/', parts.path or '')
        on_domain = any(host == d or host.endswith('.' + d) for d in DOMAINS)
        if parts.scheme == 'https' and on_domain and host not in STATIC and tenant and tenant[1] != 'javascript':
            return host, tenant[1]
    return None


def _text(value):
    return re.sub(r'<br\s*/?>', '\n', value, flags=re.I) if isinstance(value, str) else value


def _job(row, host, tenant, company):
    ident = row.get('postId') if isinstance(row, dict) else None
    if isinstance(ident, bool) or not isinstance(ident, (int, str)) or not str(ident).strip() \
            or not isinstance(row.get('postName'), str) or not row['postName'].strip():
        raise SourceError('parse_error', '大易招聘岗位缺少稳定 ID 或名称')
    if any(row.get(k) is not None and not isinstance(row[k], str) for k in ('workContent', 'serviceCondition')):
        raise SourceError('parse_error', '大易招聘岗位正文结构变化')
    jd = '\n'.join(part for part in (row.get('workContent') and '工作职责：\n' + _text(row['workContent']),
                                     row.get('serviceCondition') and '任职要求：\n' + _text(row['serviceCondition'])) if part)
    token = row.get('postIdToken')
    query = dict(postIdEnc=token) if isinstance(token, str) and re.fullmatch(r'[0-9a-f]{16,64}', token) else dict(postId=ident)
    url = 'https://' + host + DETAIL.format(tenant=tenant) + urlencode(dict(query, recruitType=2, brandCode=1))
    posted = row.get('publishDate') if isinstance(row.get('publishDate'), str) and re.match(r'\d{4}-\d\d-\d\d$', row['publishDate']) else None
    # postId is unique within a tenant only, so the tenant code is part of the identity.
    return normalize('dayee', tenant + ':' + str(ident), row['postName'], jd, url, company,
                     row.get('workPlace') if isinstance(row.get('workPlace'), str) else None,
                     published_at=posted, raw=dict(source_kind='dayee', record=row))


def detect(entry):
    return dict(entry, kind='dayee') if _site(entry) else None


def fetch(entry, ctx):
    site = _site(entry)
    if not site: raise SourceError('not_configured', '大易招聘页地址无效（需要 /wt/<公司代号>/ 路径）')
    host, tenant = site
    api = 'https://' + host + '/wt/' + tenant + '/web/json/position/list'
    headers = {'Referer': 'https://' + host + '/wt/' + tenant + '/web/index/social?brandCode=1', 'X-Requested-With': 'XMLHttpRequest'}

    def fetch_page(term, page):
        url = api + '?' + urlencode(dict(brandCode=1, recruitType=2, page=page, rowSize=PAGE_SIZE, keyWord=term))
        if not ctx.report['search_url']: ctx.report['search_url'] = url
        body = json_data(ctx.read(url, headers=headers))
        rows = body.get('postList') if isinstance(body, dict) else None
        pages = body.get('pageCount') if isinstance(body, dict) else None
        if not isinstance(rows, list) or not isinstance(pages, int) or isinstance(pages, bool) or pages < 0:
            raise SourceError('parse_error', '大易招聘列表结构变化')
        # Stop by the server's own page count: it may serve fewer rows a page than asked.
        return rows, pages * PAGE_SIZE

    return paged_jobs(ctx, fetch_page, lambda row: _job(row, host, tenant, entry.get('company') or '待确认'),
                      lambda row: str(row.get('postId')) if isinstance(row, dict) and row.get('postId') else None, PAGE_SIZE)


PROVIDER = register(Provider('dayee', fetch, detect))
