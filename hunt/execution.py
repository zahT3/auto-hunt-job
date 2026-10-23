"""Explicit, snapshot-bound Anker browser plans; no guessed application answers.

The local service owns approval, quota, deduplication and durable submit intent.
This adapter independently checks plan/permission identity before browser writes.
A plan is created only after the operator inspects the authenticated live form.
"""
import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from .anker import WEBSITE, platform_id


def _now():
    return datetime.now(timezone.utc).isoformat()


class PlanError(ValueError):
    pass


class BrowserExecutor:
    def __init__(self, plan_path, data_dir=None, headless=False):
        self.plan_path = Path(plan_path).resolve()
        self.data_dir = Path(data_dir or 'private').resolve()
        self.headless = headless

    def login(self):
        """User-operated login in the dedicated local profile; no credential read."""
        from playwright.sync_api import sync_playwright
        root = self.data_dir / 'browser'
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(str(root / 'anker-profile'), headless=False)
            try:
                page = context.new_page()
                page.goto('https://anker-in.jobs.feishu.cn/index/login', wait_until='domcontentloaded', timeout=30000)
                input('在浏览器中自行处理登录和条款。完成后返回此终端按 Enter 保存本地会话并关闭浏览器：')
            finally:
                context.close()

    def _validate(self, job, package, approval):
        raw = self.plan_path.read_bytes()
        if len(raw) > 100000:
            raise PlanError('浏览器计划过大')
        if hashlib.sha256(raw).hexdigest() != approval.get('browser_plan_hash'):
            raise PlanError('浏览器计划未获具体审核或批准后已变化')
        plan = json.loads(raw)
        pid = platform_id(job.get('platform_id', ''))
        if job.get('channel') != 'anker' or package.get('synthetic'):
            raise PlanError('只有真实候选人、安克渠道可使用真实执行器')
        if approval.get('decision') != 'approve' or approval.get('disclosure') != 'application':
            raise PlanError('缺少申请披露批准')
        try:
            expiry = datetime.fromisoformat(approval['expires_at'])
            if expiry.tzinfo is None or expiry <= datetime.now(timezone.utc):
                raise ValueError()
        except (KeyError, ValueError, TypeError):
            raise PlanError('批准无效或已过期')
        if job.get('id') not in approval.get('job_ids', []) or approval.get('limit', 0) < 1:
            raise PlanError('批准不包含该岗位或额度')
        if set(approval.get('permissions', [])) != {'input', 'upload', 'submit'}:
            raise PlanError('需要分别授权输入、上传和最终提交')
        if not package.get('snapshot') or approval.get('snapshot') != package['snapshot']:
            raise PlanError('批准与材料快照不符')
        expected_url = 'https://anker-in.jobs.feishu.cn/index/resume/' + pid + '/apply'
        recipient = job.get('url')
        parsed = urlsplit(recipient or '')
        query = parse_qs(parsed.query)
        if (parsed.scheme != 'https' or parsed.netloc != 'career.anker.com.cn' or parsed.path != '/larkJobDetail/'
                or query.get('jobId') != [pid] or query.get('websiteId') != [WEBSITE]):
            raise PlanError('岗位接收方不是已核实的安克官方岗位地址')
        expected = dict(version=1, channel='anker', platform_id=pid, snapshot=package['snapshot'], recipient=recipient, application_url=expected_url)
        if any(plan.get(key) != value for key, value in expected.items()) or approval.get('recipient') != recipient:
            raise PlanError('浏览器计划与岗位、渠道、接收方或快照不符')
        if not plan.get('identity_selector') or not plan.get('submit_selector') or not isinstance(plan.get('receipt'), dict):
            raise PlanError('计划缺少岗位身份、提交动作或关联回执定位')
        fields, uploads = [], []
        used = set()
        for item in plan.get('inputs', []):
            if not isinstance(item, dict) or set(item) - {'selector','field','type'}:
                raise PlanError('输入映射无效')
            selector, field = item.get('selector'), item.get('field')
            proven = package.get('fields', {}).get(field, {})
            if not selector or selector in used or not isinstance(proven, dict) or not proven.get('fact_ids'):
                raise PlanError('字段缺少唯一定位或事实来源')
            source_map = package.get('source_map', {})
            if any(ref not in source_map or source_map[ref].get('disclosure') != 'application' for ref in proven['fact_ids']):
                raise PlanError('字段事实没有申请披露权限')
            value = proven.get('value')
            if value is None or value == '':
                raise PlanError('未知字段不能代填')
            if item.get('type', 'text') not in ('text', 'select'):
                raise PlanError('勾选声明、签署与验证码不能自动执行')
            fields.append(dict(selector=selector, value=str(value), type=item.get('type','text')))
            used.add(selector)
        package_dir = (self.data_dir / 'packages' / str(package.get('id', ''))).resolve()
        if not package_dir.is_relative_to((self.data_dir / 'packages').resolve()):
            raise PlanError('材料目录越界')
        for item in plan.get('uploads', []):
            if not isinstance(item, dict) or set(item) != {'selector','file','sha256'}:
                raise PlanError('上传映射无效')
            filename = package.get('files', {}).get(item['file'])
            if not filename:
                raise PlanError('上传文件不是已审核申请包的一部分')
            path = (package_dir / filename).resolve()
            if not path.is_relative_to(package_dir) or not path.is_file() or path.stat().st_size > 20*1024*1024:
                raise PlanError('上传文件缺失、越界或超过 20MB')
            if not item.get('selector') or item['selector'] in used:
                raise PlanError('上传字段缺少唯一定位')
            if hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
                raise PlanError('上传文件与已批准浏览器计划的文件哈希不符')
            uploads.append(dict(selector=item['selector'], path=str(path), sha256=item['sha256']))
            used.add(item['selector'])
        if not fields or not uploads:
            raise PlanError('计划必须明确输入字段与申请包上传')
        receipt = plan['receipt']
        if not all(receipt.get(k) for k in ('record_selector','job_id_attribute','number_attribute')):
            raise PlanError('回执需要岗位 ID 与申请编号的记录定位；通用 toast 无效')
        if not all(re.fullmatch(r'[a-zA-Z_:][a-zA-Z0-9_:.-]*',receipt[k]) for k in ('job_id_attribute','number_attribute')):
            raise PlanError('回执属性名称无效')
        return plan, fields, uploads

    def execute(self, job, package, approval, is_running):
        try:
            plan, fields, uploads = self._validate(job, package, approval)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return dict(state='not_sent', submit_attempted=False, phase='preflight', reason=str(exc), event_kind='blocked_before_browser')
        if not is_running():
            return dict(state='not_sent', submit_attempted=False, phase='preflight', reason='活动已暂停或停止', event_kind='paused')
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return dict(state='not_sent', submit_attempted=False, phase='preflight', reason='本地未安装 Playwright；请按 README 安装执行器依赖', event_kind='runtime_unavailable')
        root = self.data_dir / 'browser'
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        evidence_dir = root / 'evidence' / uuid.uuid4().hex
        evidence_dir.mkdir(parents=True, mode=0o700)
        # Separate browser profile, never the user's unrelated browser sessions.
        with sync_playwright() as playwright:
            try:
                context = playwright.chromium.launch_persistent_context(str(root / 'anker-profile'), headless=self.headless)
            except Exception as exc:
                return dict(state='not_sent', submit_attempted=False, phase='preflight', reason='Chromium 启动失败：' + str(exc), event_kind='runtime_unavailable')
            try:
                page = context.new_page()
                return self._run_page(page, plan, fields, uploads, job, approval, is_running, evidence_dir)
            finally:
                context.close()

    def _run_page(self, page, plan, fields, uploads, job, approval, is_running, evidence_dir):
        """Also exercised by a real Chromium local fixture; never a live receipt."""
        changed = False
        clicked = False
        actions = []
        evidence_dir = Path(evidence_dir)
        evidence_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

        def record(kind, **extra):
            item = dict(time=_now(), kind=kind, platform_id=job['platform_id'], **extra)
            actions.append(item)
            with (evidence_dir / 'events.jsonl').open('a', encoding='utf-8') as stream:
                os.chmod(str(evidence_dir / 'events.jsonl'), 0o600)
                stream.write(json.dumps(item, ensure_ascii=False) + '\n')
                stream.flush()
                os.fsync(stream.fileno())

        def guard():
            if not is_running():
                raise PlanError('活动已暂停或停止；后续动作已阻止')
            if datetime.fromisoformat(approval['expires_at']) <= datetime.now(timezone.utc):
                raise PlanError('执行过程中批准已过期')
            # No cross-origin form writes or unexpected navigation.
            current = urlsplit(page.url)
            target = urlsplit(plan['application_url'])
            if current.scheme != target.scheme or current.netloc != target.netloc:
                raise PlanError('页面离开已批准接收方')
            if '/login' in current.path:
                raise PlanError('需用户在独立浏览器中完成手机号/验证码登录及隐私声明；未代办注册')
            if current.path != target.path:
                raise PlanError('页面不在已批准的具体岗位申请表')
            if page.locator(plan['identity_selector']).count() != 1 or page.locator(plan['identity_selector']).inner_text(timeout=5000).strip() != job['title'].strip():
                raise PlanError('当前表单岗位标题与已批准岗位不符')
            check_form()
            record_spec = plan['receipt']
            existing = page.locator(record_spec['record_selector'])
            if (existing.count() == 1 and existing.is_visible()
                    and existing.get_attribute(record_spec['job_id_attribute']) == str(job['platform_id'])
                    and existing.get_attribute(record_spec['number_attribute'])):
                raise PlanError('发现已有该岗位申请记录；先核对历史，未重复提交')

        def check_form():
            allowed = {x['selector'] for x in fields + uploads}
            controls = page.locator('input,textarea,select,[aria-required="true"]').all()
            for element in controls:
                if not element.is_visible() or element.is_disabled():
                    continue
                kind = (element.get_attribute('type') or '').lower()
                if kind in ('submit','button','reset','image'):
                    continue
                required = element.get_attribute('required') is not None or element.get_attribute('aria-required') == 'true'
                matched = any(page.locator(selector).count() == 1 and
                              element.evaluate('(el, selector) => el === document.querySelector(selector)', selector) for selector in allowed)
                if required and (not matched or kind in ('checkbox','radio')):
                    raise PlanError('发现计划外必填字段或声明；需核对后重新批准')
                if not matched:
                    # A saved ATS profile can contain old personal data. Never
                    # submit those visible values outside the approved package.
                    populated = element.evaluate('(el) => el.type === "checkbox" || el.type === "radio" ? el.checked : !!el.value')
                    if populated:
                        raise PlanError('发现计划外已填字段；不能携带旧资料提交')

        try:
            if not is_running():
                raise PlanError('活动已暂停或停止')
            page.goto(plan['application_url'], wait_until='networkidle', timeout=30000)
            guard()
            # All required controls are inspected again by guard before each
            # mutation; a later conditional question must not be silently sent.
            for entry in fields:
                guard()
                locator = page.locator(entry['selector'])
                if locator.count() != 1:
                    raise PlanError('输入字段定位不唯一')
                kind = locator.get_attribute('type') or ''
                if kind.lower() in ('checkbox','radio','password','hidden','submit','button'):
                    raise PlanError('拒绝声明、凭据、隐藏字段或按钮输入')
                record('input_intent', selector=entry['selector'])
                changed = True  # fill may trigger autosave even if it times out.
                if entry['type'] == 'select':
                    locator.select_option(entry['value'], timeout=10000)
                else:
                    locator.fill(entry['value'], timeout=10000)
                record('filled', selector=entry['selector'])
            for entry in uploads:
                guard()
                if hashlib.sha256(Path(entry['path']).read_bytes()).hexdigest() != entry['sha256']:
                    raise PlanError('上传前文件已变化，旧批准失效')
                locator = page.locator(entry['selector'])
                if locator.count() != 1 or locator.get_attribute('type') != 'file':
                    raise PlanError('上传定位必须对应唯一 file input')
                record('upload_intent', filename=Path(entry['path']).name)
                changed = True
                locator.set_input_files(entry['path'], timeout=15000)
                record('uploaded', filename=Path(entry['path']).name)
            guard()
            button = page.locator(plan['submit_selector'])
            if button.count() != 1 or not button.is_enabled():
                raise PlanError('提交按钮不可用或不唯一')
            if re.search(r'同意|签署|声明|agree|consent|terms', button.inner_text(), re.I):
                raise PlanError('提交按钮涉及同意声明或条款，需用户检查并处理')
            page.screenshot(path=str(evidence_dir / 'before-submit.png'), full_page=True)
            guard()
            record('submit_intent')  # fsync before final outbound action.
            clicked = True  # timeout after click is never interpreted as safe retry.
            button.click(timeout=15000)
            record('submit_clicked')
            record_spec = plan['receipt']
            receipt = page.locator(record_spec['record_selector'])
            receipt.wait_for(state='visible', timeout=15000)
            if receipt.count() != 1:
                raise PlanError('无法唯一核对申请记录')
            association = receipt.get_attribute(record_spec['job_id_attribute'])
            number = receipt.get_attribute(record_spec['number_attribute'])
            if str(association) != str(job['platform_id']) or not number or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_./-]{3,99}', number):
                raise PlanError('回执没有对应岗位和有效申请编号')
            evidence = evidence_dir / 'receipt.html'
            evidence.write_text(receipt.evaluate('(el) => el.outerHTML'), encoding='utf-8')
            evidence.chmod(0o600)
            page.screenshot(path=str(evidence_dir / 'receipt.png'), full_page=True)
            record('receipt_verified', number=number)
            return dict(state='submitted', submit_attempted=True, phase='submit', reason='已核验对应岗位申请记录与申请编号', event_kind='submitted',
                        receipt=dict(kind='application_record', platform_id=job['platform_id'], number=number,
                                     evidence=str(evidence), time=_now()), evidence_dir=str(evidence_dir))
        except Exception as exc:
            try:
                record('paused_or_failed', reason=str(exc), final_submit_attempted=clicked, data_may_have_been_saved=changed)
                page.screenshot(path=str(evidence_dir / 'paused.png'), full_page=True)
            except Exception:
                pass
            return dict(state='unknown' if changed or clicked else 'not_sent', reason=str(exc),
                        event_kind='submit_unverified' if clicked else 'filled_unverified' if changed else 'blocked_before_input',
                        submit_attempted=clicked, phase='submit' if clicked else 'input' if changed else 'preflight',
                        data_may_have_been_saved=changed, final_submit_attempted=clicked, evidence_dir=str(evidence_dir))


AnkerExecutor = BrowserExecutor
