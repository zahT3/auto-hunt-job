"""Bookmarklet inbox rules. Captured pages are untrusted text: stored as data, never interpreted."""
import hashlib
import hmac
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from .sources import SourceError, normalize, now, public_url

MAX_BODY = 200 * 1024
MAX_TEXT = 100000
ALLOWED_DOMAINS = ('zhipin.com', 'liepin.com', 'lagou.com', 'zhaopin.com', '51job.com', 'mokahr.com',
                   'jobs.feishu.cn', 'jobs.bytedance.com')
# Per-visit tracking only; parameters that may carry the job id (jobid, id, positionId...) stay.
TRACKING = {'spm', 'from', 'ka', 'lid', 'securityid', 'sessionid', 'scene', 'gclid', 'fbclid', 'ref', '_from', 'trk'}
TRACKING_PREFIXES = ('utm_', 'd_')


def _origin_host(origin):
    """Hostname of a plain https origin (no port other than 443, path, or credentials), else None."""
    if not isinstance(origin, str) or len(origin) > 300 or not origin.startswith('https://'):
        return None
    try:
        parts = urlsplit(origin)
        port = parts.port
    except ValueError:
        return None
    if parts.path or parts.query or parts.fragment or parts.username is not None or parts.password is not None or port not in (None, 443):
        return None
    host = (parts.hostname or '').rstrip('.').lower()
    if not host or origin != 'https://' + parts.netloc:
        return None
    return host


def is_https_origin(origin):
    return _origin_host(origin) is not None


def is_listed_origin(origin):
    host = _origin_host(origin)
    return bool(host) and any(host == d or host.endswith('.' + d) for d in ALLOWED_DOMAINS)


def token_ok(expected, given):
    if not isinstance(given, str) or not given: return False
    return hmac.compare_digest(expected.encode(), given.encode())


def clean_url(url):
    url = public_url(url)
    if not url: return ''
    p = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
             if k.lower() not in TRACKING and not k.lower().startswith(TRACKING_PREFIXES)]
    # Host case, a trailing dot and an explicit :443 must not split one job into two identities.
    host = p.hostname.rstrip('.')
    return urlunsplit((p.scheme, '[%s]' % host if ':' in host else host, p.path, urlencode(query), p.fragment))


def _text(value, limit, what):
    if value is None: return ''
    if not isinstance(value, str): raise SourceError('parse_error', what + '必须是文本')
    return value.strip()[:limit]


def normalize_payload(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get('extracted'), dict):
        raise SourceError('parse_error', '书签载荷需要 platform、url 与 extracted')
    extracted = payload['extracted']
    platform = payload.get('platform')
    if not isinstance(platform, str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,39}', platform):
        raise SourceError('parse_error', 'platform 无效')
    url = clean_url(payload.get('url') if isinstance(payload.get('url'), str) else '')
    if not url:
        raise SourceError('parse_error', '岗位链接必须是无凭据的公开 HTTPS 链接')
    title = _text(extracted.get('job_title'), 500, '岗位名称') or _text(payload.get('page_title'), 500, '页面标题')
    if not title:
        raise SourceError('parse_error', '缺少岗位名称')
    text = _text(extracted.get('raw_text'), MAX_TEXT, '页面正文')
    if not text:
        raise SourceError('parse_error', '缺少页面正文')
    salary = _text(extracted.get('salary'), 100, '薪资')
    return normalize('inbox:' + platform, hashlib.sha1(url.encode()).hexdigest()[:16], title, text, url,
                     _text(extracted.get('company'), 200, '公司') or None, _text(extracted.get('location'), 200, '地点') or None,
                     salary=salary or None, status='unverified',
                     raw=dict(source_kind='inbox', source_url=url, platform=platform, received_at=now()))
