"""Optional application-owned browser, driven by Patchright when installed, else Playwright. Never attaches to personal Chrome.

Run `python -m hunt.sources_browser --login boss` to sign in yourself. Collection
only navigates public pages, reads rendered DOM, and blocks mutation requests.
Liepin search uses two explicitly allowlisted read-only POST endpoints observed
on its own public search page; all other POSTs remain blocked.
"""
from pathlib import Path
from urllib.parse import urlsplit
import threading
import re
import queue
from .sources import SourceError
from .network import validate_url, resolve_public

ROOT = Path(__file__).resolve().parent.parent / 'private' / 'browser-discovery'
# The workbench's default data directory (python -m hunt web); its scans read profiles from <data>/browser-search.
DEFAULT_DATA = ROOT.parent / 'app'
_LOCKS = {kind: threading.Lock() for kind in ('boss', 'liepin')}
HOME = {'boss': 'https://www.zhipin.com/', 'liepin': 'https://www.liepin.com/'}
HOSTS = {'boss': ('zhipin.com', 'bosszhipin.com'), 'liepin': ('liepin.com', 'lietou-static.com')}


FALLBACK_NOTE = '未安装可选的 Patchright（requirements-platform.txt），改用 Playwright；登录后的猎聘页面可能白屏。'


def _driver():
    """('patchright', sync_playwright) when the optional Patchright is installed: it never turns on CDP's Runtime domain,
    which 猎聘 detects and answers by blanking every tab, and it drops the navigator.webdriver flag. Same API as
    Playwright, which stays the fallback."""
    try:
        from patchright.sync_api import sync_playwright
        return 'patchright', sync_playwright
    except ImportError:
        from playwright.sync_api import sync_playwright
        return 'playwright', sync_playwright


def _sync_playwright():
    return _driver()[1]


def navigation_state(kind, url):
    if url == 'about:blank' or not url:
        raise SourceError('blank_page', '页面退回 about:blank；可能是站点自动化/调试检测或浏览器兼容问题。已停止此渠道，不重复登录或导航；可先使用公司官网搜索。')
    p = urlsplit(url)
    main = 'zhipin.com' if kind == 'boss' else 'liepin.com'
    if p.scheme != 'https' or not (p.hostname == main or (p.hostname or '').endswith('.' + main)):
        raise SourceError('blocked', '平台跳转到外部站点，采集已停止')
    if kind == 'liepin' and p.hostname == 'safe.liepin.com':
        raise SourceError('captcha', '猎聘要求本人安全验证；采集已停止。请运行 python -m hunt.sources_browser --login liepin，在打开的窗口里自己完成验证后再扫描')
    if kind == 'boss' and '/web/user/' in p.path:
        raise SourceError('login_required', 'BOSS 已跳转登录页，请本人在独立浏览器登录后重新扫描')
    if kind == 'boss' and '/verify' in p.path:
        raise SourceError('captcha', 'BOSS 要求本人安全验证；采集已停止')


class BrowserReader:
    def __init__(self, kind, *, headless=False, profile_root=None, channel=None):
        if kind not in HOME: raise SourceError('not_configured', '浏览器只读模式仅支持 BOSS 与猎聘')
        if channel not in (None, 'chrome'): raise SourceError('not_configured', '只支持默认 Chromium 或已安装的 Google Chrome')
        self.kind, self.headless, self.context, self.playwright, self.locked = kind, headless, None, None, False
        self.driver = None
        self.channel = channel
        self.denied_requests = []
        self.profile_root = Path(profile_root) if profile_root else ROOT
        self.validated_hosts = set()

    def __enter__(self):
        if not _LOCKS[self.kind].acquire(blocking=False):
            raise SourceError('blocked', '此渠道的独立浏览器正在使用，请完成登录或等待当前扫描结束')
        self.locked = True
        try:
            self.driver, start = _driver()
            self.playwright = start().start()
            profile = self.profile_root / (self.kind + ('-chrome' if self.channel else ''))
            profile.mkdir(parents=True, exist_ok=True, mode=0o700)
            profile.chmod(0o700)
            self.context = self.playwright.chromium.launch_persistent_context(str(profile), headless=self.headless,
                        accept_downloads=False, service_workers='block', channel=self.channel)
            self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
            return self
        except Exception as e:
            self.__exit__(None, None, None)
            raise SourceError('not_configured', '独立浏览器未就绪：请安装 requirements-executor.txt 与 Chromium，或关闭占用的采集窗口。' + type(e).__name__) from e

    def _deny(self, route, why):
        # Kept for the source report: a page whose own requests are cut shows its own errors ("network error").
        if len(self.denied_requests) < 100:
            self.denied_requests.append(dict(method=route.request.method, url=route.request.url.split('?')[0], why=why))
        return route.abort()

    def _read_route(self, route):
        request = route.request
        try:
            p, host = validate_url(request.url)
            read_search = self.kind == 'liepin' and host == 'api-c.liepin.com' and p.path in (
                '/api/com.liepin.searchfront4c.pc-search-job',
                '/api/com.liepin.searchfront4c.pc-search-job-cond-init') and request.method == 'POST'
            if not any(host == h or host.endswith('.' + h) for h in HOSTS[self.kind]):
                return self._deny(route, 'host')
            if request.method not in ('GET', 'HEAD') and not read_search:
                return self._deny(route, 'method')
            if host not in self.validated_hosts:
                resolve_public(host, timeout=8)
                self.validated_hosts.add(host)
            return route.continue_()
        except Exception:
            return self._deny(route, 'address')

    def read(self, url):
        p, host = validate_url(url)
        main = 'zhipin.com' if self.kind == 'boss' else 'liepin.com'
        if not (host == main or host.endswith('.' + main)):
            raise SourceError('blocked', '浏览器采集禁止跨平台导航')
        self.context.route('**/*', self._read_route)
        try:
            self.page.goto(url, wait_until='domcontentloaded', timeout=25000)
            # A bounded render allowance is needed for JavaScript search listings.
            self.page.wait_for_timeout(4000 if self.kind == 'boss' else 1200)
            if self.kind == 'liepin' and '/zhaopin/' in url:
                try:
                    self.page.wait_for_selector('a[href*="/job/"]', timeout=20000, state='attached')
                except Exception:
                    pass
            elif self.kind == 'liepin' and '/job/' in url:
                try:
                    self.page.wait_for_function('''() => [...document.querySelectorAll('script[type="application/ld+json"]')].some(n=>n.textContent.includes('JobPosting')) || [...document.querySelectorAll('.job-intro-container,.job-intro,.job-description')].some(n=>n.innerText.length>30)''', timeout=10000)
                except Exception:
                    pass
            navigation_state(self.kind, self.page.url)
            if self.kind == 'liepin' and '/job/' in url and not re.search(r'/job/\d+\.shtml', urlsplit(self.page.url).path):
                raise SourceError('blocked', '猎聘详情跳转到非岗位页面，已停止此渠道；实际地址：' + self.page.url)
            html = self.page.content()
            if len(html.encode()) > 5 * 1024 * 1024:
                raise SourceError('parse_error', '浏览器页面超过本地采集大小上限')
            return html.encode()
        except SourceError:
            raise
        except Exception as e:
            if self.page.url == 'about:blank': navigation_state(self.kind, self.page.url)
            raise SourceError('fetch_error', '浏览器页面读取失败：' + type(e).__name__) from e
        finally:
            self.context.unroute('**/*', self._read_route)

    def login(self):
        # The human interacts directly; no automated credential entry or buttons.
        self.page.goto(HOME[self.kind], wait_until='domcontentloaded', timeout=25000)
        print('请在独立窗口本人登录，完成后回到终端按回车。工具不会读取或导出账号密码。')
        # Blocking input() on the Playwright thread prevents its event loop from
        # processing browser events during the human's login interaction.
        done = queue.Queue(maxsize=1)
        def wait_for_human():
            try: input()
            except (EOFError, OSError): pass
            finally: done.put(True)
        threading.Thread(target=wait_for_human, daemon=True).start()
        while done.empty():
            self.page.wait_for_timeout(100)
        navigation_state(self.kind, self.page.url)
        print('窗口操作已结束；登录是否有效仍需只读搜索核验。')
        if self.driver == 'playwright': print(FALLBACK_NOTE)

    def __exit__(self, *args):
        try:
            if self.context: self.context.close()
        finally:
            try:
                if self.playwright: self.playwright.stop()
            finally:
                if self.locked:
                    self.locked = False
                    _LOCKS[self.kind].release()


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--login', choices=tuple(HOME), required=True)
    parser.add_argument('--profile-root', type=Path)
    parser.add_argument('--data', type=Path, default=DEFAULT_DATA, help='与工作台相同的数据目录（默认 private/app）；浏览器资料保存在其 browser-search 子目录')
    parser.add_argument('--browser', choices=('chromium', 'chrome'), default='chromium', help='使用默认 Chromium 或已安装的 Google Chrome；两者资料目录隔离')
    args = parser.parse_args()
    profile_root = args.profile_root or args.data / 'browser-search'
    with BrowserReader(args.login, profile_root=profile_root, channel='chrome' if args.browser == 'chrome' else None) as browser: browser.login()


if __name__ == '__main__': main()
