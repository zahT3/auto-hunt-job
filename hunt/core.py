"""The Store: one SQLite file, its transactions, the state view, job import, and the action table.

Use cases live in mixins: workbench actions (workbench.actions), orientation and AI settings (ai.*), the search run
and candidate facts (app.*). All outbound application actions enter through WorkbenchActions.execute().
"""
import copy
import json
import secrets
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from . import directions, orient
from .ai.orientation import OrientActions
from .ai.settings import AiSettings
from .app.candidate import CandidateActions
from .app.config import DEFAULT_CONFIG, validate_config
from .app.search_run import SearchRun
from .base import Error, digest, dumps, now
from .profile import build_profile, synthetic_profile
from .workbench.actions import LOCKED, WorkbenchActions


def summary_only(raw):
    return isinstance(raw, dict) and raw.get('summary_only') is True


class Store(WorkbenchActions, OrientActions, AiSettings, SearchRun, CandidateActions):
    llm_transport = None  # tests inject a fake; None means network.fetch

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
            for key, value in [('candidate', synthetic_candidate()), ('config', DEFAULT_CONFIG), ('control', 'running'), ('candidate_draft', None), ('encountered_companies', []), ('ai_consent', None), ('orientation', None)]:
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
            orientation = self.meta(c, 'orientation')
            table = directions.load()
            if orientation:
                # Per-direction terms are computed for display only; the search still uses orientation['terms'].
                known = {r['id'] for r in table}
                orientation = dict(orientation, directions=[dict(d, terms=orient.terms_for([d['id']]) if d.get('id') in known else [])
                                                            for d in orientation.get('directions') or []])
            return dict(dataset='demo' if self.is_demo else 'app', candidate=candidate, orientation=orientation,
                        direction_table=[dict(id=r['id'], name=r['name'], family=r['family']) for r in table],
                        candidate_draft=self.meta(c, 'candidate_draft'), candidate_profile=build_profile(candidate, confirmed_only=True),
                        search_running=self.run_lock.locked() or bool(self.search_thread and self.search_thread.is_alive()),
                        entry_verifications=entry_verifications,
                        company_catalog=CATALOG, config=config, ai=self._ai(c), control=self.meta(c, 'control'), jobs=jobs, runs=runs,
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
                # A search-card summary (猎聘 card mode, the search-page bookmarklet) never replaces a job already read in full.
                if summary_only(data.get('raw')) and not summary_only(j.get('raw')):
                    self.event(j, 'deduplicated', '搜索结果卡片再次出现；保留已读到的完整岗位内容')
                    self.save(c, j)
                    return j, True
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

    def inbox_token(self):
        with self.tx() as c:
            c.execute('INSERT OR IGNORE INTO meta VALUES(?,?)', ('inbox_token', dumps(secrets.token_urlsafe(32))))
            return self.meta(c, 'inbox_token')

    def reset_inbox_token(self):
        value = secrets.token_urlsafe(32)
        with self.tx() as c:
            c.execute('INSERT OR REPLACE INTO meta VALUES(?,?)', ('inbox_token', dumps(value)))
        return value

    def receive_inbox(self, payload):
        from .inbox import normalize_payload
        from .sources import SourceError
        try:
            job = normalize_payload(payload)
        except SourceError as e:
            raise Error(str(e)) from e
        saved, duplicate = self.import_job(job)
        return dict(ok=True, job_id=saved['id'], duplicate=duplicate)

    def is_running(self):
        with self.tx() as c:
            return self.meta(c,'control')=='running'

    def set_control(self, value):
        if value not in ('running','paused','stopped'): raise Error('活动状态无效')
        with self.tx() as c: self.setmeta(c,'control',value)

    def save_config(self, config):
        cfg=validate_config(config)
        with self.tx() as c: self.setmeta(c,'config',cfg); self.intervene(c,'更新求职范围')

    def import_and_prepare(self, payload):
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

    def action(self,payload):
        name=payload.get('action')
        handler=ACTIONS.get(name) if isinstance(name,str) else None
        if not handler: raise Error('未知操作')
        handler(self,payload)
        return self.state()


# Action name -> handler(store, payload). The names are the HTTP API of /api/action; keep them stable.
ACTIONS = {
    'run': lambda s, p: s.start_run(demo=s.is_demo),
    'demo': lambda s, p: s.start_run(demo=True),
    'ai_settings': lambda s, p: s.save_ai_settings(p),
    'ai_consent': lambda s, p: s.grant_ai_consent(p),
    'ai_revoke': lambda s, p: s.revoke_ai_consent(),
    'resume_confirm': lambda s, p: s.confirm_resume(p),
    'orient_questions': lambda s, p: s.orient_questions(),
    'orient_answer': lambda s, p: s.orient_answer(p),
    'directions_set': lambda s, p: s.directions_set(p),
    'classify': lambda s, p: s.classify(p),
    'entry_verify': lambda s, p: s.start_entry_verification(p['job_id']),
    'entry_finish': lambda s, p: s.signal_entry_verification(p['job_id'], finish=True),
    'entry_cancel': lambda s, p: s.signal_entry_verification(p['job_id'], finish=False),
    'import': lambda s, p: s.import_and_prepare(p),
    'prepare': lambda s, p: s.prepare(p['job_id']),
    'review_materials': lambda s, p: s.review_materials(p),
    'review': lambda s, p: s.review(p),
    'execute': lambda s, p: s.execute(p['job_id']),
    'control': lambda s, p: s.set_control(p.get('value')),
    'config': lambda s, p: s.save_config(p.get('config',{})),
    'candidate': lambda s, p: s.import_candidate(p.get('candidate')),
    'event': lambda s, p: s.add_event(p),
}
