"""Employer-specific public readers. Only observed resources and job links."""
import json
import re
from urllib.parse import urljoin, urlsplit, urldefrag
from .sources import Document, SourceError, normalize, public_url, jd_text, now, json_data
from .careers import attach_route


def embedded_json(script):
    # Decode a literal passed to JSON.parse; no JavaScript interpreter or eval.
    for m in re.finditer(r"JSON\.parse\('((?:\\.|[^'\\])*)'\)", script):
        def escape(match):
            token = match[1]
            if token == "'": return "'"
            if token in ('\n', '\r\n'): return ''
            return json.loads('"\\' + token + '"')
        try:
            text = re.sub(r'\\(u[0-9a-fA-F]{4}|\r\n|.|\n)', escape, m[1])
            data = json.loads(text)
        except (ValueError, TypeError): continue
        if isinstance(data, dict) and isinstance(data.get('jobs'), list): return data
    raise SourceError('parse_error', '官网脚本未提供可识别的公开岗位数据')


def reference(career, observed, kind='link'):
    return dict(career_url=career, observed_url=observed, evidence_type=kind)


def scripts(html, url):
    return list(dict.fromkeys(public_url(urljoin(url, n.attrs['src'])) for n in Document(html).root.nodes()
                             if n.tag == 'script' and n.attrs.get('src')))


def links(html, url):
    return [(public_url(urljoin(url, n.attrs.get('href', ''))), n.text()) for n in Document(html).root.nodes() if n.tag == 'a' and n.attrs.get('href')]


def read_jobs(source, read, terms, limit, pages, report, renderer=None):
    from .catalog import lookup
    from .discovery import matches, _api
    entry = lookup(source['url'])
    if not entry: return
    name, url = entry['id'], source['url']; report['company'] = entry['company']; report['adapter'] = entry['adapter']
    report['search_url'] = url
    if name == 'imtoken':
        from .imtoken import read_jobs as read_imtoken
        yield from read_imtoken(source, read, terms, limit, pages, report, renderer=renderer)
        return
    html = read(url).decode('utf-8'); report['pages'] += 1
    def emit(rows):
        selected = [r for r in rows if matches(r['title'] + ' ' + r['jd'], terms)]
        selected.sort(key=lambda r: (not matches(r['title'], terms), not bool(re.search(r'开发|研发|工程师|engineer|developer|backend', r['title'], re.I))))
        report['filter_scope'] = 'title_and_body'
        report['fetched'] += len(rows); report['truncated'] = len(selected) > limit
        return selected[:limit]
    if name == 'minimax':
        from .minimax import read_jobs as read_minimax
        yield from read_minimax(source, read, terms, limit, pages, report, renderer, html=html)
    elif name == 'deepseek':
        resources = [u for u in scripts(html, url) if urlsplit(u).hostname == 'talent.deepseek.com' and '/static/main.' in u]
        if not resources: raise SourceError('parse_error', 'DeepSeek 页面脚本关联已变化')
        data = embedded_json(read(resources[0]).decode('utf-8')); report['pages'] += 1
        rows = []
        for row in data['jobs']:
            detail, apply = public_url(row.get('detailUrl', '')), public_url(row.get('submitUrl', ''))
            if urlsplit(detail).hostname != 'app.mokahr.com' or '/job/' + str(row.get('id')) not in detail: continue
            if apply != detail + '/apply': raise SourceError('parse_error', 'DeepSeek 申请地址与职位身份不一致')
            job = normalize('website', 'deepseek:' + row['id'], row['title'], row['descriptionHtml'], detail,
                entry['company'], ' / '.join(row.get('locations', [])), application_url=apply)
            attach_route(job, reference(url, resources[0], 'embedded_json'))
            job['raw']['source_snapshot_at'] = data.get('crawledAt')
            rows.append(job)
        yield from emit(rows)
    elif name == 'dify':
        urls = re.findall(r'https://[A-Za-z0-9.-]+\.supabase\.co/functions/v1/public-jobs\?lang=[a-z]+', html)
        if not urls: raise SourceError('parse_error', 'Dify 公开岗位接口关联已变化')
        data = json_data(read(urls[0])); report['pages'] += 1
        emails = re.findall(r'href=["\x27]mailto:([^?"\x27]+)', html)
        if 'joinus@dify.ai' not in emails: raise SourceError('parse_error', 'Dify 招聘邮箱未从页面核实')
        rows = []
        for row in data.get('jobs', []):
            job = normalize('website', 'dify:' + row['id'], row['title'], row['content'], url, entry['company'], row.get('location'))
            attach_route(job, reference(url, urls[0], 'public_json'))
            job['raw']['application_route'].update(entry_type='email', email='joinus@dify.ai', note='官网公开招聘邮箱；没有网页申请表单。')
            rows.append(job)
        yield from emit(rows)
    elif name == 'okx':
        resources = [u for u in scripts(html, url) if urlsplit(u).hostname == 'www.okx.com' and '/assistance/openings/' in u]
        if not resources: raise SourceError('parse_error', 'OKX 招聘脚本引用已变化')
        script = read(resources[0]).decode('utf-8'); report['pages'] += 1
        match = re.search(r'https://boards\.greenhouse\.io/([A-Za-z0-9_-]+)/jobs/', script)
        if not match: raise SourceError('parse_error', 'OKX 官网未找到明确的招聘看板引用')
        child = dict(pages=0, fetched=0, truncated=False, search_url=None)
        try:
            for job in _api(dict(kind='greenhouse', board=match[1], company=entry['company']), read, terms, limit, pages, child):
                yield attach_route(job, reference(url, resources[0], 'embedded_url'))
        finally:
            report['pages'] += child['pages']; report['fetched'] += child['fetched']; report['truncated'] = child['truncated']
    elif name in ('kimi', 'stepfun', 'cobo'):
        candidates = [u for u, text in links(html, url) if urlsplit(u).hostname in ('app.mokahr.com', 'hire-r1.mokahr.com') and ('social-recruitment/' in u or '/apply/' in u)]
        if not candidates and name == 'stepfun':
            for resource in scripts(html, url)[:2]:
                if urlsplit(resource).hostname != urlsplit(url).hostname: continue
                script = read(resource).decode('utf-8'); report['pages'] += 1
                candidates.extend(re.findall(r'https://app\.mokahr\.com/social-recruitment/step/\d+', script))
        if not candidates and renderer:
            rendered = renderer.read(url); html = rendered['body'].decode(); report['pages'] += 1
            candidates = [u for u, _ in links(html, url) if urlsplit(u).hostname == 'app.mokahr.com' and '/apply/' in u]
        if not candidates: raise SourceError('needs_browser', '官网招聘按钮需要公开页面渲染；请开启公开页面渲染后重试')
        board = candidates[0]; p = urlsplit(board)
        match = re.match(r'/(social-recruitment|apply)/([A-Za-z0-9_-]+)/(\d+)', p.path)
        if not match: raise SourceError('parse_error', 'Moka 看板引用结构变化')
        mode, org, site = match.groups(); base = 'https://' + p.hostname; board = base + match[0]
        payload = dict(orgId=org, siteId=int(site), limit=50, offset=0, needStat=True, locale='zh_CN', site='social')
        data = json_data(read(base + '/api/outer/ats-apply/website/jobs/v2', method='POST', data=json.dumps(payload).encode(), headers={'Content-Type':'application/json'})); report['pages'] += 1
        if isinstance(data.get('data'), str):
            if not renderer: raise SourceError('needs_browser', 'Moka 返回加密页面数据；需开启公开页面渲染，不作为零岗位')
            rendered = renderer.read(board + '#/jobs'); report['pages'] += 1
            job_links = list(dict.fromkeys(u for u, text in links(rendered['body'].decode(), board) if urldefrag(u)[0] == board and re.fullmatch(r'/job/[a-f0-9-]+', urlsplit(u).fragment) and matches(text, terms)))
            if not job_links: raise SourceError('blocked', '公开渲染未取得 Moka 职位链接；没有绕过登录或验证')
            report['fetched'] = len(job_links); count = 0
            # Read actual details, bounded by requested pages (5 details maximum).
            for link in job_links[:pages]:
                detail = renderer.read(link); report['pages'] += 1
                try: job = moka_dom(detail['body'].decode(), link, org, entry['company'])
                except SourceError as error:
                    report.setdefault('detail_errors', []).append(dict(url=link, status=error.status, error=str(error)))
                    continue
                if matches(job['title'] + ' ' + job['jd'], terms):
                    yield attach_route(job, reference(url, candidates[0])); count += 1
                    if count >= limit: break
            report['truncated'] = len(job_links) > min(pages, count)
        else:
            content = data.get('data', data)
            if not isinstance(content, dict) or not isinstance(content.get('jobs'), list): raise SourceError('parse_error', 'Moka 公开列表结构变化')
            rows = []
            for r in content['jobs']:
                if r.get('status') not in (None, 'opened', 'open', 'OPEN', 'published', 1): continue
                detail = board + '#/job/' + r['id']
                locations = [' '.join(str(loc.get(k) or '') for k in ('country','provinceName','cityName')).strip() for loc in r.get('locations', [])]
                job = normalize('website', org + ':' + r['id'], r['title'], r.get('jobDescription'), detail, entry['company'], ' / '.join(locations), application_url=detail + '/apply')
                rows.append(attach_route(job, reference(url, candidates[0])))
            yield from emit(rows)
            report['truncated'] |= content.get('jobStats', {}).get('total', 0) > len(content['jobs'])
    elif name in ('hashkey', 'imtoken'):
        if name == 'imtoken':
            observed = next((u for u, t in links(html, url) if t == 'View openings' and urlsplit(u).hostname == urlsplit(url).hostname), None)
            if observed:
                url = observed; html = read(url).decode(); report['pages'] += 1
            candidates = [(u,t) for u,t in links(html,url) if urlsplit(u).hostname == 'careers.token.im' and re.search(r'engineer|developer|manager|designer', urlsplit(u).path, re.I)]
        else:
            candidates = [(u,t) for u,t in links(html,url) if t.lower() == 'apply now' and urlsplit(u).hostname == 'group.hashkey.com' and '/quick-apply' not in u]
        candidates = list(dict.fromkeys(candidates)); report['fetched'] = len(candidates); count = 0
        for link, _ in candidates[:pages]:
            detail = read(link).decode(); report['pages'] += 1; doc = Document(detail)
            title = doc.root.first(tags=('h1','h2')); article = doc.root.first(tags=('article', 'main'))
            if name == 'hashkey':
                heading = next((n for n in doc.root.nodes() if n.tag == 'h3' and n.text().lower() == 'job description'), None)
                if heading and heading.parent and heading.parent.parent: article = heading.parent.parent
            if not title or not article: raise SourceError('parse_error', '官网职位标题或正文结构变化')
            location = None
            if name == 'hashkey' and title.parent and title.parent.parent:
                header = title.parent.parent.text()
                location = next((place for place in ('Hong Kong','Singapore','Tokyo','London','Dubai','Shanghai','Beijing','Shenzhen') if place in header), None)
            job = normalize('website', name + ':' + urlsplit(link).path.strip('/'), title.text(), article.prose(), link, entry['company'], location)
            attach_route(job, reference(source['url'], link))
            emails = re.findall(r'href=["\x27]mailto:([^?"\x27]+)', detail)
            if name == 'imtoken' and 'hr@token.im' in emails: job['raw']['application_route'].update(entry_type='email', email='hr@token.im')
            if matches(job['title'] + ' ' + job['jd'], terms):
                yield job; count += 1
                if count >= limit: break
        report['truncated'] = len(candidates) > min(pages, count)
        if not candidates: raise SourceError('parse_error', '官网职位列表结构未能识别；不是零岗位')
    else:
        targets = [u for u,_ in links(html,url) if urlsplit(u).hostname and urlsplit(u).hostname.endswith('.jobs.feishu.cn')]
        report['observed_entry_urls'] = targets[:3]
        if targets: read(targets[0])  # A broken official entry is reported, not hidden.
        raise SourceError('unsupported', '官网已定位；此招聘系统尚未完成正文适配，不计为已接通')


def moka_dom(html, url, org, company):
    doc = Document(html)
    titles = [n for n in doc.root.nodes() if any(c.startswith('title-') for c in n.attrs.get('class','').split())]
    heading = titles[0] if titles else doc.root.first(tags=('h1','h2'))
    description_label = next((n for n in doc.root.nodes() if n.text() == '职位描述'), None)
    description = description_label.parent if description_label else None
    content = next((n for n in description.nodes() if n.tag == 'div' and 'job-description' in n.attrs.get('class', '')), None) if description else None
    text = (content or description).prose().replace('职位描述', '').strip() if description else ''
    if not heading or len(re.sub(r'暂无|\s', '', text)) < 40:
        raise SourceError('parse_error', 'Moka 页面有职位入口，但没有完整岗位正文；不以列表文字代替 JD')
    lines = text.splitlines()
    text = '\n'.join(dict.fromkeys(line.strip() for line in lines if line.strip()))
    return normalize('website', org + ':' + urlsplit(url).fragment.rsplit('/',1)[-1], heading.text(), text, url, company, application_url=url+'/apply')
