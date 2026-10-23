"""Public job-source parsers. No login credentials, resume text, or application writes."""
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
import json
import re
from urllib.parse import urljoin, urlsplit, urlunsplit


class SourceError(ValueError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class Node:
    def __init__(self, tag='', attrs=None, parent=None):
        self.tag, self.attrs, self.parent, self.children = tag, dict(attrs or []), parent, []
        self.depth = parent.depth + 1 if parent else 0
        if self.depth > 128: raise SourceError('parse_error', '网页嵌套超过解析上限')

    def nodes(self):
        yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.nodes()

    def text(self):
        if self.tag in ('script', 'style', 'noscript'):
            return ''
        return re.sub(r'\s+', ' ', ' '.join(c.text() if isinstance(c, Node) else c for c in self.children)).strip()

    def prose(self):
        if self.tag in ('script', 'style', 'noscript'): return ''
        if self.tag in ('br', 'hr'): return '\n'
        text = ''.join(c.prose() if isinstance(c, Node) else c for c in self.children)
        return text + ('\n' if self.tag in ('p','div','li','h1','h2','h3','section','article','tr') else '')

    def first(self, classes=(), tags=()):
        for n in self.nodes():
            if (classes and set(classes).intersection(n.attrs.get('class', '').split())) or (tags and n.tag in tags):
                return n
        return None


class Document(HTMLParser):
    VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = self.current = Node()
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        n = Node(tag, attrs, self.current)
        self.current.children.append(n)
        if tag not in self.VOID:
            self.current = n

    def handle_startendtag(self, tag, attrs):
        self.current.children.append(Node(tag, attrs, self.current))

    def handle_endtag(self, tag):
        n = self.current
        while n.parent:
            if n.tag == tag:
                self.current = n.parent
                return
            n = n.parent

    def handle_data(self, data):
        self.current.children.append(data)


def plain(value):
    return Document(unescape(str(value or ''))).root.text()


def jd_text(value):
    """Keep prose paragraphs and comparisons while dropping recognized markup."""
    text = unescape(str(value or ''))
    # Remove only real HTML tags; plain text such as C++ < Java remains text.
    text = re.sub(r'<(script|style)\b[^>]*>.*?</\1\s*>', '', text, flags=re.I | re.S)
    text = re.sub(r'<\s*(?:br|hr)\s*/?\s*>|</(?:p|div|li|ul|ol|h[1-6]|section|article|tr)\s*>', '\n', text, flags=re.I)
    text = re.sub(r'</?(?:p|div|li|ul|ol|h[1-6]|section|article|span|a|b|strong|em|i|u|font|table|tbody|thead|td|tr|blockquote|pre|code|img)\b[^>]*>', '', text, flags=re.I)
    lines = [re.sub(r'[ \t\r\f\v]+', ' ', line).strip() for line in text.split('\n')]
    return re.sub(r'\n{3,}', '\n\n', '\n'.join(lines)).strip()


def now():
    return datetime.now(timezone.utc).isoformat()


def public_url(url):
    from .network import validate_url
    try:
        p, _ = validate_url(url)
    except ValueError:
        return ''
    return urlunsplit((p.scheme, p.netloc, p.path, p.query, ''))


def normalize(kind, ident, title, jd, url, company=None, location=None, **extra):
    url = public_url(url)
    if not ident or not plain(title) or not plain(jd) or not url:
        raise SourceError('parse_error', '岗位缺少稳定身份、名称、正文或公开来源链接')
    result = dict(channel=kind, platform_id=str(ident), title=plain(title)[:500], company=company or '待确认',
                  jd=jd_text(jd)[:100000], url=url, application_url=url, location=location or None,
                  salary=None, requirements_text=None, status='unverified', collected_at=now(), published_at=None,
                  raw=dict(source_url=url, source_kind=kind))
    result.update(extra)
    result['application_url'] = public_url(result.get('application_url') or url) or url
    return result


def json_data(raw):
    try:
        return json.loads(raw)
    except (ValueError, UnicodeError) as e:
        raise SourceError('parse_error', '公开接口未返回可解析的 JSON') from e


def at_board(kind, board):
    if not isinstance(board, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', board):
        raise SourceError('not_configured', '公司官网需要有效的招聘看板 slug')
    return board


def greenhouse_row(row, board, company):
    if not row.get('id'): raise SourceError('parse_error', 'Greenhouse 岗位缺少稳定 ID')
    return normalize('greenhouse', board + ':' + str(row.get('id', '')), row.get('title'), row.get('content'),
                     row.get('absolute_url', ''), company, (row.get('location') or {}).get('name'), status='open',
                     raw=dict(source_kind='greenhouse', board=board, record=row, updated_at=row.get('updated_at')))


def lever_row(row, board, company):
    if not row.get('id'): raise SourceError('parse_error', 'Lever 岗位缺少稳定 ID')
    jd = (row.get('descriptionPlain') or jd_text(row.get('description'))) + '\n'
    for section in row.get('lists') or []:
        jd += str(section.get('text') or '') + '\n' + jd_text(section.get('content')) + '\n'
    jd += row.get('additionalPlain') or jd_text(row.get('additional'))
    return normalize('lever', board + ':' + str(row.get('id', '')), row.get('text'), jd, row.get('hostedUrl', ''),
                     company, (row.get('categories') or {}).get('location'), status='open',
                     application_url=row.get('applyUrl'), raw=dict(source_kind='lever', board=board, record=row))


def ashby_row(row, board, company):
    url = row.get('jobUrl', '')
    ident = row.get('id') or urlsplit(url).path.rstrip('/').split('/')[-1]
    if not ident: raise SourceError('parse_error', 'Ashby 岗位缺少稳定 ID')
    compensation = row.get('compensation') or {}
    return normalize('ashby', board + ':' + str(ident), row.get('title'), row.get('descriptionPlain') or row.get('descriptionHtml'),
                     url, company, row.get('location'), status='open', application_url=row.get('applyUrl'),
                     published_at=row.get('publishedAt'), salary=compensation.get('scrapeableCompensationSalarySummary'),
                     raw=dict(source_kind='ashby', board=board, record=row))


def structured_salary(row):
    base = row.get('baseSalary') or {}
    if not isinstance(base, dict): return None
    value = base.get('value')
    if not isinstance(value, dict): return str(value) if value is not None else None
    low, high = value.get('minValue'), value.get('maxValue')
    amount = value.get('value')
    if low is not None and high is not None: amount = f'{low:g}–{high:g}' if isinstance(low, (int,float)) and isinstance(high,(int,float)) else f'{low}–{high}'
    elif low is not None: amount = '≥' + str(low)
    elif high is not None: amount = '≤' + str(high)
    if amount is None: return None
    return ' '.join(str(v) for v in (base.get('currency'), amount, value.get('unitText')) if v is not None)


def jsonld_jobs(html, url, kind='website'):
    doc = Document(html)
    records = []
    def walk(x):
        if isinstance(x, list):
            for y in x: walk(y)
        elif isinstance(x, dict):
            types = x.get('@type', [])
            if types == 'JobPosting' or isinstance(types, list) and 'JobPosting' in types:
                records.append(x)
            if '@graph' in x: walk(x['@graph'])
            if 'itemListElement' in x: walk(x['itemListElement'])
            if 'item' in x: walk(x['item'])
    for n in doc.root.nodes():
        if n.tag == 'script' and n.attrs.get('type', '').lower() == 'application/ld+json':
            try: walk(json.loads(''.join(c for c in n.children if isinstance(c, str))))
            except (ValueError, TypeError): pass
    result = []
    for row in records:
        link = public_url(urljoin(url, row.get('url') or url))
        identifier = row.get('identifier') or {}
        ident = identifier.get('value') if isinstance(identifier, dict) else identifier
        # Website identity is URL-bound because employer identifiers are not globally unique.
        ident = link if kind == 'website' else ident or platform_id(kind, link)
        company = row.get('hiringOrganization') or {}
        locations = row.get('jobLocation') or []
        if not isinstance(locations, list): locations = [locations]
        cities = []
        for loc in locations:
            address = loc.get('address', {}) if isinstance(loc, dict) else {}
            if isinstance(address, str): cities.append(address)
            elif isinstance(address, dict): cities.append(' '.join(str(address.get(k) or '') for k in ('addressLocality', 'addressRegion', 'addressCountry')).strip())
        valid = row.get('validThrough')
        status = 'unverified'
        if valid:
            try:
                end = datetime.fromisoformat(str(valid).replace('Z', '+00:00'))
                if end.tzinfo is None: end = end.replace(tzinfo=timezone.utc)
                status = 'closed' if end < datetime.now(timezone.utc) else 'open'
            except ValueError: pass
        try:
            result.append(normalize(kind, ident, row.get('title'), row.get('description'), link,
                                    company.get('name') if isinstance(company, dict) else str(company), ', '.join(cities),
                                    status=status, published_at=row.get('datePosted'), salary=structured_salary(row),
                                    raw=dict(source_kind=kind, source_url=url, structured_data=row)))
        except SourceError: continue
    return result


def platform_id(kind, url):
    pattern = r'/job_detail/([^/]+)\.html' if kind == 'boss' else r'/job/(\d+)\.shtml'
    match = re.search(pattern, urlsplit(url).path)
    return match.group(1) if match else None


def platform_links(html, base, kind):
    allowed = 'www.zhipin.com' if kind == 'boss' else 'www.liepin.com'
    result = []
    for n in Document(html).root.nodes():
        if n.tag != 'a': continue
        url = public_url(urljoin(base, n.attrs.get('href', '')))
        if urlsplit(url).hostname != allowed or not platform_id(kind, url): continue
        p = urlsplit(url)
        canonical = urlunsplit((p.scheme, p.netloc, p.path, '', ''))
        if canonical not in result: result.append(canonical)
    return result


def gate(html):
    text = Document(html).root.text()
    # Do not detect SDK strings in script source or footer login links as gates.
    if re.search(r'请完成.{0,12}验证|安全验证|滑动.{0,10}验证|访问验证|人机验证|异常访问|访问过于频繁|访问异常|verify you are human', text, re.I):
        raise SourceError('captcha', '平台要求安全验证；已停止此渠道，请在独立浏览器中由本人处理后重试')
    if re.search(r'登录后.{0,8}(查看|搜索|浏览)|请先登录|登录查看完整', text):
        raise SourceError('login_required', '平台要求登录查看；可启用独立浏览器只读采集，由本人登录')
    if re.search(r'access denied|forbidden|请求被拒绝', text, re.I):
        raise SourceError('blocked', '平台拒绝当前公开访问；已停止，不自动绕过')
    return text


def platform_detail(html, url, kind):
    gate(html)
    structured = jsonld_jobs(html, url, kind)
    pid = platform_id(kind, url)
    for item in structured:
        if platform_id(kind, item['url']) == pid:
            item['platform_id'] = pid
            return item
    root = Document(html).root
    # Restrict to the main posting block, never recommendation cards.
    main = root.first(classes=('job-banner',)) if kind == 'boss' else root.first(classes=('job-title-box', 'job-title'))
    title_node = main.first(tags=('h1',)) if main else root.first(tags=('h1',))
    desc = root.first(classes=('job-sec-text', 'job-detail')) if kind == 'boss' else root.first(classes=('job-intro-container', 'job-description', 'job-intro'))
    title = title_node.text() if title_node else ''
    jd = desc.prose() if desc else ''
    if not title or len(jd) < 30:
        raise SourceError('parse_error', '岗位详情未获得可验证的标题与正文；页面可能需要浏览器渲染或结构已变化')
    company = root.first(classes=('company-name', 'company-info'))
    location = root.first(classes=('job-location', 'job-area'))
    salary = main.first(classes=('salary', 'job-salary')) if main else None
    return normalize(kind, pid, title, jd, url,
                     company.text()[:200] if company else None, location.text()[:200] if location else None,
                     salary=salary.text() if salary else None,
                     raw=dict(source_kind=kind, source_url=url, extraction='visible_dom', status_note='公开详情可读，当前在招状态仍需人工核实'))
