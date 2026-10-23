"""Discover employer ATS references without executing page scripts or applications."""
import re
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin, urlsplit
from .sources import Document, at_board, public_url, now

ATS_HOSTS = {'boards.greenhouse.io': 'greenhouse', 'job-boards.greenhouse.io': 'greenhouse',
             'jobs.lever.co': 'lever', 'jobs.ashbyhq.com': 'ashby'}


def linked_boards(html, page_url):
    """Only observed anchor/iframe or embedded HTTPS ATS URLs; never guess slugs."""
    doc = Document(html)
    references = [(urljoin(page_url, n.attrs.get('href') or n.attrs.get('src') or ''), 'link')
                  for n in doc.root.nodes() if n.tag in ('a', 'iframe')]
    # Next.js server payloads may contain explicit jobUrl/applyUrl strings. Read
    # references only, never eval or copy their descriptions into verified JDs.
    for n in doc.root.nodes():
        if n.tag == 'script':
            text = ''.join(c for c in n.children if isinstance(c, str)).replace('\\/', '/')
            references.extend((u, 'embedded_url') for u in re.findall(
                r'https://(?:job-boards\.greenhouse\.io|boards\.greenhouse\.io|jobs\.lever\.co|jobs\.ashbyhq\.com)/[^\s<>"\x27\\]+', text))
    result, seen = [], set()
    for url, evidence_type in references:
        url = public_url(url)
        p = urlsplit(url)
        kind = ATS_HOSTS.get(p.hostname)
        parts = p.path.split('/')
        if not kind or len(parts) < 2: continue
        try: board = at_board(kind, parts[1])
        except ValueError: continue
        if (kind, board) in seen: continue
        seen.add((kind, board))
        result.append(dict(kind=kind, board=board, board_url='https://' + p.hostname + '/' + board,
                           career_url=page_url, observed_url=url, evidence_type=evidence_type))
    return result[:3]


def attach_route(job, reference):
    """Evidence describes a source-page relation, not ownership or submission success."""
    job.setdefault('raw', {})['application_route'] = dict(reference,
        status='careers_linked', application_url=job.get('application_url') or job['url'],
        checked_at=now(), note='招聘页明确引用此招聘看板；已从看板读取岗位正文。申请表单尚需核验。')
    return job


def preserve_entry_check(previous_raw, incoming_raw, application_url):
    """Keep a recent observation for the same receiver through source refreshes."""
    if not isinstance(previous_raw, dict) or not isinstance(incoming_raw, dict): return incoming_raw
    route = previous_raw.get('application_route') or {}
    if not isinstance(route, dict): return incoming_raw
    check = route.get('entry_check')
    if not isinstance(check, dict) or check.get('url') != application_url: return incoming_raw
    try:
        observed = datetime.fromisoformat(check['checked_at'].replace('Z', '+00:00'))
        if observed.tzinfo is None: return incoming_raw
        age = datetime.now(timezone.utc) - observed
        if not timedelta(0) <= age < timedelta(hours=24): return incoming_raw
    except (KeyError, ValueError, TypeError): return incoming_raw
    incoming_route = incoming_raw.setdefault('application_route', {})
    if isinstance(incoming_route, dict):
        incoming_check = incoming_route.get('entry_check') or {}
        if check.get('status') in ('not_found', 'form_seen', 'login_required') and incoming_check.get('status') in ('needs_browser', 'check_failed', 'budget_exhausted'):
            incoming_route['entry_check'] = dict(check)
        else: incoming_route.setdefault('entry_check', dict(check))
    return incoming_raw
