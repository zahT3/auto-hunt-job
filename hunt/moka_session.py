"""Human login, then read-only Moka entry verification in an isolated profile.

No resume, field values, DOM dumps, credentials or cookies enter the result.
Authentication endpoints are enabled only while the user is in the login window.
Application writes and uploads remain blocked throughout.
"""
import hashlib
import re
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit
from .sources import SourceError, now
from .network import validate_url, resolve_public
from .official_browser import MOKA_READ_PATHS
from .entries import title_key

HOSTS = {'app.mokahr.com', 'hire-r1.mokahr.com'}
READ_POSTS = MOKA_READ_PATHS | {
    '/api/outer/ats-apply/privacy-policy/get',
    '/api/outer/ats-apply/website/applicant-limit-check',
    '/api/outer/ats-apply/website/group-by-job',
    '/api/outer/ats-apply/website/listCountryCallingCodes',
    '/api/outer/ats-apply/website/project-delivery-limit-prompt',
    '/api/outer/ats-jc-apply/website/feature-switches',
    '/api/outer/ats-candidate/apply-form/extend-info/website/query',
    '/api/outer/ats-apply/personal-center/candidateInfo',
    '/api/outer/ats-apply/personal-center/applyInfoV2',
    '/api/outer/ats-apply/personal-center/contact',
    '/api/outer/ats-common/common-sense/listOptions',
    '/api/outer/ats-candidate/exclusive-features/eeo-dei/candidate/getQuestionDetailList',
}
# Observed in Moka's own application client. No wildcard authentication writes.
AUTH_POSTS = {
    '/personal-center/candidate/loginAuthCode',
    '/personal-center/candidate/phone-login',
    '/personal-center/candidate/email-login',
    '/api/outer/ats-common/verification/scenes/GenericEmail/prepare',
    '/api/outer/mage/captcha/getCaptchaId',
}


def role_title(value):
    # The official Moka application page adds this priority badge to its heading.
    return title_key(re.sub(r'^\s*【优先】\s*', '', value))


class ReadTracker:
    """Fail closed on required form reads, including failed and pending requests."""
    def __init__(self): self.reset()

    def reset(self):
        self.pending = set()
        self.failures = set()

    def required(self, request):
        p = urlsplit(request.url)
        return p.hostname in HOSTS and (p.path in READ_POSTS or
            any(p.path.startswith(prefix) for prefix in ('/api/get_apply_form/', '/api/apply_form_info/', '/api/get_job_apply_form/')))

    def started(self, request):
        if self.required(request): self.pending.add(request)

    def finished(self, request): self.pending.discard(request)

    def failed(self, request):
        if request in self.pending: self.failures.add(urlsplit(request.url).path)
        self.pending.discard(request)

    def response(self, response):
        if response.request in self.pending and response.status >= 400:
            self.failures.add(urlsplit(response.url).path)

    @property
    def incomplete(self): return bool(self.pending or self.failures)

    def attach(self, context):
        context.on('request', self.started)
        context.on('requestfinished', self.finished)
        context.on('requestfailed', self.failed)
        context.on('response', self.response)


def entry_identity(url):
    p, _ = validate_url(url)
    board = re.fullmatch(r'/(apply|social-recruitment)/([\w-]+)/(\d+)/?', p.path)
    role = re.fullmatch(r'/job/([\w-]+)/apply/?', p.fragment)
    if p.hostname not in HOSTS or not board or not role:
        raise SourceError('unsupported', '只支持明确职位的 Moka 申请入口')
    return (p.hostname, board[2], board[3], role[1])


def allowed_request(method, url, host, login=False):
    p, _ = validate_url(url)
    if method == 'POST':
        return p.hostname == host and (p.path in READ_POSTS or
                                      login and p.path.rstrip('/') in AUTH_POSTS)
    if method not in ('GET', 'HEAD'): return False
    if p.hostname == host:
        # Some legacy endpoints mutate through GET. Never enable these.
        return not re.search(r'logout|delete|save|submit|upload|send|loginAuthCode|bind|merge', p.path, re.I)
    # Static Moka assets and NetEase's human CAPTCHA resources; no third-party POSTs.
    return (p.hostname or '').endswith(('.mokahr.com', '.mokahr.cn', '.126.net', '.nosdn.127.net'))


def classify(job, url, observation, *, session=False, blocked_reads=False):
    expected = entry_identity(job.get('application_url') or job['url'])
    result = dict(url=job.get('application_url') or job['url'], final_url=url,
                  checked_at=now(), method='isolated_session' if session else 'public_render',
                  authenticated=False, source_id_seen=False)
    try: actual = entry_identity(url)
    except (ValueError, SourceError):
        result['status'] = 'identity_mismatch'; return result
    if actual != expected:
        result['status'] = 'identity_mismatch'; return result
    result['source_id_seen'] = True
    text = observation.get('text', '')
    if any(re.fullmatch(r'.{0,15}(职位已关闭|职位不存在|已下线|job (?:closed|not found)).{0,15}', h, re.I) for h in observation.get('headings', [])):
        result['status'] = 'not_found'
    elif observation.get('login_gate'):
        result['status'] = 'login_required'
    elif observation.get('captcha'):
        result['status'] = 'captcha'
    elif not any(role_title(h) == role_title(job['title']) for h in observation.get('headings', [])):
        result['status'] = 'identity_mismatch'
    elif blocked_reads or observation.get('load_error'):
        result['status'] = 'form_incomplete'
    elif observation.get('resume_input') and observation.get('submit_control'):
        result.update(status='form_seen', identity='same_board_role_and_heading',
                      authenticated=bool(session and observation.get('account_marker')))
    else:
        result['status'] = 'job_page_seen'
    return result


# Read visible DOM only. In particular, do not read input values or app stores.
OBSERVE = r"""() => {
  const visible = n => !!n && !!(n.offsetWidth || n.offsetHeight || n.getClientRects().length) && getComputedStyle(n).visibility !== 'hidden';
  const text = document.body.innerText.slice(0, 120000);
  const modals = [...document.querySelectorAll('[role=dialog],[class*=Modal-modal-]')].filter(visible);
  return {
    text,
    headings: [...document.querySelectorAll('h1,h2,div[class*=title-]')].filter(visible).map(n=>n.innerText.trim()).filter(s=>s.length<500),
    login_gate: /请先登录/.test(text) || modals.some(n=>/邮箱登录|手机号登录|扫码登录/.test(n.innerText)),
    captcha: modals.some(n=>/请完成验证|请通过验证码验证|安全验证/.test(n.innerText)),
    load_error: /获取(?:投递限制|申请表|问卷|职位)失败|加载失败|网络错误/.test(text),
    resume_input: !!document.querySelector('input[type=file]:not([disabled])') && /上传简历|上传附件/.test(text),
    submit_control: [...document.querySelectorAll('button')].some(n=>visible(n) && /^(预览并提交|提交申请|提交)$/.test(n.innerText.trim()) && !n.disabled),
    account_marker: [...document.querySelectorAll('a,button')].some(n=>visible(n) && /^(退出登录|退出)$/.test(n.innerText.trim()))
  };
}"""


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


def main():
    import argparse, json
    parser = argparse.ArgumentParser(description='Moka 本人登录后的只读入口核验；不填写、不上传、不投递')
    parser.add_argument('--data', type=Path, default=Path('private/app'))
    parser.add_argument('--job', required=True, help='工作台岗位 ID')
    parser.add_argument('--headless', action='store_true', help='只读已有独立会话，不等待登录')
    args = parser.parse_args()
    from .core import Store
    store = Store(args.data)
    with store.tx() as c: job = store.job(c, args.job)
    try:
        with MokaVerifier(store.root / 'browser-entry', job, headless=args.headless) as browser:
            if args.headless: result = browser.open()
            else:
                finish, cancel = threading.Event(), threading.Event()
                def progress(status, message, check):
                    print(message, flush=True)
                    if status == 'awaiting_login':
                        def wait():
                            try: input('完成登录后按回车核验；Ctrl+C 结束：'); finish.set()
                            except (EOFError, OSError): cancel.set()
                        threading.Thread(target=wait, daemon=True).start()
                result = browser.run(finish, cancel, progress)
        store.save_entry_check(job, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (SourceError, KeyboardInterrupt) as error:
        print(json.dumps(dict(status=getattr(error, 'status', 'cancelled'), error=str(error)), ensure_ascii=False))
        raise SystemExit(1)


if __name__ == '__main__': main()
