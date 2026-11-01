"""Greenhouse, Lever and Ashby public job boards; a company's own website reuses read_board for linked boards."""
from urllib.parse import urlencode

from ..search.query import matches
from ..sources import SourceError, ashby_row, at_board, greenhouse_row, json_data, lever_row
from . import Provider, register


def read_board(source, read, terms, limit, pages, report):
    kind, board = source['kind'], at_board(source['kind'], source.get('board'))
    company = source.get('company') or board
    if kind == 'greenhouse':
        # The full content feed can exceed 5 MiB. Discover IDs first, then read
        # bounded matching details. Greenhouse's public list is not paginated.
        url = 'https://boards-api.greenhouse.io/v1/boards/' + board + '/jobs'
        report['search_url'] = url
        data = json_data(read(url)); rows = data.get('jobs') if isinstance(data, dict) else None
        if not isinstance(rows, list): raise SourceError('parse_error', 'Greenhouse 列表结构变化')
        report['pages'] = 1; report['fetched'] = len(rows)
        matching = [r for r in rows if isinstance(r, dict) and r.get('id') and matches(r.get('title', ''), terms)]
        report['filter_scope'] = 'title'
        for row in matching[:limit]:
            detail_url = url + '/' + str(row['id'])
            detail = json_data(read(detail_url))
            if str(detail.get('id')) != str(row['id']): raise SourceError('parse_error', 'Greenhouse 详情身份不一致')
            yield greenhouse_row(detail, board, company)
        report['truncated'] = len(matching) > limit
    elif kind == 'ashby':
        url = 'https://api.ashbyhq.com/posting-api/job-board/' + board + '?includeCompensation=true'
        report['search_url'] = url
        data = json_data(read(url)); rows = data.get('jobs') if isinstance(data, dict) else None
        if not isinstance(rows, list): raise SourceError('parse_error', 'Ashby 列表结构变化')
        report['pages'] = 1; report['fetched'] = len(rows); count = 0
        for row in rows:
            if not isinstance(row, dict): raise SourceError('parse_error', 'Ashby 岗位结构变化')
            if row.get('isListed') is False: continue
            if not matches(row.get('title', '') + ' ' + str(row.get('descriptionPlain', '')), terms): continue
            if count >= limit: report['truncated'] = True; break
            yield ashby_row(row, board, company); count += 1
    else:
        count, seen = 0, set()
        for page in range(pages):
            url = 'https://api.lever.co/v0/postings/' + board + '?' + urlencode(dict(mode='json', skip=page * 50, limit=50))
            if not report['search_url']: report['search_url'] = url
            rows = json_data(read(url))
            if not isinstance(rows, list): raise SourceError('parse_error', 'Lever 列表结构变化')
            report['pages'] += 1; report['fetched'] += len(rows)
            new = 0
            for row in rows:
                if not isinstance(row, dict) or not row.get('id'): raise SourceError('parse_error', 'Lever 岗位缺少身份')
                if row['id'] in seen: continue
                seen.add(row['id']); new += 1
                if not matches(row.get('text', '') + ' ' + str(row.get('descriptionPlain', '')), terms): continue
                if count >= limit: report['truncated'] = True; return
                yield lever_row(row, board, company); count += 1
            if len(rows) < 50: break
            if not new: raise SourceError('parse_error', 'Lever 分页重复，已停止而不是继续请求')
            if page == pages - 1: report['truncated'] = True


def fetch(entry, ctx):
    return read_board(entry, ctx.read, ctx.terms, ctx.limit, ctx.pages, ctx.report)


for _id in ('greenhouse', 'lever', 'ashby'):
    register(Provider(_id, fetch))
