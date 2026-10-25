"""Moka (MokaHR) public careers API: app.mokahr.com and hire-r1.mokahr.com tenants.

Ported from career-ops providers/mokahr.mjs (https://github.com/career-ops-hq/career-ops,
commit f4d7477c8d25f81e6e4a952b724378913ea8c86e, MIT License). app.mokahr.com answers with an
AES-128-CBC envelope whose key (`necromancer`) ships in the same response; hire-r1.mokahr.com
sends plain JSON. Decryption needs the optional `cryptography` package (requirements-sources.txt).
Pages are requested one after another with the upstream's pause.
"""
import base64
import binascii
import json
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlsplit

from ..sources import SourceError, json_data, normalize
from . import Provider, paged_jobs, register

API_PATH = '/api/outer/ats-apply/website/jobs/v2'
# An allowlist, not *.mokahr.com: hire-r1-ats.mokahr.com is a static CDN. A tenant is unknown to the
# other deployment, so the API call goes to the tenant URL's own host.
ALLOWED_HOSTS = ('app.mokahr.com', 'hire-r1.mokahr.com')
# Identical across every tenant the upstream checked; a different IV would show as parse_error.
AES_IV = b'de7c21ed8d6f50fe'
MAX_LIMIT = 50
PAUSE = 0.4
TENANT_PATH_RE = re.compile(r'/(?:social-recruitment|campus-recruitment|apply)/([^/]+)/([0-9]+)/?')
# Exact paths excluded by app.mokahr.com/robots.txt (upstream, checked 2026-08-26); other routes are not.
ROBOTS_EXCLUDED_PATHS = frozenset(('/social-recruitment/lingjuninvest/46355', '/social-recruitment/shopee/74378'))
CST = timezone(timedelta(hours=8))
# Without an explicit zone the same string would mean different instants, so such dates are dropped.
ZONED = re.compile(r'.*(?:Z|[+-][0-9]{2}:[0-9]{2})', re.I | re.S)


def _tenant(value):
    """(origin, org, site id, base URL) for an allowed tenant URL, else None."""
    try: parts = urlsplit(value) if isinstance(value, str) else None
    except ValueError: return None
    if not parts or parts.scheme != 'https' or parts.netloc.lower() not in ALLOWED_HOSTS: return None
    match = TENANT_PATH_RE.fullmatch(parts.path)
    site = match and int(match.group(2))
    if not site or parts.path.rstrip('/') in ROBOTS_EXCLUDED_PATHS: return None
    origin = 'https://' + parts.netloc.lower()
    return origin, match.group(1), site, origin + parts.path.rstrip('/')


def _entry_tenant(entry):
    for key in ('careers_url', 'url'):
        tenant = _tenant(entry.get(key))
        if tenant: return tenant
    return None


def _decrypt(envelope):
    try:
        from cryptography.hazmat.primitives import padding
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    except ImportError as e:
        raise SourceError('not_configured', 'Moka 来源需要解密依赖 cryptography：请运行 python -m pip install -r requirements-sources.txt') from e
    data, key = envelope.get('data'), envelope.get('necromancer')
    if not isinstance(data, str) or not isinstance(key, str) or len(key.encode('utf-8')) != 16:
        raise SourceError('parse_error', 'Moka 响应缺少 data/necromancer，或密钥长度不是 16 字节')
    try:
        decryptor = Cipher(algorithms.AES(key.encode('utf-8')), modes.CBC(AES_IV)).decryptor()
        padded = decryptor.update(base64.b64decode(data, validate=True)) + decryptor.finalize()
        unpadder = padding.PKCS7(128).unpadder()
        return json.loads((unpadder.update(padded) + unpadder.finalize()).decode('utf-8'))
    except (ValueError, binascii.Error) as e:
        raise SourceError('parse_error', 'Moka 响应解密失败（IV 或加密方式可能已变化）') from e


def _page(raw):
    envelope = json_data(raw)
    if isinstance(envelope, dict) and envelope.get('success') is False:
        raise SourceError('fetch_error', 'Moka 接口返回错误：%s' % (envelope.get('msg') or envelope.get('code') or 'success=false'))
    # hire-r1 sends `data` as a JSON object, app.mokahr.com as a ciphertext string.
    data = envelope.get('data') if isinstance(envelope, dict) else None
    body = envelope if isinstance(data, dict) else _decrypt(envelope) if isinstance(envelope, dict) else None
    inner = body.get('data') if isinstance(body, dict) else None
    posts = inner.get('jobs') if isinstance(inner, dict) else None
    if not isinstance(posts, list): raise SourceError('parse_error', 'Moka 岗位列表结构变化')
    return posts


def _posted(value):
    text = value.strip() if isinstance(value, str) else ''
    if not ZONED.fullmatch(text): return None
    try: return datetime.fromisoformat(re.sub('z$', '+00:00', text, flags=re.I)).astimezone(CST).date().isoformat()
    except ValueError: return None


def _job(row, tenant, company):
    origin, org, site, base = tenant
    if not isinstance(row, dict) or row.get('id') in (None, '') or not row.get('title'):
        raise SourceError('parse_error', 'Moka 岗位缺少稳定 ID 或名称')
    ident = str(row['id'])
    try: encoded = quote(ident, safe='')
    except UnicodeError as e: raise SourceError('parse_error', 'Moka 岗位 ID 无法编码') from e
    locations = row.get('locations')
    location = '/'.join(p for p in (' '.join(str(l[k]) for k in ('provinceName', 'cityName') if l.get(k))
                                   for l in locations if isinstance(l, dict)) if p) if isinstance(locations, list) else ''
    department = row.get('department')
    department = department.get('name') if isinstance(department, dict) else None
    jd = '\n'.join(str(part) for part in (
        row.get('commitment') and '类型: %s' % row['commitment'], department and '部门: %s' % department,
        row.get('jobDescription')) if part)
    # The tenant frontend routes a posting through its hash router; job_fragment() keeps this exact form.
    return normalize('mokahr', '%d:%s' % (site, ident), row['title'], jd, '%s#/job/%s' % (base, encoded), company, location or None,
                     status='open', published_at=_posted(row.get('createdAt')), raw=dict(source_kind='mokahr', record=row))


def _row_id(row):
    return str(row['id']) if isinstance(row, dict) and row.get('id') not in (None, '') else None


def detect(entry):
    return dict(entry, kind='mokahr') if _entry_tenant(entry) else None


def fetch(entry, ctx):
    # An explicit kind skips detect(), so the host and path checks are repeated here.
    tenant = _entry_tenant(entry)
    if not tenant:
        raise SourceError('not_configured', 'Moka 来源需要 app.mokahr.com 或 hire-r1.mokahr.com 的 HTTPS 招聘页链接'
                          '（/social-recruitment、/campus-recruitment 或 /apply 加机构名与数字站点 ID，且不在 robots 禁止的页面内）')
    origin, org, site, _ = tenant
    api, first = origin + API_PATH, True
    company = entry.get('company') or org
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}

    def fetch_page(term, page):
        nonlocal first
        if not ctx.report['search_url']: ctx.report['search_url'] = api
        if not first and PAUSE: time.sleep(PAUSE)
        first = False
        body = dict(siteId=site, orgId=org, locale='zh-CN', limit=MAX_LIMIT, offset=(page - 1) * MAX_LIMIT)
        if term: body['keyword'] = term
        posts = _page(ctx.read(api, method='POST', data=json.dumps(body, ensure_ascii=False).encode('utf-8'), headers=headers))
        # No reliable total (jobStats.total stays 0): a full page means there may be more, a short page ends the board.
        return posts, (page * MAX_LIMIT + 1 if len(posts) >= MAX_LIMIT else 0)
    return paged_jobs(ctx, fetch_page, lambda row: _job(row, tenant, company), _row_id, MAX_LIMIT)


PROVIDER = register(Provider('mokahr', fetch, detect))
