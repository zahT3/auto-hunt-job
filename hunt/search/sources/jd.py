"""京东招聘公开列表接口；旧站可能忽略分页，按稳定 ID 检测重复页。"""
from urllib.parse import urlencode, urlsplit

from ..parse import SourceError, json_data, normalize
from . import Context, Provider, paged_jobs, register

HOST = 'zhaopin.jd.com'
PAGE_SIZE = 100
LIST_URL = 'https://' + HOST + '/web/job/job_info_list/3'
HEADERS = {'Content-Type': 'application/x-www-form-urlencoded', 'Referer': LIST_URL, 'Origin': 'https://' + HOST}


def _form(term, page):
    return urlencode(dict(pageIndex=page, pageSize=PAGE_SIZE, workCityJson='[]', jobTypeJson='[]', jobSearch=term)).encode()


def _row_id(row):
    ident = row.get('id') if isinstance(row, dict) else None
    return str(ident) if isinstance(ident, (str, int)) and not isinstance(ident, bool) and str(ident).strip() else None


def _job(row, company):
    ident = _row_id(row)
    if not ident or not isinstance(row.get('positionNameOpen'), str) or not row['positionNameOpen'].strip():
        raise SourceError('parse_error', '京东招聘岗位缺少稳定 ID 或对外名称')
    if any(row.get(k) is not None and not isinstance(row[k], str) for k in ('workContent', 'qualification')):
        raise SourceError('parse_error', '京东招聘岗位正文结构变化')
    jd = '\n'.join(row.get(k) or '' for k in ('workContent', 'qualification')).strip()
    try: url = LIST_URL + '?' + urlencode(dict(id=ident))
    except UnicodeError as e: raise SourceError('parse_error', '京东招聘岗位 ID 无法编码') from e
    return normalize('jd', ident, row['positionNameOpen'], jd, url, company, row.get('workCity'),
                     published_at=row.get('formatPublishTime'), raw=dict(source_kind='jd', record=row))


def detect(entry):
    for key in ('careers_url', 'url'):
        value = entry.get(key)
        if not isinstance(value, str): continue
        try: parts = urlsplit(value)
        except ValueError: continue
        if parts.scheme == 'https' and parts.hostname == HOST: return dict(entry, kind='jd')
    return None


def fetch(entry, ctx):
    totals, seen = {}, {}

    def fetch_page(term, page):
        url = 'https://' + HOST + '/web/job/job_list'
        if not ctx.report['search_url']: ctx.report['search_url'] = url
        data = _form(term, page)
        if term not in totals:
            total = json_data(ctx.read('https://' + HOST + '/web/job/job_count', method='POST', data=data, headers=HEADERS))
            if not isinstance(total, int) or isinstance(total, bool) or total < 0:
                raise SourceError('parse_error', '京东招聘岗位总数结构变化')
            totals[term], seen[term] = total, set()
        rows = json_data(ctx.read(url, method='POST', data=data, headers=HEADERS))
        if not isinstance(rows, list): raise SourceError('parse_error', '京东招聘列表结构变化')
        ids = {_row_id(row) for row in rows} - {None}
        repeated = page > 1 and bool(ids) and not ids.difference(seen[term])
        seen[term].update(ids)
        if repeated and len(seen[term]) < totals[term]: ctx.report['truncated'] = True
        return rows, min(totals[term], page * PAGE_SIZE) if repeated else totals[term]

    # jobSearch matches literally, so 'AI 产品经理' misses every 'AI产品经理'; a spaced term is also searched unspaced.
    terms = list(dict.fromkeys(t for term in ctx.terms for t in (term, ''.join(term.split())) if t))
    searched = Context(ctx.read, terms, ctx.limit, ctx.pages, ctx.report, ctx.renderer, keep=ctx.keep)
    return paged_jobs(searched, fetch_page, lambda row: _job(row, entry.get('company') or '京东'), _row_id, PAGE_SIZE)


PROVIDER = register(Provider('jd', fetch, detect))
