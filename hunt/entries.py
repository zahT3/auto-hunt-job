"""Bounded read-only entry checks and evidence-bound alternate receiver repair."""
import re
from urllib.parse import urlsplit, urljoin
from .sources import Document, public_url, now
from .network import FetchError


def title_key(value):
    return re.sub(r'[^\w\u4e00-\u9fff]+', '', str(value).casefold())


def official_job_link(html, career_url, title):
    expected = title_key(title)
    candidates = set()
    for node in Document(html).root.nodes():
        if node.tag != 'a' or not any(title_key(child.text()) == expected for child in node.nodes()): continue
        url = public_url(urljoin(career_url, node.attrs.get('href', '')))
        if url and urlsplit(url).hostname == urlsplit(career_url).hostname and urlsplit(url).path != urlsplit(career_url).path:
            candidates.add(url)
    return next(iter(candidates)) if len(candidates) == 1 else None


def inspect(job, url, response):
    if isinstance(response, bytes): response = dict(body=response, url=url, status=200)
    if response.get('observation') is not None and 200 <= response.get('status',200) < 300:
        from .moka_session import classify
        return classify(job, response.get('url',url), response['observation'], blocked_reads=response.get('incomplete_reads',False))
    final_url, status = response.get('url', url), response.get('status', 200)
    result = dict(url=url, final_url=final_url, http_status=status, checked_at=now(), method='public_render' if response.get('rendered') else 'public_http')
    html = response['body'].decode('utf-8', errors='replace'); doc = Document(html)
    source_id = str(job.get('platform_id') or '').rsplit(':', 1)[-1]
    result['source_id_seen'] = bool(source_id and source_id in html)
    headings = [n.text() for n in doc.root.nodes() if n.tag in ('h1', 'h2', 'title')]
    soft404 = any(re.fullmatch(r'.{0,20}(page not found|404|页面不存在|职位不存在|职位已关闭|job (?:not found|closed)).{0,25}', s, re.I) for s in headings)
    if status in (404,410) or soft404:
        result['status'] = 'not_found'
    elif status in (401,403,429): result['status'] = 'blocked'
    elif not 200 <= status < 300: result['status'] = 'check_failed'
    elif re.search(r'/(?:login|signin|sign-in|user/login)(?:/|\?|$)', final_url, re.I): result['status'] = 'login_required'
    elif any(re.search(r'安全验证|请完成验证|captcha|verify you are human', s, re.I) for s in headings): result['status'] = 'captcha'
    elif urlsplit(final_url).hostname in ('app.mokahr.com', 'hire-r1.mokahr.com') and urlsplit(final_url).fragment.endswith('/apply') and '请先登录' in doc.root.text():
        result['status'] = 'login_required'
    else:
        role_headings = [n.text() for n in doc.root.nodes() if n.tag in ('h1','h2') or n.attrs.get('data-test') == 'jobTitle' or any(c.startswith('title-') for c in n.attrs.get('class','').split())]
        identity = any(title_key(h) == title_key(job['title']) for h in role_headings)
        if not identity:
            result['status'] = 'identity_mismatch' if role_headings else 'needs_browser'
        else:
            forms = [n for n in doc.root.nodes() if n.tag == 'form']
            form = any(any(n.tag == 'input' and (n.attrs.get('type') == 'file' or 'resume' in n.attrs.get('name','').lower()) for n in f.nodes()) for f in forms)
            result['status'] = 'form_seen' if form else 'job_page_seen'
            result['identity'] = 'exact_role_heading'
    return result


def check_job(job, read, renderer=None):
    route = job.setdefault('raw', {}).setdefault('application_route', {})
    url = job.get('application_url') or job['url']
    if route.get('entry_type') == 'email':
        route['entry_check'] = dict(url=url, checked_at=now(), status='email_only', email=route.get('email'), method='source_observation')
        return job
    def check(target):
        try:
            result = inspect(job, target, read(target, with_metadata=True))
            public_browser = isinstance(job.get('raw'),dict) and job['raw'].get('requires_public_browser')
            if renderer and (result['status'] in ('needs_browser','identity_mismatch') or public_browser and result['status'] in ('not_found','blocked','check_failed')):
                result = inspect(job, target, renderer.read(target))
            return result
        except FetchError as error:
            if renderer:
                try: return inspect(job, target, renderer.read(target))
                except ValueError as rendered_error:
                    if getattr(rendered_error, 'status', None) == 'cancelled': raise
                    error = rendered_error
            return dict(url=target, status=getattr(error, 'status', 'check_failed'), checked_at=now(), error=str(error)[:300], method='public_read')
        except ValueError as error:
            if getattr(error, 'status', None) == 'cancelled': raise
            if getattr(error, 'status', None) == 'budget_exhausted': return dict(url=target, status='budget_exhausted', checked_at=now())
            return dict(url=target, status='check_failed', checked_at=now(), error=str(error)[:300], method='public_read')
    primary = check(url)
    alternate = route.get('official_job_url')
    if primary['status'] != 'form_seen' and alternate and public_url(alternate) and alternate != url:
        # This alternate was observed as a unique exact-title link on the source
        # page. A generic careers page can never qualify as a repaired receiver.
        repaired = check(alternate)
        if repaired['status'] == 'form_seen' and job.get('platform_id') and not repaired.get('source_id_seen'):
            repaired['status'] = 'identity_unconfirmed'
        if repaired['status'] == 'form_seen':
            route.update(original_application_url=url, repair=dict(reason='official_same_role_form', previous_check=primary, checked_at=now()), entry_check=repaired)
            job['application_url'] = alternate
            route['application_url'] = alternate
            return job
        route['alternate_check'] = repaired
    route['entry_check'] = primary
    return job
