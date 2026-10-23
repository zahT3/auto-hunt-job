"""MiniMax social careers, read from its normal public Feishu pages.

The official /index/ link is valid in Chromium even when a plain HTTP request
returns 404. No signatures, cookies or application payloads are constructed.
"""
import re
from urllib.parse import urlencode, urljoin, urlsplit

from .careers import attach_route
from .sources import Document, Node, SourceError, normalize, public_url

HOST = 'vrfi1sk8a0.jobs.feishu.cn'
SEARCH_PATH = '/api/v1/search/job/posts'
DETAIL_PATH = re.compile(r'/index/position/([0-9]{15,25})/detail/?')


def read_request(method, url):
    """Only the observed public list POST, never a resume or apply endpoint."""
    try:
        p = urlsplit(url)
        return (method == 'POST' and p.scheme == 'https' and p.hostname == HOST
                and p.port in (None, 443) and p.username is None and p.password is None
                and p.path == SEARCH_PATH)
    except ValueError:
        return False


def official_board(html, career_url):
    """Select the social link by its official label; do not substitute campus."""
    candidates = []
    for node in Document(html).root.nodes():
        if node.tag != 'a' or '社会招聘' not in node.text():
            continue
        url = public_url(urljoin(career_url, node.attrs.get('href', '')))
        p = urlsplit(url)
        if p.hostname == HOST and p.path.rstrip('/') == '/index' and not p.query:
            candidates.append(url)
    candidates = list(dict.fromkeys(candidates))
    if len(candidates) != 1:
        raise SourceError('parse_error', 'MiniMax 官网未确认唯一的社会招聘入口；未替换为校招或人才计划')
    return candidates[0]


def search_url(board, term, page=1):
    # This query is emitted by the public search box (observed 2026-10-23).
    query = dict(keywords=term, category='', location='', project='', type='',
                 job_hot_flag='', current=page, limit=10, functionCategory='', tag='')
    return board + ('&' if '?' in board else '?') + urlencode(query)


def listing(html, board):
    doc = Document(html)
    result = []
    seen = set()
    for node in doc.root.nodes():
        if node.tag != 'a':
            continue
        url = public_url(urljoin(board, node.attrs.get('href', '')))
        p = urlsplit(url)
        identity = DETAIL_PATH.fullmatch(p.path)
        if p.hostname != HOST or not identity or url in seen:
            continue
        title = next((n for n in node.nodes() if n.attrs.get('data-test') == 'positionItem'), None)
        info = node.first(classes=('positionItem-subTitle',))
        if not title or not info or '社招' not in info.text():
            continue
        if node.attrs.get('data-id') not in (None, identity[1]):
            raise SourceError('identity_mismatch', 'MiniMax 职位链接与列表身份不符')
        seen.add(url)
        result.append(dict(url=url, title=title.text(), text=node.text(),
                           internship='实习' in info.text()))
    count = re.search(r'开启新的工作[（(](\d+)[）)]', doc.root.text())
    if not result:
        # A failed/blocked list request also renders the site's empty-state 0.
        # Without a successful response receipt it cannot prove zero vacancies.
        raise SourceError('blocked', 'MiniMax 公开页面未取得可核对的社招列表；空白或零计数不能证明无岗位')
    return result, int(count[1]) if count else None


def detail(html, url, expected_title=None):
    p = urlsplit(url)
    identity = DETAIL_PATH.fullmatch(p.path)
    if p.hostname != HOST or not identity:
        raise SourceError('identity_mismatch', 'MiniMax 详情地址不属于已确认的社招入口')
    doc = Document(html)
    box = doc.root.first(classes=('jobDetail',))
    heading = next((n for n in doc.root.nodes() if n.attrs.get('data-test') == 'jobTitle'), None)
    if not box or not heading:
        raise SourceError('parse_error', 'MiniMax 详情未显示完整职位正文')
    title = heading.text()
    if expected_title and re.sub(r'\s+', '', title) != re.sub(r'\s+', '', expected_title):
        raise SourceError('identity_mismatch', 'MiniMax 列表和详情的职位名称不一致')
    info = box.first(classes=('job-info',))
    if not info or '社招' not in info.text():
        raise SourceError('identity_mismatch', 'MiniMax 详情没有确认社会招聘类型')
    apply = next((n for n in box.nodes() if n.tag == 'button' and n.text() == '投递'), None)
    if not apply or 'disabled' in apply.attrs or apply.attrs.get('aria-disabled') == 'true':
        raise SourceError('parse_error', 'MiniMax 详情没有可用投递按钮，未确认当前仍在招')
    sections = {}
    label = None
    for node in box.children:
        if not isinstance(node, Node):
            continue
        classes = node.attrs.get('class', '').split()
        if 'block-title' in classes:
            label = node.text()
        elif 'block-content' in classes and label:
            sections[label] = node.prose().strip()
    description, requirements = sections.get('职位描述', ''), sections.get('职位要求', '')
    if len(description) < 40 or len(requirements) < 20:
        raise SourceError('parse_error', 'MiniMax 详情缺少完整职责或任职要求；未使用列表摘要替代')
    locations = [n.text() for n in info.children if isinstance(n, Node)]
    job = normalize('website', 'minimax:' + identity[1], title,
                    description + '\n\n任职要求\n' + requirements, url, 'MiniMax',
                    locations[0] if locations else None,
                    requirements_text=requirements, status='open')
    job['raw'].update(recruitment_type='社招',
                      employment_type='实习' if '实习' in info.text() else '全职' if '全职' in info.text() else None,
                      requires_public_browser=True)
    return job


def read_jobs(source, read, terms, limit, pages, report, renderer=None, html=None):
    """Bounded list + detail reads. Caller owns the renderer's request guard."""
    from .discovery import matches
    career = source['url']
    if html is None:
        html = read(career).decode('utf-8')
        report['pages'] += 1
    board = official_board(html, career)
    report.update(company='MiniMax', adapter='feishu_browser', search_url=board,
                  observed_entry_urls=[board], filter_scope='title_and_body')
    if not renderer:
        raise SourceError('needs_browser', 'MiniMax 社招需开启公开页面渲染；直接 HTTP 的 404 不代表入口失效')
    queries = list(dict.fromkeys(terms or ['']))[:min(pages, 3)]
    candidates = {}
    totals = {}
    for term in queries:
        url = search_url(board, term)
        response = renderer.read(url); report['pages'] += 1
        if response.get('status') != 200 or urlsplit(response.get('url', url)).hostname != HOST:
            raise SourceError('blocked', 'MiniMax 社招页面未能正常打开')
        try:
            rows, total = listing(response['body'].decode('utf-8'), board)
        except SourceError as error:
            report.setdefault('query_errors', []).append(dict(keyword=term, status=error.status, error=str(error)))
            continue
        totals[term] = total
        for row in rows:
            if matches(row['text'], terms):
                candidates[row['url']] = row
    report['source_totals'] = totals
    report['fetched'] += len(candidates)
    if not candidates:
        raise SourceError('blocked', 'MiniMax 本轮未取得可核对的匹配职位；保留搜索受阻信息，不作为零岗位')
    ordered = sorted(candidates.values(), key=lambda row: (
        row['internship'],
        not bool(re.search(r'开发|研发|工程师|架构师|engineer|developer', row['title'], re.I)),
        not matches(row['title'], terms)))
    count = 0
    for row in ordered[:pages]:
        response = renderer.read(row['url']); report['pages'] += 1
        try:
            if response.get('status') != 200:
                raise SourceError('blocked', 'MiniMax 职位详情没有正常打开')
            if response.get('url', row['url']).rstrip('/') != row['url'].rstrip('/'):
                raise SourceError('identity_mismatch', 'MiniMax 详情跳转到其他地址，未确认相同职位')
            job = detail(response['body'].decode('utf-8'), row['url'], row['title'])
        except SourceError as error:
            report.setdefault('detail_errors', []).append(dict(url=row['url'], status=error.status, error=str(error)))
            continue
        if not matches(job['title'] + ' ' + job['jd'], terms):
            continue
        attach_route(job, dict(career_url=career, observed_url=board, evidence_type='public_browser'))
        job['raw']['application_route'].update(
            entry_type='job_page', requires_public_browser=True,
            note='官网职位详情已核对；投递按钮后续的登录和表单需独立核验。')
        yield job; count += 1
        if count >= limit:
            break
    report['truncated'] = (len(candidates) > count or len(terms or []) > len(queries)
                           or any(total is None or total > 10 for total in totals.values()))
    if count == 0:
        raise SourceError('parse_error', 'MiniMax 找到列表但未取得可核对的完整详情')
