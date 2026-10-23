"""Bounded HTTPS fetching with validated DNS and pinned TLS destinations.

No environment proxy or cookies are used. Reserved benchmark fake-DNS answers
used by some local VPNs are re-resolved via Cloudflare DoH before connecting.
"""
import http.client
import ipaddress
import json
import queue
import socket
import ssl
import threading
import time
from urllib.parse import urljoin, urlsplit

MAX_BYTES = 5 * 1024 * 1024
TIMEOUT = 25
MAX_REDIRECTS = 4
_FAKE_DNS = ipaddress.ip_network('198.18.0.0/15')


class FetchError(ValueError):
    pass


def validate_url(url):
    if not isinstance(url, str) or len(url) > 8192 or any(ord(c) < 33 for c in url):
        raise FetchError('公开 URL 无效')
    try:
        p = urlsplit(url)
        port = p.port
    except ValueError as e:
        raise FetchError('URL 端口或主机无效') from e
    if p.scheme.lower() != 'https' or not p.hostname or p.username is not None or p.password is not None:
        raise FetchError('只允许无凭据的公开 HTTPS URL')
    if port not in (None, 443) or '\\' in p.netloc or '%' in p.hostname:
        raise FetchError('只允许 HTTPS 443 端口与标准主机名')
    host = p.hostname.rstrip('.').lower()
    if host == 'localhost' or host.endswith(('.localhost', '.local', '.internal', '.home', '.lan')):
        raise FetchError('拒绝本机或内网主机')
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        try:
            host = host.encode('idna').decode('ascii')
        except UnicodeError as e:
            raise FetchError('主机名无效') from e
    else:
        if not _public(ip):
            raise FetchError('拒绝非公网地址')
    return p, host


def _public(ip):
    if isinstance(ip, str):
        ip = ipaddress.ip_address(ip)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        return _public(ip.ipv4_mapped)
    return ip.is_global and not ip.is_multicast and not ip.is_unspecified


class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, hostname, ip, timeout):
        super().__init__(hostname, 443, timeout=timeout, context=ssl.create_default_context())
        self.pinned_ip = ip

    def connect(self):
        sock = socket.create_connection((self.pinned_ip, 443), timeout=self.timeout)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


def _bounded_call(fn, timeout):
    result = queue.Queue(maxsize=1)
    def work():
        try:
            result.put((True, fn()))
        except BaseException as exc:
            result.put((False, exc))
    threading.Thread(target=work, daemon=True).start()
    try:
        ok, value = result.get(timeout=max(.01, timeout))
    except queue.Empty as exc:
        raise FetchError('DNS 解析超时') from exc
    if not ok:
        raise FetchError('DNS 解析失败：' + str(value))
    return value


def _doh(host, timeout):
    # Fixed public bootstrap endpoints. Only hostnames, never user materials, go
    # to the resolver. Each endpoint keeps normal IP SAN certificate validation.
    from urllib.parse import urlencode
    started = time.monotonic()
    failures = []
    for bootstrap in ('1.1.1.1', '1.0.0.1'):
        remaining = timeout - (time.monotonic() - started)
        if remaining <= 0:
            break
        conn = _PinnedHTTPS(bootstrap, bootstrap, min(remaining, 8))
        try:
            conn.request('GET', '/dns-query?' + urlencode({'name': host, 'type': 'A'}),
                         headers={'Accept': 'application/dns-json', 'User-Agent': 'auto-hunt-job/0.1'})
            response = conn.getresponse()
            if response.status != 200:
                raise FetchError('公开 DNS 解析失败')
            raw = response.read(65537)
            if len(raw) > 65536:
                raise FetchError('DNS 响应过大')
            data = json.loads(raw)
            if data.get('Status') != 0:
                raise FetchError('公开 DNS 未找到主机')
            return [a['data'] for a in data.get('Answer', []) if a.get('type') in (1, 28)]
        except (OSError, http.client.HTTPException, ValueError) as exc:
            failures.append(type(exc).__name__)
        finally:
            conn.close()
    raise FetchError('公开 DNS 解析失败：' + ', '.join(failures))


def resolve_public(host, timeout=TIMEOUT):
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        addresses = _bounded_call(lambda: list({a[4][0] for a in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}), timeout)
    else:
        addresses = [str(ip)]
    # Never whitelist the VPN synthetic destination. Resolve it independently.
    if addresses and all(ipaddress.ip_address(a) in _FAKE_DNS for a in addresses if ':' not in a) and all(':' not in a for a in addresses):
        addresses = _bounded_call(lambda: _doh(host, timeout), timeout)
    if not addresses or any(not _public(a) for a in addresses):
        raise FetchError('DNS 返回非公网地址，已拒绝请求')
    return addresses


def fetch(url, method='GET', data=None, headers=None, with_metadata=False):
    """Fetch bytes; all redirects repeat URL/DNS validation and pin the result."""
    method = method.upper()
    if method not in ('GET', 'POST', 'HEAD'):
        raise FetchError('不支持的公开检索请求方式')
    if data is not None and not isinstance(data, bytes):
        raise FetchError('请求正文必须是 bytes')
    if data is not None and len(data) > MAX_BYTES:
        raise FetchError('请求正文过大')
    request_headers = {'User-Agent': 'auto-hunt-job/0.1', 'Accept-Encoding': 'identity'}
    for k, v in (headers or {}).items():
        if k.lower() in ('host', 'cookie', 'authorization', 'proxy-authorization', 'connection', 'transfer-encoding', 'content-length'):
            raise FetchError('公开检索不允许认证或连接覆盖头')
        if '\r' in k + str(v) or '\n' in k + str(v):
            raise FetchError('请求头无效')
        request_headers[k] = str(v)
    started = time.monotonic()
    for redirect in range(MAX_REDIRECTS + 1):
        p, host = validate_url(url)
        remaining = TIMEOUT - (time.monotonic() - started)
        if remaining <= 0:
            raise FetchError('公开抓取超时')
        ips = resolve_public(host, remaining)
        remaining = TIMEOUT - (time.monotonic() - started)
        if remaining <= 0:
            raise FetchError('公开抓取超时')
        conn = _PinnedHTTPS(host, ips[0], remaining)
        # Shutdown at the overall deadline also bounds trickled HTTP headers/body.
        def abort():
            try:
                if conn.sock:
                    conn.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        timer = threading.Timer(remaining, abort)
        timer.daemon = True
        timer.start()
        try:
            path = p.path or '/'
            if p.query:
                path += '?' + p.query
            conn.request(method, path, body=data, headers=request_headers)
            response = conn.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader('Location')
                if not location or redirect == MAX_REDIRECTS:
                    raise FetchError('重定向缺少目标或次数过多')
                next_url = urljoin(url, location)
                np, nh = validate_url(next_url)
                if next_url == url: raise FetchError('重定向循环：目标地址未变化')
                if method == 'POST' and nh != host:
                    raise FetchError('拒绝向其他主机重定向 POST 正文')
                if response.status == 303 or response.status in (301, 302) and method == 'POST':
                    method, data = 'GET', None
                url = next_url
                continue
            if not with_metadata and (response.status < 200 or response.status >= 300):
                raise FetchError('公开请求 HTTP ' + str(response.status))
            if response.getheader('Content-Encoding', 'identity').lower() not in ('identity', ''):
                raise FetchError('不接受压缩响应，防止解压缩超限')
            length = response.getheader('Content-Length')
            if length and int(length) > MAX_BYTES:
                raise FetchError('公开响应过大')
            raw = response.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise FetchError('公开响应过大')
            if time.monotonic() - started > TIMEOUT:
                raise FetchError('公开抓取超时')
            return dict(body=raw, url=url, status=response.status) if with_metadata else raw
        except (OSError, http.client.HTTPException, ValueError) as exc:
            if isinstance(exc, FetchError):
                raise
            raise FetchError('公开抓取失败：' + str(exc)) from exc
        finally:
            timer.cancel()
            conn.close()
    raise FetchError('重定向次数过多')
