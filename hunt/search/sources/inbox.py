"""Bookmarklet inbox rules. Captured pages are untrusted text: stored as data, never interpreted."""
import hashlib
import hmac
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from ..parse import SourceError, normalize, now, public_url

MAX_BODY = 200 * 1024
MAX_TEXT = 100000
ALLOWED_DOMAINS = ('zhipin.com', 'liepin.com', 'lagou.com', 'zhaopin.com', '51job.com', 'mokahr.com',
                   'jobs.feishu.cn', 'jobs.bytedance.com')
# Per-visit tracking only; parameters that may carry the job id (jobid, id, positionId...) stay.
TRACKING = {'spm', 'from', 'ka', 'lid', 'securityid', 'sessionid', 'scene', 'gclid', 'fbclid', 'ref', '_from', 'trk'}
TRACKING_PREFIXES = ('utm_', 'd_')
# 猎聘 job links carry per-visit search state in the query (skId, ckId, index...); the path alone names the job, so a
# search-results card and the same job's detail page land on one record.
LIEPIN_JOB = re.compile(r'/(?:job|a)/\d+\.shtml')


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
    # Host case, a trailing dot and an explicit :443 must not split one job into two identities.
    host = p.hostname.rstrip('.')
    query = [] if (host == 'liepin.com' or host.endswith('.liepin.com')) and LIEPIN_JOB.fullmatch(p.path) else \
        [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if k.lower() not in TRACKING and not k.lower().startswith(TRACKING_PREFIXES)]
    return urlunsplit((p.scheme, '[%s]' % host if ':' in host else host, p.path, urlencode(query), p.fragment))


def _text(value, limit, what):
    if value is None: return ''
    if not isinstance(value, str): raise SourceError('parse_error', what + '必须是文本')
    return value.strip()[:limit]


# Structured fields a bookmarklet may send next to the page text (the BOSS bookmarklet reads them from the page's
# own job data). Only these keys are kept; anything else, notably the recruiter's name, title and online status,
# is dropped. Values: (type, max length).
STRUCTURED = {'brandName': (str, 200), 'salaryDesc': (str, 100), 'jobExperience': (str, 50), 'jobDegree': (str, 50),
              'cityName': (str, 50), 'skills': (list, 50)}
# Kept verbatim in raw for later use, not used for filtering yet: goldHunter (the source's 0/1 headhunter flag) and
# the recruiter account's activity wording ("本周活跃"), which describes the posting, not a person's identity.
STRUCTURED_RAW = {'goldHunter': (int, None), 'bossActiveTimeDesc': (str, 50)}
MAX_SKILLS = 30


def _structured(value):
    if value is None: return {}
    if not isinstance(value, dict): raise SourceError('parse_error', '结构化字段必须是对象')
    out = {}
    for key, (kind, limit) in {**STRUCTURED, **STRUCTURED_RAW}.items():
        v = value.get(key)
        if v is None or v == '': continue
        if kind is list:
            if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
                raise SourceError('parse_error', key + ' 必须是文本列表')
            v = list(dict.fromkeys(x.strip()[:limit] for x in v if x.strip()))[:MAX_SKILLS]
        elif kind is int:
            if isinstance(v, bool): v = int(v)
            if not isinstance(v, int) or v not in (0, 1): raise SourceError('parse_error', key + ' 必须是 0 或 1')
        else:
            if not isinstance(v, str): raise SourceError('parse_error', key + ' 必须是文本')
            v = v.strip()[:limit]
        if v != '' and v != []: out[key] = v
    return out


def _modified(value):
    """lastModifyTime as the source gave it (epoch ms or text): its own "last modified" claim, never a posting date."""
    if value is None or value == '': return None
    if isinstance(value, bool) or not isinstance(value, (int, str)) or (isinstance(value, str) and len(value) > 40):
        raise SourceError('parse_error', 'lastModifyTime 必须是数字或短文本')
    return dict(field='lastModifyTime', value=value)


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
    fields = _structured(payload.get('structured'))
    given = payload.get('structured')
    modified = _modified(given.get('lastModifyTime') if isinstance(given, dict) else None)
    title = _text(extracted.get('job_title'), 500, '岗位名称') or _text(payload.get('page_title'), 500, '页面标题')
    if not title:
        raise SourceError('parse_error', '缺少岗位名称')
    text = _text(extracted.get('raw_text'), MAX_TEXT, '页面正文')
    if not text:
        raise SourceError('parse_error', '缺少页面正文')
    salary = _text(extracted.get('salary'), 100, '薪资') or fields.get('salaryDesc', '')
    company = _text(extracted.get('company'), 200, '公司') or fields.get('brandName', '')
    place = _text(extracted.get('location'), 200, '地点') or fields.get('cityName', '')
    summary = payload.get('summary_only') is True
    raw = dict(source_kind='inbox', source_url=url, platform=platform, received_at=now(),
               **({'summary_only': True, 'capture': 'list'} if summary else {}),
               **({'structured': fields} if fields else {}), **({'source_modified': modified} if modified else {}))
    extra = dict(experience=fields['jobExperience']) if fields.get('jobExperience') else {}
    return normalize('inbox:' + platform, hashlib.sha1(url.encode()).hexdigest()[:16], title, text, url,
                     company or None, place or None, salary=salary or None, status='unverified', raw=raw, **extra)
