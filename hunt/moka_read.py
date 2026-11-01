"""Read-only Moka page observation shared by the public renderer, entry checks and the signed-in verifier.

Which Moka requests count as reads, how a rendered application page is observed (visible DOM only), and how that
observation becomes an entry-check status. Nothing here opens a browser or keeps a session.
"""
import re
from urllib.parse import urlsplit
from .sources import SourceError, now, title_key
from .network import validate_url

MOKA_READ_PATHS = {'/api/outer/ats-apply/website/jobs/v2', '/api/outer/ats-apply/website/job',
                   '/api/outer/ats-apply/website/jobs/recent',
                   '/api/outer/ats-apply/website/jobs/v2/filterFieldsAggregations',
                   '/api/outer/ats-apply/website/jobs/departments/flat',
                   '/api/outer/ats-apply/website/jobs/departments/structure',
                   '/api/outer/ats-apply/website/jobs/module'}

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
