"""Persistent orchestration. All outbound application actions enter through execute()."""
import base64
import copy
import hashlib
import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


def now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(dumps(value).encode()).hexdigest()


class Error(Exception):
    pass


DEFAULT_CONFIG = dict(keyword='', keywords=[], cities=[], salary_min=None, max_jobs=20,
                      interval_minutes=60, submission_limit=0, targets_confirmed=False,
                      sources=['boss', 'liepin', 'anker', 'greenhouse', 'lever', 'ashby'],
                      company_boards=[dict(type='greenhouse', slug='anthropic', company='Anthropic'),
                                      dict(type='lever', slug='binance', company='Binance'),
                                      dict(type='ashby', slug='cursor', company='Cursor')], max_pages=2,
                      source_modes={'boss': 'public', 'liepin': 'public'}, search_provider=None,
                      official_only=False, browser_channel=None, check_entries=True, official_browser=False)
LOCKED = {'sending', 'unknown', 'submitted'}


def synthetic_profile(candidate):
    """Synthetic provenance survives editing the top-level profile toggle."""
    if candidate.get('synthetic') is True:
        return True
    return any(isinstance(f, dict) and isinstance(f.get('source'), dict)
               and (f['source'].get('synthetic') is True
                    or str(f['source'].get('reference', '')).startswith('synthetic://'))
               for f in candidate.get('facts', []))


class Store:
    def __init__(self, root, channel=None, executor=None):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.root / 'state.sqlite3'
        self.channel, self.executor = channel, executor
        self.run_lock = threading.Lock()
        self.start_lock = threading.Lock()
        self.search_thread = None
        self.entry_lock = threading.Lock()
        self.entry_verifications = {}
        self.entry_signals = {}
        self.is_demo = self.root.name == 'demo'
        with self.tx() as c:
            c.executescript('''CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, identity TEXT UNIQUE NOT NULL, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS packages(id TEXT PRIMARY KEY, job_id TEXT, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS attempts(id TEXT PRIMARY KEY, job_id TEXT NOT NULL, state TEXT, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS interventions(id TEXT PRIMARY KEY, data TEXT NOT NULL);''')
            from .materials import synthetic_candidate
            for key, value in [('candidate', synthetic_candidate()), ('config', DEFAULT_CONFIG), ('control', 'running'), ('candidate_draft', None), ('encountered_companies', [])]:
                c.execute('INSERT OR IGNORE INTO meta VALUES(?,?)', (key, dumps(value)))
            saved_config = self.meta(c, 'config')
            self.setmeta(c, 'config', dict(DEFAULT_CONFIG, **saved_config))
        # Called only by process bootstrap; a second Store object must not mark live sends unknown.

    @contextmanager
    def tx(self):
        c = sqlite3.connect(str(self.path), timeout=30)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA journal_mode=WAL')
        c.execute('PRAGMA foreign_keys=ON')
        c.execute('BEGIN IMMEDIATE')
        try:
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()

    def meta(self, c, key):
        return json.loads(c.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()[0])

    def setmeta(self, c, key, value):
        c.execute('UPDATE meta SET value=? WHERE key=?', (dumps(value), key))

    def job(self, c, jid):
        row = c.execute('SELECT data FROM jobs WHERE id=?', (jid,)).fetchone()
        if not row:
            raise Error('岗位不存在')
        return json.loads(row[0])

    def save(self, c, job):
        c.execute('UPDATE jobs SET data=? WHERE id=?', (dumps(job), job['id']))

    def event(self, job, kind, note, evidence=None):
        job.setdefault('events', []).append(dict(kind=kind, note=note, evidence=evidence, time=now()))

    def intervene(self, c, reason, job_id=None):
        c.execute('INSERT INTO interventions VALUES(?,?)', (uuid.uuid4().hex, dumps(dict(time=now(), reason=reason, job_id=job_id))))

    def recover(self):
        with self.tx() as c:
            for row in c.execute('SELECT * FROM runs').fetchall():
                run = json.loads(row['data'])
                if run.get('status') == 'running':
                    run.update(status='interrupted', finished_at=now())
                    run.setdefault('failures', []).append('运行器中断；本轮覆盖不完整，可重新搜索')
                    c.execute('UPDATE runs SET data=? WHERE id=?', (dumps(run), row['id']))
            for row in c.execute("SELECT * FROM attempts WHERE state='sending'").fetchall():
                attempt = json.loads(row['data'])
                attempt.update(state='unknown', reason='运行器中断，需查证是否发送；禁止自动重发', updated_at=now())
                c.execute('UPDATE attempts SET state=?, data=? WHERE id=?', ('unknown', dumps(attempt), row['id']))
                j = self.job(c, row['job_id'])
                j.update(status='unknown', next_action='查证招聘站申请记录；未证实未发送前保持锁定')
                self.event(j, 'unknown', attempt['reason'])
                self.save(c, j)

    def state(self):
        with self.entry_lock: entry_verifications = copy.deepcopy(self.entry_verifications)
        with self.tx() as c:
            jobs = [json.loads(r[0]) for r in c.execute('SELECT data FROM jobs ORDER BY rowid DESC')]
            candidate = self.meta(c, 'candidate')
            config = self.meta(c, 'config')
            for j in jobs:
                j['attempts'] = [json.loads(r[0]) for r in c.execute('SELECT data FROM attempts WHERE job_id=? ORDER BY rowid', (j['id'],))]
                review = j.get('material_review') or {}
                j['material_review_current'] = bool(review.get('snapshot') and
                    review.get('snapshot') == self._current_material_snapshot(candidate, config, j))
            keyword = str(config.get('keyword') or '').strip().casefold()
            jobs.sort(key=lambda j:(j['status'] in ('submitted','rejected'), any(r.get('status')=='not_met' for r in (j.get('match') or {}).get('hard',[])), -(j.get('recommendation') or {}).get('priority',0), bool(keyword) and keyword not in j['title'].casefold()))
            tasks = []
            if synthetic_profile(candidate):
                tasks.append(dict(title='补充真实事实资料', reason='当前候选人为合成演示，禁止对外申请', action='candidate'))
            if not config['targets_confirmed']:
                tasks.append(dict(title='确认求职范围', reason='岗位、城市、薪资与时限仍待确认；当前仅为开发准备', action='config'))
            for j in jobs:
                if j['status'] in ('unknown', 'blocked', 'review'):
                    reason = j.get('next_action', '审核材料')
                    if j['status'] == 'review' and j['material_review_current']:
                        if (j.get('package') or {}).get('blockers'):
                            reason = '补充必填事实或处理材料阻碍'
                        elif any(r.get('status') == 'not_met' for r in (j.get('match') or {}).get('hard', [])):
                            reason = '核对不符合的硬条件'
                        elif reason in ('审核材料', '集中审核事实、缺口、披露范围和最终文件'):
                            continue
                    tasks.append(dict(title=j['title'], reason=reason, job_id=j['id']))
            runs = [json.loads(r[0]) for r in c.execute('SELECT data FROM runs ORDER BY rowid DESC LIMIT 30')]
            from .profile import build_profile
            from .catalog import CATALOG
            return dict(dataset='demo' if self.is_demo else 'app', candidate=candidate,
                        candidate_draft=self.meta(c, 'candidate_draft'), candidate_profile=build_profile(candidate, confirmed_only=True),
                        search_running=self.run_lock.locked() or bool(self.search_thread and self.search_thread.is_alive()),
                        entry_verifications=entry_verifications,
                        company_catalog=CATALOG, config=config, control=self.meta(c, 'control'), jobs=jobs, runs=runs,
                        tasks=tasks, interventions=[json.loads(r[0]) for r in c.execute('SELECT data FROM interventions ORDER BY rowid DESC')],
                        capabilities=[dict(channel='搜索', description='BOSS、猎聘与公司官网按已选来源检索；每轮结果显示实际覆盖与失败。'),
                                      dict(channel='候选人理解', description='本地规则提取与有来源的技能关联；不推断熟练度或录用概率。'),
                                      dict(channel='投递', description='集中审核后才可申请；仅安克具备待线上验证的执行器，其他渠道目前只读。')])

    def import_job(self, data):
        title = str(data.get('title', '')).strip()
        jd = str(data.get('jd', '')).strip()
        if not title or not jd:
            raise Error('请提供岗位名称和 JD 正文')
        if len(jd) > 100000 or len(title) > 500:
            raise Error('岗位文本过长')
        url = data.get('url', '').strip()
        if url:
            parts = urlsplit(url)
            if parts.scheme not in ('https', 'http') or not parts.hostname or parts.username or parts.password:
                raise Error('只接受无凭据的 HTTP(S) 岗位链接')
            from .sources import job_fragment
            url = urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, parts.query, job_fragment(parts)))
        channel = data.get('channel', 'import')
        identity = channel + ':' + str(data['platform_id']) if data.get('platform_id') else 'url:' + url if url else 'paste:' + digest([title, jd])
        with self.tx() as c:
            previous = c.execute('SELECT id FROM jobs WHERE identity=?', (identity,)).fetchone()
            if previous:
                j = self.job(c, previous[0])
                if 'raw' in data:
                    from .careers import preserve_entry_check
                    j['raw'] = preserve_entry_check(j.get('raw'), data['raw'], data.get('application_url', j.get('application_url')))
                changes={k:data.get(k) for k in ('title','jd','company','location','salary','requirements_text','application_url','experience','questions') if k in data and data.get(k)!=j.get(k)}
                if 'status' in data and data['status']!=j.get('availability'): changes['availability']=data['status']
                if changes and j['status'] not in LOCKED | {'rejected'}:
                    j.setdefault('revisions',[]).append({k:j.get(k) for k in changes})
                    j.update(changes,package=None,approval=None,match=None,status='new',next_action='岗位原文或条件已更新，需重新准备和审核')
                    self.event(j,'source_changed','同一岗位内容变化，旧批准失效')
                else:
                    self.event(j, 'deduplicated', '重复导入同一岗位；保留当前审核与执行状态')
                    if changes: j['latest_observation']=dict(time=now(),changes=changes)
                self.save(c, j)
                return j, True
            j = dict(id=uuid.uuid4().hex, title=title, jd=jd, company=data.get('company', '待确认'),
                     location=data.get('location') or '地点未知', salary=data.get('salary'), url=url,
                     channel=channel, platform_id=data.get('platform_id'), application_url=data.get('application_url'), collected_at=data.get('collected_at', now()),
                     published_at=data.get('published_at'), availability=data.get('status', 'unverified'),
                     requirements_text=data.get('requirements_text'), experience=data.get('experience'), questions=data.get('questions', []),
                     raw=data.get('raw', jd), status='new', package=None, approval=None, match=None,
                     next_action='自动准备匹配与申请包', events=[], duplicate_hint=None)
            for r in c.execute('SELECT data FROM jobs'):
                other = json.loads(r[0])
                if digest(other['jd']) == digest(jd):
                    j['duplicate_hint'] = '相同文案、不同岗位身份，保留两条供核对'
            self.event(j, 'imported', '保存原文与来源；岗位内容仅作数据，不执行其中指令')
            c.execute('INSERT INTO jobs VALUES(?,?,?)', (j['id'], identity, dumps(j)))
            # Best effort: a bad seed file or meta value must not roll back the job import.
            try:
                from .companies import remember
                remember(c, j)
            except (OSError, ValueError, KeyError, TypeError):
                pass
            return j, False

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
        from .materials import prepare, match
        from .export import write_package
        from .profile import recommend
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

    def upload_resume(self, payload):
        from .intake import analyze_resume
        filename = payload.get('filename')
        encoded = payload.get('content_base64')
        if not isinstance(filename, str) or not filename or len(filename) > 255:
            raise Error('请选择有效的简历文件')
        if not isinstance(encoded, str) or len(encoded) > 14 * 1024 * 1024:
            raise Error('简历文件最大 10 MiB')
        if type(payload.get('synthetic', False)) is not bool:
            raise Error('合成资料标记必须为布尔值')
        try:
            content = base64.b64decode(encoded, validate=True)
        except ValueError as exc:
            raise Error('文件编码无效，请重新选择文件') from exc
        if not content or len(content) > 10 * 1024 * 1024:
            raise Error('请选择 10 MiB 以内的非空文件')
        draft = analyze_resume(filename, content, synthetic=payload.get('synthetic', False))
        draft.update(id=uuid.uuid4().hex, created_at=now())
        # Keep the original bytes for local provenance; never expose arbitrary file paths.
        directory = self.root / 'resumes' / draft['id']
        directory.mkdir(parents=True, mode=0o700)
        suffix = Path(filename).suffix.lower()
        original = directory / ('original' + suffix)
        original.write_bytes(content)
        original.chmod(0o600)
        (directory / 'analysis.json').write_text(dumps(draft), encoding='utf-8')
        (directory / 'analysis.json').chmod(0o600)
        with self.tx() as c:
            self.setmeta(c, 'candidate_draft', draft)
        return self.state()

    def confirm_resume(self, payload):
        ids = payload.get('confirmed_fact_ids', [])
        if not isinstance(ids, list) or not ids or any(not isinstance(x, str) for x in ids) or len(ids) != len(set(ids)):
            raise Error('请核对并选择要用于本地匹配的事实')
        with self.tx() as c:
            draft = self.meta(c, 'candidate_draft')
            if not draft or draft.get('id') != payload.get('draft_id'):
                raise Error('简历版本已变化，请刷新并核对新版本')
            if draft.get('status') in ('needs_ocr', 'error', 'failed'):
                raise Error('简历尚未成功提取文字，请先处理解析提示')
            candidate = copy.deepcopy(draft['candidate'])
            if set(ids) - {f['id'] for f in candidate['facts']}:
                raise Error('所选事实不属于这份简历')
            for fact in candidate['facts']:
                fact['status'] = 'confirmed' if fact['id'] in ids else 'unconfirmed'
                fact['disclosure'] = 'private'
            candidate['version'] = int(self.meta(c, 'candidate').get('version', 0)) + 1
            self.setmeta(c, 'candidate', candidate)
            self.setmeta(c, 'candidate_draft', None)
            self.intervene(c, '核对上传简历，用于本地画像与匹配；未授权任何对外申请')
            # Persist a clear stale state, rather than presenting old recommendations as current.
            for row in c.execute('SELECT data FROM jobs').fetchall():
                job = json.loads(row[0])
                if job['status'] not in LOCKED | {'rejected'}:
                    job.update(status='new', package=None, approval=None, match=None, recommendation=None, next_action='候选资料已更新，运行搜索或重新准备以更新匹配')
                    self.save(c, job)

    def start_run(self, demo=False):
        with self.start_lock:
            if self.run_lock.locked() or self.search_thread and self.search_thread.is_alive():
                raise Error('本轮已在运行')
            if not self.is_running():
                raise Error('活动已暂停或停止，先恢复再运行')
            self.search_thread = threading.Thread(target=self.run, kwargs={'demo': demo}, daemon=True)
            self.search_thread.start()

    def run(self, demo=False):
        if not self.run_lock.acquire(False):
            raise Error('本轮已在运行')
        run = dict(id=uuid.uuid4().hex, started_at=now(), kind='fixture' if demo else 'real_discovery', discovered=0,
                   duplicates=0, imported=0, prepared=0, applicable=0, verified_submissions=0, failures=[], status='running', user_interventions=0)
        try:
            with self.tx() as c:
                cfg = self.meta(c, 'config')
                candidate = self.meta(c, 'candidate')
                if self.meta(c, 'control') != 'running':
                    raise Error('活动已暂停或停止，先恢复再运行')
            if demo:
                if not self.is_demo:
                    raise Error('合成夹具仅允许在独立 --demo 数据目录运行')
                items = [dict(title='Python 数据工具工程师（合成夹具）',company='合成示例公司',location='深圳',jd='使用 Python 编写数据处理脚本。\n至少 3 年相关开发经验。\n熟悉 Kubernetes。',channel='fixture',platform_id='fixture-python',status='fixture')]
            else:
                with self.tx() as c:
                    c.execute('INSERT INTO runs VALUES(?,?)', (run['id'], dumps(run)))
                if self.channel is not None:
                    items = self.channel.discover(limit=min(cfg['max_jobs'], 5), keyword=cfg['keyword'])
                    if getattr(self.channel, 'last_discovery', None):
                        run['discovery'] = self.channel.last_discovery
                else:
                    from .discovery import discover
                    from .profile import build_profile
                    def source_progress(report):
                        run.setdefault('sources', []).append(copy.deepcopy(report))
                        with self.tx() as connection:
                            connection.execute('UPDATE runs SET data=? WHERE id=?', (dumps(run), run['id']))
                    if cfg.get('sweep') is True and 'discovery_sources' not in cfg:
                        from . import companies
                        from .discovery import search_terms
                        try:
                            with self.tx() as c: extra = companies.encountered(c)
                        except (ValueError, TypeError): extra = []
                        cfg = dict(cfg, discovery_sources=companies.select(search_terms(cfg), cfg.get('sweep_max_companies', 300), extra))
                    result = discover(cfg, profile=build_profile(candidate, confirmed_only=True),
                                      should_continue=self.is_running, browser_profile_root=self.root / 'browser-search',
                                      on_source=source_progress)
                    items = result['jobs']
                    run['sources'] = result.get('sources', [])
                    run['queries'] = result.get('queries', [])
                    run['expanded_terms'] = result.get('expanded_terms', {})
                    if result.get('sweep'):
                        run.update(sweep=result['sweep'], deadline_reached=result.get('deadline_reached', False))
                    run['coverage_note'] = result.get('coverage_note', '仅覆盖本轮已配置来源与请求预算，不代表全网完整结果')
            if not self.is_running():
                with self.tx() as c:
                    run['status'] = self.meta(c, 'control')
            run['discovered'] = len(items)
            sweep = run.get('sweep')
            # A sweep imports everything it found but prepares only the first few, in discovery order.
            for index, item in enumerate(items[:sweep['max_jobs']] if sweep else items[:cfg['max_jobs']]):
                with self.tx() as c:
                    if self.meta(c, 'control') != 'running':
                        run['status'] = self.meta(c, 'control')
                        break
                try:
                    j, duplicate = self.import_job(item)
                    run['duplicates'] += int(duplicate)
                    run['imported'] += 1
                    if (not sweep or index < sweep['prepare']) and j['status'] not in LOCKED | {'rejected', 'approved'}:
                        j = self.prepare(j['id'])
                        run['prepared'] += 1
                        run['applicable'] += int(not j['package'].get('blockers') and not synthetic_profile(candidate) and cfg['targets_confirmed'] and j['channel']=='anker' and not any(x.get('status') == 'not_met' for x in j['match'].get('hard', [])))
                except Exception as e:
                    run['failures'].append(str(e))
            if run['status'] == 'running':
                failed_sources = [s for s in run.get('sources', []) if s.get('status') not in ('ok', 'success', 'completed', 'empty', 'filtered_empty') or s.get('truncated')]
                if run.get('deadline_reached'): run['truncated'] = True
                run['status'] = 'partial' if run.get('deadline_reached') else ('partial' if items else 'blocked') if failed_sources else ('empty' if not items else 'completed')
                if run['failures']:
                    run['status'] = 'partial' if run['prepared'] or sweep and run['imported'] else 'failed'
        except Exception as e:
            run.update(status='failed', failures=run['failures'] + [str(e)])
        finally:
            run['finished_at'] = now()
            with self.tx() as c:
                run['user_interventions'] = c.execute('SELECT COUNT(*) FROM interventions WHERE json_extract(data,\'$.time\')>=?',(run['started_at'],)).fetchone()[0]
                c.execute('INSERT OR REPLACE INTO runs VALUES(?,?)', (run['id'], dumps(run)))
            self.run_lock.release()
        return run

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
            from .anker import Anker
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

    def is_running(self):
        with self.tx() as c:
            return self.meta(c,'control')=='running'

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
        from .moka_session import MokaVerifier, entry_identity
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

    def action(self,payload):
        action=payload.get('action')
        if action=='run': self.start_run(demo=self.is_demo)
        elif action=='demo': self.start_run(demo=True)
        elif action=='resume_confirm': self.confirm_resume(payload)
        elif action=='entry_verify': self.start_entry_verification(payload['job_id'])
        elif action in ('entry_finish', 'entry_cancel'):
            with self.entry_lock:
                signals = self.entry_signals.get(payload['job_id'])
                if not signals: raise Error('核验窗口已结束')
                signals[0 if action == 'entry_finish' else 1].set()
        elif action=='import':
            data=dict(payload)
            if not data.get('jd') and data.get('url'):
                from .network import fetch
                from html.parser import HTMLParser
                class Text(HTMLParser):
                    def __init__(self): super().__init__(); self.parts=[]; self.skip=0
                    def handle_starttag(self,t,a):
                        if t in ('script','style'): self.skip+=1
                    def handle_endtag(self,t):
                        if t in ('script','style'): self.skip=max(0,self.skip-1)
                    def handle_data(self,d):
                        if not self.skip and d.strip(): self.parts.append(d.strip())
                parser=Text(); parser.feed(fetch(data['url']).decode('utf-8',errors='replace'))
                data['jd']='\n'.join(parser.parts)[:100000]
                data['title']=data.get('title') or 'URL 导入岗位（标题待核对）'
            j,_=self.import_job(data); self.prepare(j['id'])
        elif action=='prepare': self.prepare(payload['job_id'])
        elif action=='review_materials': self.review_materials(payload)
        elif action=='review': self.review(payload)
        elif action=='execute': self.execute(payload['job_id'])
        elif action=='control':
            if payload.get('value') not in ('running','paused','stopped'): raise Error('活动状态无效')
            with self.tx() as c: self.setmeta(c,'control',payload['value'])
        elif action=='config':
            cfg=dict(DEFAULT_CONFIG,**payload.get('config',{}))
            if not isinstance(cfg['cities'],list) or len(cfg['cities'])>20 or any(not isinstance(x,str) or len(x)>100 for x in cfg['cities']) or not 1<=int(cfg['max_jobs'])<=50 or not 1<=float(cfg['interval_minutes'])<=10080 or not 0<=int(cfg['submission_limit'])<=5:
                raise Error('每轮准备 1-50 岗、间隔至少 1 分钟、提交额度 0-5')
            cfg['max_jobs']=int(cfg['max_jobs']);cfg['submission_limit']=int(cfg['submission_limit'])
            if type(cfg['targets_confirmed']) is not bool: raise Error('需要明确确认目标')
            if type(cfg.get('official_only', False)) is not bool: raise Error('官网模式必须为明确的开关')
            if any(type(cfg.get(k, False)) is not bool for k in ('check_entries', 'official_browser')): raise Error('入口核验与公开渲染必须为开关')
            if type(cfg.get('sweep', False)) is not bool: raise Error('大范围搜索必须为开关')
            for key, low, high in (('sweep_max_companies', 1, 1000), ('sweep_max_jobs', 1, 5000), ('sweep_requests', 1, 10000),
                                   ('sweep_deadline_seconds', 30, 3600), ('sweep_prepare', 0, 200)):
                if key in cfg and (type(cfg[key]) is not int or not low <= cfg[key] <= high):
                    raise Error('大范围搜索参数 %s 必须是 %d 至 %d 的整数' % (key, low, high))
            if cfg.get('browser_channel') not in (None, 'chrome'): raise Error('仅支持默认 Chromium 或 Google Chrome')
            if not isinstance(cfg.get('keyword'),str) or len(cfg['keyword'])>100:
                raise Error('岗位关键词最长 100 字符')
            keywords=cfg.get('keywords',[])
            if not isinstance(keywords,list) or len(keywords)>8 or any(not isinstance(q,str) or not q.strip() or len(q)>100 for q in keywords):
                raise Error('设置 0-8 个岗位搜索词，每个不超过 100 字符')
            sources=cfg.get('sources',[])
            if not isinstance(sources,list) or not sources or any(not isinstance(s,str) for s in sources) or len(sources)!=len(set(sources)) or set(sources)-{'boss','liepin','anker','greenhouse','lever','ashby','website'}:
                raise Error('请选择支持的搜索渠道')
            boards=cfg.get('company_boards',[])
            if not isinstance(boards,list) or len(boards)>20:
                raise Error('公司官网配置最多 20 个')
            sources=cfg.get('discovery_sources')
            if sources is not None:
                cap=cfg.get('sweep_max_companies',300) if cfg.get('sweep') else 20
                if not isinstance(sources,list) or len(sources)>cap or any(not isinstance(s,dict) for s in sources):
                    raise Error('搜索来源 discovery_sources 必须是对象数组，最多 %d 个' % cap)
            import re
            from .network import validate_url
            for board in boards:
                if isinstance(board,dict) and board.get('type')=='website':
                    validate_url(board.get('url'))
                    continue
                if not isinstance(board,dict) or board.get('type') not in ('greenhouse','lever','ashby') or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',str(board.get('slug',''))) or len(str(board.get('company','')))>200:
                    raise Error('官网需填写平台、公司标识和名称')
            cfg['max_pages']=int(cfg.get('max_pages',2))
            if not 1<=cfg['max_pages']<=5:
                raise Error('每渠道每关键词最多 1-5 页')
            cfg['keywords']=list(dict.fromkeys(q.strip() for q in keywords))
            modes=cfg.get('source_modes',{})
            if not isinstance(modes,dict) or set(modes)-{'boss','liepin'} or any(v not in ('public','browser') for v in modes.values()):
                raise Error('采集模式仅支持公开读取或独立浏览器')
            provider=cfg.get('search_provider')
            if provider:
                if not isinstance(provider,dict) or provider.get('provider')!='searxng':
                    raise Error('通用搜索目前支持 SearXNG JSON 接口')
                validate_url(provider.get('url'))
            # Local profile roots are fixed by the runner, never accepted from requests.
            cfg.pop('browser_profile_root',None)
            with self.tx() as c: self.setmeta(c,'config',cfg); self.intervene(c,'更新求职范围')
        elif action=='candidate':
            candidate=payload.get('candidate')
            if not isinstance(candidate,dict) or not isinstance(candidate.get('facts'),list): raise Error('候选资料需包含 facts 数组')
            ids=set()
            for f in candidate['facts']:
                if not isinstance(f,dict) or not all(k in f for k in ('id','text','source','status','version','disclosure')) or not isinstance(f['id'],str) or f['id'] in ids or not isinstance(f['source'],dict): raise Error('事实需唯一 ID、原文、来源、状态、版本和披露范围')
                if f['source'].get('kind')=='generated' or f['source'].get('kind')=='draft': raise Error('生成草稿不能作为事实源')
                ids.add(f['id'])
            if synthetic_profile(candidate):
                candidate['synthetic']=True
            with self.tx() as c:
                candidate['version']=int(self.meta(c,'candidate').get('version',0))+1
                self.setmeta(c,'candidate',candidate);self.intervene(c,'本地导入候选事实')
                for row in c.execute('SELECT data FROM jobs').fetchall():
                    job=json.loads(row[0])
                    if job['status'] not in LOCKED | {'rejected'}:
                        job.update(status='new',package=None,approval=None,match=None,recommendation=None,next_action='候选资料已更新，需重新准备和审核')
                        self.save(c,job)
        elif action=='event':
            kind=payload.get('kind')
            if kind not in ('note','followup_draft','interview','reply','chat_sent','hr_read'): raise Error('事件类型无效；不能手工注入申请成功')
            if kind in ('chat_sent','hr_read','reply') and not payload.get('evidence'): raise Error('需要对应事件的证据')
            with self.tx() as c:
                j=self.job(c,payload['job_id']);self.event(j,kind,str(payload.get('note','')),payload.get('evidence'));self.save(c,j)
        else: raise Error('未知操作')
        return self.state()
