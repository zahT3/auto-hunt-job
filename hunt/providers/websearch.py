"""Whole-web index extension through the user's own SearXNG JSON endpoint; only employer pages supply a JD."""
from urllib.parse import urlencode, urlsplit, urlunsplit

from ..search.query import matches
from ..sources import SourceError, gate, html_text, json_data, jsonld_jobs, public_url
from . import Provider, register


def read_websearch(source, read, terms, limit, pages, report):
    if source.get('provider') != 'searxng':
        raise SourceError('not_configured', '全网索引扩展需配置自有 SearXNG HTTPS JSON 搜索端点；不依赖 Codex 搜索工具')
    endpoint = public_url(source.get('url') or '')
    if not endpoint: raise SourceError('not_configured', 'SearXNG 端点无效，仅支持公开 HTTPS')
    seen = set(); count = 0
    for term in terms:
        for page in range(1, pages + 1):
            p = urlsplit(endpoint)
            url = urlunsplit((p.scheme, p.netloc, p.path or '/search', urlencode(dict(q=term + ' jobs careers', format='json', pageno=page)), ''))
            if not report['search_url']: report['search_url'] = url
            data = json_data(read(url)); rows = data.get('results') if isinstance(data, dict) else None
            if not isinstance(rows, list): raise SourceError('parse_error', '搜索端点未返回 results 数组或未启用 JSON')
            report['pages'] += 1; report['fetched'] += len(rows)
            for row in rows[:10]:
                target = public_url(row.get('url') or '')
                if not target or target in seen: continue
                seen.add(target)
                # Only the employer/platform page can supply the actual JD;
                # snippets are never fabricated into job descriptions.
                html = html_text(read(target)); gate(html)
                for item in jsonld_jobs(html, target):
                    if item['status'] != 'closed' and matches(item['title'] + ' ' + item['jd'], terms):
                        if count >= limit: report['truncated'] = True; return
                        yield item; count += 1
            if not rows: break
            if page == pages: report['truncated'] = True


register(Provider('websearch', lambda entry, ctx: read_websearch(entry, ctx.read, ctx.terms, ctx.limit, ctx.pages, ctx.report)))
