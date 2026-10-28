"""网易招聘公开岗位列表；保留原始 workType，不猜测社招/校招含义。"""
import json
from urllib.parse import urlencode, urlsplit

from ..sources import SourceError, json_data, normalize
from . import Provider, paged_jobs, register

HOST = 'hr.163.com'
PAGE_SIZE = 100
LIST_URL = 'https://' + HOST + '/job-list.html'
HEADERS = {'Content-Type': 'application/json', 'Referer': LIST_URL, 'Origin': 'https://' + HOST}


def _row_id(row):
    ident = row.get('id') if isinstance(row, dict) else None
    return str(ident) if isinstance(ident, (str, int)) and not isinstance(ident, bool) and str(ident).strip() else None


def _job(row, company):
    ident = _row_id(row)
    if not ident or not isinstance(row.get('name'), str) or not row['name'].strip():
        raise SourceError('parse_error', '网易招聘岗位缺少稳定 ID 或名称')
    if any(row.get(k) is not None and not isinstance(row[k], str) for k in ('description', 'requirement')):
        raise SourceError('parse_error', '网易招聘岗位正文结构变化')
    jd = '\n'.join(row.get(k) or '' for k in ('description', 'requirement')).strip()
    locations = row.get('workPlaceNameList')
    if locations is None: locations = []
    if not isinstance(locations, list): raise SourceError('parse_error', '网易招聘岗位地点结构变化')
    try: url = LIST_URL + '?' + urlencode(dict(id=ident))
    except UnicodeError as e: raise SourceError('parse_error', '网易招聘岗位 ID 无法编码') from e
    return normalize('netease', ident, row['name'], jd, url,
                     company, '、'.join(str(p) for p in locations) or None, raw=dict(source_kind='netease', record=row))


def detect(entry):
    for key in ('careers_url', 'url'):
        value = entry.get(key)
        if not isinstance(value, str): continue
        try: parts = urlsplit(value)
        except ValueError: continue
        if parts.scheme == 'https' and parts.hostname == HOST: return dict(entry, kind='netease')
    return None


def fetch(entry, ctx):
    def fetch_page(term, page):
        url = 'https://' + HOST + '/api/hr163/position/queryPage'
        if not ctx.report['search_url']: ctx.report['search_url'] = url
        data = json.dumps(dict(currentPage=page, pageSize=PAGE_SIZE, keyword=term), ensure_ascii=False).encode()
        body = json_data(ctx.read(url, method='POST', data=data, headers=HEADERS, timeout=20))
        body = body.get('data') if isinstance(body, dict) else None
        rows = body.get('list') if isinstance(body, dict) else None
        total = body.get('total') if isinstance(body, dict) else None
        if not isinstance(rows, list) or not isinstance(total, int) or isinstance(total, bool) or total < 0:
            raise SourceError('parse_error', '网易招聘列表结构变化')
        return rows, total

    return paged_jobs(ctx, fetch_page, lambda row: _job(row, entry.get('company') or '网易'), _row_id, PAGE_SIZE)


PROVIDER = register(Provider('netease', fetch, detect))
