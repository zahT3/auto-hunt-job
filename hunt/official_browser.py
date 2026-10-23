"""Optional fresh public renderer. No personal profile, input, upload or submit."""
from urllib.parse import urlsplit
from .sources import SourceError
from .network import validate_url, resolve_public

MOKA_READ_PATHS = {'/api/outer/ats-apply/website/jobs/v2', '/api/outer/ats-apply/website/job',
                   '/api/outer/ats-apply/website/jobs/recent',
                   '/api/outer/ats-apply/website/jobs/v2/filterFieldsAggregations',
                   '/api/outer/ats-apply/website/jobs/departments/flat',
                   '/api/outer/ats-apply/website/jobs/departments/structure',
                   '/api/outer/ats-apply/website/jobs/module'}


def read_request(method, url):
    p, _ = validate_url(url)
    from .minimax import read_request as minimax_read
    return method in ('GET', 'HEAD') or (method == 'POST' and p.hostname in ('app.mokahr.com', 'hire-r1.mokahr.com') and p.path in MOKA_READ_PATHS) or minimax_read(method, url)


class PublicRenderer:
    def __init__(self, maximum=8, should_continue=None):
        self.maximum, self.should_continue, self.used = maximum, should_continue, 0
        self.blocked_posts = set()

    def __enter__(self):
        return self

    def _start(self):
        try:
            from playwright.sync_api import sync_playwright
            self.runtime = sync_playwright().start()
            self.browser = self.runtime.chromium.launch(headless=True)
            self.context = self.browser.new_context(service_workers='block')
            from .moka_session import ReadTracker
            self.reads = ReadTracker()
            self.reads.attach(self.context)
            self.hosts = set()
            def route_handler(route):
                try:
                    req = route.request
                    if not read_request(req.method, req.url):
                        if req.method == 'POST': self.blocked_posts.add(urlsplit(req.url).path)
                        return route.abort()
                    host = urlsplit(req.url).hostname
                    if host not in self.hosts:
                        resolve_public(host, timeout=5); self.hosts.add(host)
                    if req.resource_type in ('image', 'media', 'font'): return route.abort()
                    route.continue_()
                except Exception: route.abort()
            self.context.route('**/*', route_handler)
            self.page = self.context.new_page()
            return self
        except Exception as error:
            self.__exit__(None, None, None)
            raise SourceError('needs_browser', '公开页面渲染不可用；请安装 requirements-executor.txt 与 Chromium：' + str(error)[:160]) from error

    def read(self, url):
        validate_url(url)
        if self.should_continue and not self.should_continue(): raise SourceError('cancelled', '扫描已停止')
        if self.used >= self.maximum: raise SourceError('budget_exhausted', '公开页面渲染次数已用完')
        self.used += 1
        if not getattr(self, 'runtime', None): self._start()
        self.reads.reset()
        try:
            same_document = self.page.url.split('#',1)[0] == url.split('#',1)[0]
            response = self.page.goto(url, wait_until='domcontentloaded', timeout=25000)
            if same_document:
                response = self.page.reload(wait_until='domcontentloaded', timeout=25000)
            # Public SPA data loads asynchronously. A single bounded wait, no retries.
            self.page.wait_for_timeout(2200)
            if self.page.url == 'about:blank': raise SourceError('blank_page', '公开招聘页退回空白，已停止')
            validate_url(self.page.url)
            html = self.page.content()
            if len(html.encode()) > 5 * 1024 * 1024: raise SourceError('parse_error', '渲染页面超过大小上限')
            result = dict(body=html.encode(), url=self.page.url, status=response.status if response else 200, rendered=True)
            p = urlsplit(self.page.url)
            if p.hostname in ('app.mokahr.com', 'hire-r1.mokahr.com') and p.fragment.endswith('/apply'):
                from .moka_session import OBSERVE
                result['observation'] = self.page.evaluate(OBSERVE)
                result['incomplete_reads'] = self.reads.incomplete
            return result
        except SourceError: raise
        except Exception as error: raise SourceError('fetch_error', '公开页面渲染失败：' + str(error)[:200]) from error

    def __exit__(self, *args):
        for name in ('context', 'browser', 'runtime'):
            obj = getattr(self, name, None)
            if obj:
                try: obj.stop() if name == 'runtime' else obj.close()
                except Exception: pass
