"""Read imToken's public job pages without pretending its broken list is empty.

The official sitemap is a discovery fallback, not evidence that a vacancy is
still open. Such results remain unverified and retain that limitation alongside
the exact, publicly advertised application email. No email is sent here.
"""
import re
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree

from .careers import attach_route
from .network import FetchError
from .sources import Document, Node, SourceError, normalize, public_url


HOST = 'careers.token.im'
BASE = 'https://' + HOST
UNKNOWN = '官网职位列表暂不可用；从官方站点地图发现此岗位页，是否仍在招需确认。'


def job_url(value, base=BASE):
    url = public_url(urljoin(base, value))
    p = urlsplit(url)
    return url if p.hostname == HOST and re.fullmatch(r'/(?:en|cn)/(?!home(?:/|$))[A-Za-z0-9_-]+/?', p.path) else ''


def listed_links(html):
    """Only explicit job anchors or quoted literal links in window.jobs."""
    found = []
    for n in Document(html).root.nodes():
        if n.tag == 'a':
            found.append(job_url(n.attrs.get('href', '')))
        elif n.tag == 'script':
            script = ''.join(c for c in n.children if isinstance(c, str))
            for array in re.finditer(r'window\.jobs\s*=\s*\[(.*?)\]\s*;?', script, re.S):
                for m in re.finditer(r'\blink\s*:\s*([\x27"])([^\x27"\n]+)\1', array[1]):
                    found.append(job_url(m[2]))
    return list(dict.fromkeys(u for u in found if u))


def sitemap_jobs(raw):
    """No XML entities, external resources, alternate hosts, or sitemap guessing."""
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise SourceError('parse_error', 'imToken 站点地图包含不支持的 XML 声明')
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError as error:
        raise SourceError('parse_error', 'imToken 站点地图格式变化') from error
    ns = '{http://www.sitemaps.org/schemas/sitemap/0.9}'
    if root.tag != ns + 'urlset':
        raise SourceError('parse_error', 'imToken 站点地图不是公开页面列表')
    rows = {}
    for n in root.findall(ns + 'url'):
        url = job_url(n.findtext(ns + 'loc') or '')
        if not url: continue
        slug = urlsplit(url).path.rstrip('/').rsplit('/', 1)[-1]
        lastmod = n.findtext(ns + 'lastmod') or ''
        # English/Chinese versions of the same slug are one candidate. Prefer
        # English for stable identity, without claiming the translations match.
        if slug not in rows or '/en/' in url:
            rows[slug] = dict(url=url, lastmod=lastmod, slug=slug)
    return list(rows.values())


def _prose(n):
    if n.tag in ('script', 'style', 'noscript'): return ''
    if n.tag in ('br', 'hr'): return '\n'
    body = ''.join(_prose(c) if isinstance(c, Node) else c for c in n.children)
    return body + ('\n' if n.tag in ('p', 'li', 'div', 'section', 'article', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6') else '')


def parse_job(html, url, company='imToken'):
    doc = Document(html)
    containers = [n for n in doc.root.nodes() if 'sqs-html-content' in n.attrs.get('class', '').split()]
    article = next((n for n in containers if n.first(tags=('h3',)) and any(
        c.tag == 'h4' and c.text() in ('Location', '工作地点') for c in n.nodes())), None)
    if article is None:
        raise SourceError('parse_error', 'imToken 页面没有可识别的职位正文和工作地点')
    title = article.first(tags=('h3',)).text()
    text = _prose(article)
    if len(text.strip()) < 200 or not re.search(r'qualifications|requirements|skills|职责|要求|look for|you.ll', text, re.I):
        raise SourceError('parse_error', 'imToken 职位正文不完整')
    location = re.search(r'(?:^|\n)(?:Location|工作地点)\s*\n([^\n]+)', text)
    title_text = ' '.join(n.text() for n in doc.root.nodes() if n.tag in ('title', 'h1', 'h2', 'h3'))
    if re.search(r'position (?:is )?(?:closed|filled)|no longer accepting|招聘结束|职位已关闭|职位已下线', title_text, re.I):
        raise SourceError('closed', 'imToken 官网标明该岗位已关闭')
    job = normalize('website', 'imtoken:' + urlsplit(url).path.strip('/'), title, text, url, company,
                    location[1].strip() if location else None, status='unverified')
    # Only an actual mailto in the employer page can establish the receiver.
    email = next((n.attrs.get('href', '').split('?', 1)[0][7:] for n in doc.root.nodes()
                  if n.tag == 'a' and n.attrs.get('href', '').lower().split('?', 1)[0] == 'mailto:hr@token.im'), None)
    if email: job['raw']['public_application_email'] = email
    return job


def read_jobs(source, read, terms, limit, pages, report, html=None, renderer=None):
    """Use with the existing budgeted read callback; pages bounds detail reads."""
    from .discovery import matches
    career = source.get('url') or BASE + '/'
    if html is None:
        try:
            html = read(career).decode('utf-8'); report['pages'] += 1
        except FetchError as error:
            # A flaky landing page need not hide reachable, public job pages.
            # The robots-declared sitemap can still give unverified leads.
            report['homepage_error'] = str(error)[:400]
            html = ''
    urls = listed_links(html)
    report['adapter'] = 'imtoken_public'; report['filter_scope'] = 'title_and_body'
    fallback = not urls
    observed = career
    if fallback:
        robots = read(BASE + '/robots.txt').decode('utf-8'); report['pages'] += 1
        observed = next((public_url(m[1]) for m in re.finditer(r'^Sitemap:\s*(https://\S+)\s*$', robots, re.M | re.I)
                         if urlsplit(public_url(m[1])).hostname == HOST), None)
        if not observed: raise SourceError('parse_error', 'imToken 列表不可用且没有声明官方站点地图')
        rows = sitemap_jobs(read(observed)); report['pages'] += 1
        if not rows: raise SourceError('parse_error', 'imToken 列表不可用；官方站点地图也没有可识别的职位页')
        # Prefer recently edited engineering pages over stale exact-slug hits.
        # lastmod stays page metadata, never a posting/availability date.
        rows.sort(key=lambda r: not matches(r['slug'].replace('-', ' '), terms))
        rows.sort(key=lambda r: r['lastmod'], reverse=True)
        rows.sort(key=lambda r: not bool(re.search(r'engineer|backend|frontend|senior-fe|sre|architect|bedex', r['slug'], re.I)))
        report['listing_status'] = 'unavailable'
        report['availability_note'] = UNKNOWN
    else:
        rows = [dict(url=u, lastmod=None) for u in urls]
        report['listing_status'] = 'observed'
    report['observed_entry_urls'] = [observed]
    report['fetched'] += len(rows)
    count = 0; visited = 0
    for row in rows[:pages]:
        visited += 1
        try:
            try:
                detail = read(row['url']).decode('utf-8'); report['pages'] += 1
            except FetchError:
                if renderer is None: raise
                rendered = renderer.read(row['url']); report['pages'] += 1
                if rendered.get('status', 200) >= 400 or public_url(rendered.get('url', '')) != row['url']:
                    raise SourceError('parse_error', 'imToken 渲染页面与岗位地址不一致')
                detail = rendered['body'].decode('utf-8')
            job = parse_job(detail, row['url'], source.get('company') or 'imToken')
        except (SourceError, FetchError) as error:
            # Cancellation/budget signals are SourceError too; propagate them.
            if isinstance(error, SourceError) and error.status in ('cancelled', 'budget_exhausted'): raise
            report.setdefault('detail_errors', []).append(dict(url=row['url'], status=getattr(error, 'status', 'fetch_error'), error=str(error)))
            continue
        if not matches(job['title'] + ' ' + job['jd'], terms): continue
        attach_route(job, dict(career_url=career, observed_url=observed,
                              evidence_type='sitemap' if fallback else 'link'))
        route = job['raw']['application_route']
        route['listing_status'] = 'unavailable' if fallback else 'observed'
        route['note'] = UNKNOWN if fallback else '官网列表引用此职位页；已读取正文，招聘状态仍需确认。'
        if job['raw'].get('public_application_email'):
            route.update(entry_type='email', email=job['raw'].pop('public_application_email'))
        job['raw']['source_listing_status'] = route['listing_status']
        job['raw']['availability_note'] = route['note']
        job['raw']['page_last_modified'] = row.get('lastmod')
        yield job; count += 1
        if count >= limit: break
    report['truncated'] = visited < len(rows)
