"""BOSS 直聘 and 猎聘 search pages, read publicly or through the dedicated read-only browser discovery opens."""
import re
from urllib.parse import urlencode

from ..search.query import matches
from ..sources import SourceError, gate, html_text, liepin_cards, platform_detail, platform_links
from . import Provider, register


def read_platform(source, read, terms, limit, pages, report):
    kind = source['kind']; seen = set(); count = 0; failures = []
    # 猎聘 card mode: jobs come from the search page's cards and are kept by title; no detail page is opened.
    cards = kind == 'liepin' and source.get('cards') is True
    if cards: report['cards'] = True
    for term in terms:
        for page in range(pages):
            url = ('https://www.zhipin.com/web/geek/job?' + urlencode(dict(query=term, city='100010000', page=page + 1)) if kind == 'boss'
                   else 'https://www.liepin.com/zhaopin/?' + urlencode(dict(key=term, currentPage=page, pageSize=40, scene='input', inputFrom='www_index')))
            if not report['search_url']: report['search_url'] = url
            html = html_text(read(url)); text = gate(html)
            report['pages'] += 1
            found = {job['url']: job for job in liepin_cards(html, url)} if cards else None
            links = list(found) if cards else platform_links(html, url, kind)
            if not links:
                if re.search(r'暂无.{0,8}(职位|岗位)|没有找到.{0,8}(职位|岗位)|未找到.{0,8}(职位|岗位)', text): break
                raise SourceError('blocked', '公开页面未提供岗位列表，需要浏览器渲染或登录；不是零岗位。可启用独立浏览器只读模式')
            fresh = [link for link in links if link not in seen]
            report['fetched'] += len(fresh)
            if not fresh: break
            for link in fresh:
                seen.add(link)
                if count >= limit: report['truncated'] = True; return
                if cards:
                    job = found[link]
                    if matches(job['title'], terms): yield job; count += 1
                    else: report['filtered'] += 1
                    continue
                try:
                    item = platform_detail(html_text(read(link)), link, kind)
                except SourceError as e:
                    if e.status != 'parse_error': raise
                    failures.append(dict(url=link, status=e.status, error=str(e)))
                    report['detail_errors'] = failures
                    continue
                if item['status'] == 'closed': continue
                if matches(item['title'] + ' ' + item['jd'], terms):
                    yield item; count += 1
            if page == pages - 1: report['truncated'] = True
    if failures: raise SourceError('parse_error', str(len(failures)) + ' 个岗位详情无法解析；已保留其余真实结果')


def fetch(entry, ctx):
    return read_platform(entry, ctx.read, ctx.terms, ctx.limit, ctx.pages, ctx.report)


for _id in ('boss', 'liepin'):
    register(Provider(_id, fetch))
