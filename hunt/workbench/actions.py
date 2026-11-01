"""Workbench actions on a Store: materials, review, the single outbound gateway execute(), entry checks.

Frozen: bug fixes only. The mixin uses the host's tx/meta/job/save/event/intervene and never imports the app layer.
"""
import hashlib
import json
import threading
import uuid
from datetime import datetime, timezone, timedelta

from ..base import Error, digest, dumps, now
from ..profile import synthetic_profile

LOCKED = {'sending', 'unknown', 'submitted'}


class WorkbenchActions:
    """Review, prepare and execute, mixed into the Store. All outbound application actions enter through execute()."""

    def snapshot(self, candidate, config, job, package):
        return digest(dict(candidate=candidate, config=config, job={k: job.get(k) for k in ('id','platform_id','channel','url','title','company','jd','availability','requirements_text','questions','location','salary','experience','application_url')},
                           package={k:v for k,v in package.items() if k != 'snapshot'},
                           files=self.file_hashes(package)))

    def file_hashes(self, package):
        result = {}
        for kind, filename in package.get('files', {}).items():
            p = self.root / 'packages' / package['id'] / filename
            result[kind] = hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
        return result

    def _current_material_snapshot(self, candidate, config, job):
        """A review is current only while the saved materials and files match."""
        package = job.get('package')
        if not isinstance(package, dict) or not package.get('snapshot') or not package.get('files'):
            return None
        try:
            directory = self.root / 'packages' / package['id']
            if not all((directory / filename).is_file() for filename in package['files'].values()):
                return None
            current = self.snapshot(candidate, config, job, package)
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            return None
        return current if current == package['snapshot'] else None

    def review_materials(self, payload):
        """Record that selected local material versions were viewed, not approved."""
        ids, snapshots = payload.get('job_ids'), payload.get('snapshots')
        if (not isinstance(ids, list) or not 1 <= len(ids) <= 50 or
                any(not isinstance(jid, str) or not jid for jid in ids) or len(ids) != len(set(ids))):
            raise Error('请选择 1 至 50 个不同岗位复核材料')
        if payload.get('acknowledge_review') is not True:
            raise Error('请明确确认已查看所选材料；这不会授权对外申请')
        if not isinstance(snapshots, dict):
            raise Error('缺少材料快照，请刷新后复核')
        with self.tx() as c:
            candidate, config = self.meta(c, 'candidate'), self.meta(c, 'config')
            selected = []
            # Validate the entire batch before recording any event or review.
            for jid in ids:
                job = self.job(c, jid)
                current = self._current_material_snapshot(candidate, config, job)
                if not current or snapshots.get(jid) != current:
                    raise Error('材料、事实、条件或文件已变化，或缺少具体快照；请重新准备后复核')
                selected.append((job, current))
            for job, current in selected:
                if (job.get('material_review') or {}).get('snapshot') == current:
                    continue
                job['material_review'] = dict(snapshot=current, reviewed_at=now(),
                    package_id=job['package']['id'], scope='local_materials',
                    meaning='viewed', gaps_remaining=len(job['package'].get('gaps', [])))
                self.event(job, 'materials_reviewed', '已查看此版本本地材料；缺口仍保留，未授权披露或对外申请',
                           dict(snapshot=current, package_id=job['package']['id']))
                self.save(c, job)

    def prepare(self, jid):
        from ..materials import prepare, match
        from ..export import write_package
        from ..profile import recommend
        with self.tx() as c:
            j = self.job(c, jid)
            if j['status'] in LOCKED or j['status'] == 'rejected':
                raise Error('已拒绝、已发送或结果未知的岗位不能重新准备以绕过状态锁')
            candidate, config = self.meta(c, 'candidate'), self.meta(c, 'config')
            j['match'] = match(candidate, j, config)
            j['recommendation'] = recommend(candidate, j, config)
            package = prepare(candidate, j, config)
            package.update(id=uuid.uuid4().hex, created_at=now(), job_id=jid)
            out = self.root / 'packages' / package['id']
            out.mkdir(parents=True, mode=0o700)
            package['files'] = write_package(package, out)
            package['snapshot'] = self.snapshot(candidate, config, j, package)
            c.execute('INSERT INTO packages VALUES(?,?,?)', (package['id'], jid, dumps(package)))
            j.update(package=package, approval=None, status='review', next_action='集中审核事实、缺口、披露范围和最终文件')
            self.event(j, 'prepared', '生成本地证据草稿；不代表申请提交')
            self.save(c, j)
            return j

    def review(self, payload):
        ids = payload.get('job_ids', [])
        if not ids or len(ids) != len(set(ids)) or len(ids) > 5:
            raise Error('每组明确选择 1 至 5 个不同岗位')
        decision = payload.get('decision')
        if decision not in ('approve', 'reject'):
            raise Error('无效审核决定')
        permissions = payload.get('permissions', [])
        if not isinstance(permissions, list) or set(permissions) - {'input', 'upload', 'submit'}:
            raise Error('权限类型无效')
        hours = float(payload.get('expires_hours', 24))
        if not 0 < hours <= 72:
            raise Error('批准有效期必须在 0 至 72 小时以内')
        limit = int(payload.get('limit', len(ids)))
        if not 1 <= limit <= len(ids):
            raise Error('额度必须小于等于本组岗位数')
        with self.tx() as c:
            candidate, cfg = self.meta(c,'candidate'), self.meta(c,'config')
            plan_hash=payload.get('browser_plan_hash','')
            if plan_hash and (len(plan_hash)!=64 or any(x not in '0123456789abcdef' for x in plan_hash)):
                raise Error('执行计划 SHA-256 格式无效')
            group = uuid.uuid4().hex
            for jid in ids:
                j = self.job(c, jid)
                if j['status'] in LOCKED or j['status'] == 'rejected':
                    raise Error('该岗位已锁定；不能用审核重置拒绝或执行状态')
                p = j.get('package')
                if not p:
                    raise Error('先生成并审阅最终材料')
                current = self.snapshot(candidate,cfg,j,p)
                if current != p['snapshot'] or payload.get('snapshots', {}).get(jid) != current:
                    raise Error('快照已变化或缺少具体快照，请重新准备并审核')
                if decision == 'approve' and (p.get('blockers') or any(x.get('status')=='not_met' for x in j['match'].get('hard',[]))):
                    raise Error('缺少必填事实或明确不符合硬条件，不能批准对外操作')
                if decision == 'approve' and j['channel'] != 'anker':
                    raise Error('此渠道当前仅支持岗位发现和审核，不具备可批准的申请执行器')
                if decision == 'approve' and p.get('gaps') and payload.get('acknowledge_gaps') is not True:
                    raise Error('请明确确认已阅读匹配缺口；确认不能补齐缺失事实')
                j['status'] = 'approved' if decision == 'approve' else 'rejected'
                j['approval'] = dict(group=group, snapshot=current, decision=decision, permissions=permissions,
                    expires_at=(datetime.now(timezone.utc)+timedelta(hours=hours)).isoformat(),limit=limit,
                    job_ids=ids, recipient=j['url'], disclosure='application', browser_plan_hash=plan_hash, created_at=now())
                j['next_action'] = '在授权范围内执行；仍受活动额度和站点能力约束' if decision=='approve' else '已拒绝，不再自动处理'
                self.event(j, 'reviewed', '用户'+('批准' if decision=='approve' else '拒绝')+'当前具体快照')
                self.intervene(c, '申请快照审核：'+decision, jid)
                self.save(c,j)

    def execute(self, jid):
        # Read-only refresh happens before entering the serialized outbound gateway.
        with self.tx() as c:
            j = self.job(c,jid)
            if j['status'] in LOCKED:
                raise Error('已发送、执行中或结果未知；禁止重复提交')
            if j['channel'] != 'anker':
                raise Error('该渠道没有真实执行适配；合成夹具永不进入真实申请')
            candidate = self.meta(c,'candidate')
            if synthetic_profile(candidate):
                raise Error('合成候选人禁止外传')
        channel = self.channel
        if channel is None:
            from ..anker import Anker
            channel=Anker()
        fresh=channel.detail(j['platform_id'])
        if fresh.get('status') != 'open' or str(fresh.get('platform_id')) != str(j['platform_id']):
            raise Error('岗位状态或身份未通过重新核验')
        if any(fresh.get(key)!=j.get(key) for key in ('jd','title','url','company','location','salary','requirements_text','application_url')) or fresh.get('questions',[])!=j.get('questions',[]):
            raise Error('岗位内容已变化，需重新导入与审核')
        with self.tx() as c:
            j=self.job(c,jid)
            candidate,cfg=self.meta(c,'candidate'),self.meta(c,'config')
            if synthetic_profile(candidate):
                raise Error('合成候选人禁止外传')
            a,p=j.get('approval'),j.get('package')
            if self.meta(c,'control') != 'running':
                raise Error('活动已暂停或停止')
            if j['status'] in LOCKED or j['status']=='rejected':
                raise Error('该岗位已锁定')
            if not a or a['decision']!='approve' or datetime.fromisoformat(a['expires_at'])<=datetime.now(timezone.utc):
                raise Error('缺少有效批准或批准已过期')
            if a['snapshot']!=self.snapshot(candidate,cfg,j,p) or a['snapshot']!=p['snapshot']:
                raise Error('事实、材料或披露范围已改变，旧批准失效')
            if set(a['permissions']) != {'input','upload','submit'}:
                raise Error('尚未授权该接收方的输入、上传和最终提交')
            if not cfg['targets_confirmed'] or cfg['submission_limit']<=0:
                raise Error('确认求职范围并明确设置真实提交额度后才能执行')
            count=c.execute("SELECT COUNT(*) FROM attempts WHERE state IN ('sending','unknown','submitted')").fetchone()[0]
            if count>=cfg['submission_limit']:
                raise Error('真实提交额度已耗尽')
            for old in c.execute('SELECT state FROM attempts WHERE job_id=?',(jid,)):
                if old[0] not in ('not_sent',):
                    raise Error('历史结果未证实未发送，禁止重试')
            used=0
            for row in c.execute('SELECT data FROM attempts'):
                old=json.loads(row[0])
                used+=int(old.get('group')==a['group'] and old['state']!='not_sent')
            if used>=a['limit']:
                raise Error('本组批准额度已用完')
            if self.executor is None:
                self.intervene(c,'需启动已授权的真实浏览器执行器',jid)
                raise Error('真实浏览器执行器未连接；请见渠道能力与运行说明，未发起外传')
            attempt=dict(id=uuid.uuid4().hex,job_id=jid,state='sending',group=a['group'],snapshot=a['snapshot'],started_at=now())
            c.execute('INSERT INTO attempts VALUES(?,?,?,?)',(attempt['id'],jid,'sending',dumps(attempt)))
            j.update(status='sending',next_action='正在执行；中断后先查证')
            self.event(j,'intent','对外动作意图已持久化')
            self.save(c,j)
        try:
            result=self.executor.execute(j,p,a,lambda:self.can_continue(jid,a['snapshot']))
        except BaseException as e:
            result=dict(state='unknown',reason=str(e))
        if not isinstance(result,dict):
            result=dict(state='unknown',reason='执行器返回结构无效；禁止自动重发')
        state=result.get('state','unknown')
        if state not in ('not_sent','submitted','unknown'):
            state='unknown'
        if state=='not_sent' and (result.get('submit_attempted') is not False or result.get('phase') not in ('preflight','input','upload')):
            state='unknown'
        receipt=result.get('receipt')
        if isinstance(receipt,dict):
            try:
                receipt_time=datetime.fromisoformat(receipt.get('time',''))
                valid_receipt_time=receipt_time.tzinfo is not None and datetime.fromisoformat(attempt['started_at'])-timedelta(seconds=1)<=receipt_time<=datetime.now(timezone.utc)+timedelta(minutes=1)
            except (TypeError,ValueError): valid_receipt_time=False
        else: valid_receipt_time=False
        if state=='submitted' and not (valid_receipt_time and isinstance(receipt.get('evidence'),str) and receipt['evidence'].strip() and isinstance(receipt,dict) and receipt.get('platform_id')==j['platform_id'] and receipt.get('evidence') and receipt.get('time') and receipt.get('kind') in ('application_record','application_number','explicit_success_page')):
            state='unknown'
        with self.tx() as c:
            attempt.update(state=state,updated_at=now(),result=result)
            c.execute('UPDATE attempts SET state=?,data=? WHERE id=?',(state,dumps(attempt),attempt['id']))
            j=self.job(c,jid)
            j.update(status='approved' if state=='not_sent' else state,next_action='核对站点申请记录' if state=='unknown' else '等待招聘反馈' if state=='submitted' else result.get('reason','已证实未发送，可恢复'))
            self.event(j,state,j['next_action'],receipt)
            self.save(c,j)
        return dict(result,state=state)

    def can_continue(self,jid,snapshot):
        with self.tx() as c:
            if self.meta(c,'control')!='running': return False
            j=self.job(c,jid)
            a,p=j.get('approval'),j.get('package')
            if not a or not p or a['decision']!='approve' or a['snapshot']!=snapshot: return False
            if datetime.fromisoformat(a['expires_at'])<=datetime.now(timezone.utc): return False
            return j['status']=='sending' and self.snapshot(self.meta(c,'candidate'),self.meta(c,'config'),j,p)==snapshot

    def save_entry_check(self, original, check):
        """A page observation cannot change the recipient, material or approval."""
        with self.tx() as c:
            job = self.job(c, original['id'])
            if any(job.get(k) != original.get(k) for k in ('url','application_url','title','platform_id')):
                raise Error('核验期间岗位已更新，请重新核验当前入口')
            if not isinstance(job.get('raw'), dict): job['raw'] = {}
            route = job['raw'].setdefault('application_route', {})
            previous = route.get('entry_check')
            if previous:
                route['entry_check_history'] = (route.get('entry_check_history', []) + [previous])[-5:]
            route['entry_check'] = check
            self.event(job, 'entry_checked', '只读核验申请入口；未填写、上传或投递', dict(status=check['status'], method=check['method']))
            self.save(c, job)

    def start_entry_verification(self, job_id):
        from ..moka_session import MokaVerifier, entry_identity
        with self.tx() as c: job = self.job(c, job_id)
        entry_identity(job.get('application_url') or job['url'])
        with self.entry_lock:
            if any(v['status'] in ('opening','awaiting_login','checking') for v in self.entry_verifications.values()):
                raise Error('已有核验窗口，请先完成或关闭它')
            finish, cancel = threading.Event(), threading.Event()
            self.entry_signals[job_id] = (finish, cancel)
            self.entry_verifications[job_id] = dict(status='opening', message='正在打开独立核验窗口。')
        def progress(status, message, check=None):
            with self.entry_lock:
                self.entry_verifications[job_id] = dict(status=status, message=message, check=check)
        def run():
            try:
                with MokaVerifier(self.root / 'browser-entry', job) as browser:
                    check = browser.run(finish, cancel, progress)
                self.save_entry_check(job, check)
                progress('complete', '入口核验完成；未投递。', check)
            except Exception as error:
                status = 'cancelled' if getattr(error, 'status', None) == 'cancelled' else 'failed'
                progress(status, str(error) if isinstance(error, (ValueError, Error)) else '核验未完成：' + type(error).__name__)
            finally:
                with self.entry_lock:
                    if self.entry_signals.get(job_id) == (finish,cancel):
                        self.entry_signals.pop(job_id, None)
        threading.Thread(target=run, daemon=True).start()

    def signal_entry_verification(self, job_id, finish):
        with self.entry_lock:
            signals = self.entry_signals.get(job_id)
            if not signals: raise Error('核验窗口已结束')
            signals[0 if finish else 1].set()

    def add_event(self, payload):
        kind=payload.get('kind')
        if kind not in ('note','followup_draft','interview','reply','chat_sent','hr_read'): raise Error('事件类型无效；不能手工注入申请成功')
        if kind in ('chat_sent','hr_read','reply') and not payload.get('evidence'): raise Error('需要对应事件的证据')
        with self.tx() as c:
            j=self.job(c,payload['job_id']);self.event(j,kind,str(payload.get('note','')),payload.get('evidence'));self.save(c,j)
