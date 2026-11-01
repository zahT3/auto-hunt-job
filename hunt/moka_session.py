"""Human login, then read-only Moka entry verification in an isolated profile.

No resume, field values, DOM dumps, credentials or cookies enter the result.
Authentication endpoints are enabled only while the user is in the login window.
Application writes and uploads remain blocked throughout.
"""
import hashlib
import time
from pathlib import Path
from urllib.parse import urlsplit
from .sources import SourceError, now
from .network import resolve_public
from .moka_read import OBSERVE, ReadTracker, allowed_request, classify, entry_identity

class MokaVerifier:
    def __init__(self, root, job, *, headless=False):
        self.job = job
        self.url = job.get('application_url') or job['url']
        self.identity = entry_identity(self.url)
        self.root, self.headless = Path(root), headless
        self.login_enabled = False
        self.blocked = set()
        self.reads = ReadTracker()

    def __enter__(self):
        try:
            from playwright.sync_api import sync_playwright
            self.runtime = sync_playwright().start()
            key = hashlib.sha256('|'.join(self.identity[:3]).encode()).hexdigest()[:16]
            profile = self.root / key
            profile.mkdir(parents=True, exist_ok=True, mode=0o700); profile.chmod(0o700)
            self.context = self.runtime.chromium.launch_persistent_context(
                str(profile), headless=self.headless, accept_downloads=False, service_workers='block')
            self.hosts = set()
            self.context.route('**/*', self._route)
            self.context.route_web_socket('**/*', lambda ws: ws.close())
            self.reads.attach(self.context)
            self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
            return self
        except Exception as error:
            self.__exit__(None, None, None)
            raise SourceError('needs_browser', '独立核验窗口未启动；请安装 Chromium，或关闭同公司占用窗口。' + type(error).__name__) from error

    def _route(self, route):
        try:
            request = route.request; p = urlsplit(request.url)
            if not allowed_request(request.method, request.url, self.identity[0], self.login_enabled):
                if len(self.blocked) < 100: self.blocked.add((request.method, p.path))
                return route.abort()
            if p.hostname not in self.hosts:
                resolve_public(p.hostname, timeout=5); self.hosts.add(p.hostname)
            route.continue_()
        except Exception: route.abort()

    def open(self, login=False):
        self.login_enabled = login
        self.reads.reset()
        same_document = self.page.url.split('#',1)[0] == self.url.split('#',1)[0]
        response = self.page.goto(self.url, wait_until='domcontentloaded', timeout=30000)
        if same_document:
            response = self.page.reload(wait_until='domcontentloaded', timeout=30000)
        self.page.wait_for_timeout(2400)
        if response and (response.status in (401,403,404,410,429) or response.status >= 500):
            return dict(url=self.url, final_url=self.page.url, checked_at=now(), method='isolated_session',
                        authenticated=False, source_id_seen=False, http_status=response.status,
                        status='not_found' if response.status in (404,410) else 'blocked' if response.status in (401,403,429) else 'check_failed')
        return self.check()

    def check(self):
        obs = self.page.locator('body').evaluate(OBSERVE, timeout=8000)
        result = classify(self.job, self.page.url, obs, session=True, blocked_reads=self.reads.incomplete)
        # Paths have no query strings or request bodies. No raw DOM is persisted.
        result['blocked_request_count'] = len(self.blocked)
        return result

    def run(self, finish, cancel, progress, timeout=600):
        check = self.open(login=True)
        if check['status'] not in ('login_required', 'captcha'): return check
        progress('awaiting_login', '请在独立窗口本人登录，完成后点“已登录”。', check)
        deadline = time.monotonic() + timeout
        while not finish.is_set() and not cancel.is_set() and time.monotonic() < deadline:
            if self.page.is_closed(): raise SourceError('cancelled', '核验窗口已关闭')
            self.page.wait_for_timeout(150)
        self.login_enabled = False
        if cancel.is_set(): raise SourceError('cancelled', '已结束核验')
        if not finish.is_set(): raise SourceError('cancelled', '登录核验超时，窗口已关闭')
        progress('checking', '正在只读核验申请入口。', None)
        # Re-read the original exact role after login; no click, fill or upload.
        return self.open(login=False)

    def __exit__(self, *args):
        for name in ('context', 'runtime'):
            obj = getattr(self, name, None)
            if obj:
                try: obj.stop() if name == 'runtime' else obj.close()
                except Exception: pass
