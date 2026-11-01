"""A company's own careers page: a catalog adapter when one exists, else JobPosting data and linked job boards."""
import re
from urllib.parse import urljoin, urlsplit

from .careers import attach_route, linked_boards
from ..entries import official_job_link
from ..query import matches
from ..parse import Document, SourceError, gate, html_text, jsonld_jobs, public_url
from . import Provider, register
from .ats import read_board
from .catalog import lookup
from .domestic import read_jobs


def read_website(source, read, terms, limit, pages, report, renderer=None):
    url = public_url(source.get('url') or '')
    if not url: raise SourceError('not_configured', '请配置公司官网公开 HTTPS 招聘页')
    if lookup(url):
        yield from read_jobs(source, read, terms, limit, pages, report, renderer)
        return
    report['search_url'] = url; queue = [url]; seen = set(); emitted = set(); count = 0; boards_seen = set()
    while queue and report['pages'] < pages:
        current = queue.pop(0)
        if current in seen: continue
        seen.add(current)
        html = html_text(read(current)); gate(html); report['pages'] += 1
        rows = jsonld_jobs(html, current)
        report['fetched'] += len(rows)
        for item in rows:
            if item['url'] in emitted or item['status'] == 'closed': continue
            emitted.add(item['url'])
            if not matches(item['title'] + ' ' + item['jd'], terms): continue
            if count >= limit: report['truncated'] = True; return
            yield item; count += 1
        for board in linked_boards(html, current):
            key = (board['kind'], board['board'])
            if key in boards_seen: continue
            boards_seen.add(key)
            report.setdefault('linked_boards', []).append(board)
            if count >= limit or report['pages'] >= pages:
                report['truncated'] = True
                return
            child = dict(pages=0, fetched=0, truncated=False, search_url=None)
            try:
                for item in read_board(dict(board, company=source.get('company') or urlsplit(url).hostname),
                                 read, terms, limit-count, pages-report['pages'], child):
                    identity = (item['channel'], item['platform_id'])
                    if identity in emitted: continue
                    emitted.add(identity)
                    attach_route(item, board)
                    alternate = official_job_link(html, current, item['title'])
                    if alternate: item['raw']['application_route']['official_job_url'] = alternate
                    yield item; count += 1
            finally:
                report['pages'] += child['pages']
                report['fetched'] += child['fetched']
                report['truncated'] = report['truncated'] or child['truncated']
        for n in Document(html).root.nodes():
            if n.tag != 'a': continue
            link = public_url(urljoin(current, n.attrs.get('href', '')))
            if urlsplit(link).hostname == urlsplit(url).hostname and re.search(r'job|career|position|recruit', urlsplit(link).path, re.I) and link not in seen and link not in queue:
                queue.append(link)
    report['truncated'] = report['truncated'] or bool(queue)
    if not emitted and not boards_seen: raise SourceError('parse_error', '官网未提取到 JobPosting 正文或受支持的招聘看板；当前页需专用适配，不能视作无岗位')


register(Provider('website', lambda entry, ctx: read_website(entry, ctx.read, ctx.terms, ctx.limit, ctx.pages, ctx.report, ctx.renderer)))
