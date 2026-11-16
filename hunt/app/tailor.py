"""Per-job résumé tailoring on a Store (actions tailor, tailor_get, tailor_review, tailor_export; design sections 4, 8, 10).

A tailored résumé is stored as the section 4.1 document in the `tailored` table: the confirmed facts are never copied,
only the list of edits and their statuses. The text of a version is always recomputed from the current facts and the
accepted edits, so a fact that changed makes its edits `stale` instead of leaking old words into an export.
"""
import json
import re

from ..ai import llm, match as ai_match, orient, tailor as ai_tailor
from ..base import Error, digest, dumps, now
from ..profile import claims, resume_render, structure, tailor

MAX_FORMAT_STEMS = 80
REASONS = dict(
    no_facts='还没有已确认的事实，先确认简历事实。',
    no_structure='还没有简历结构，先在确认页核对。',
    unconfirmed='简历结构还没有确认，先在确认页核对。',
    stale='简历结构需要重新核对：有条目过期或字段待确认。',
    empty='简历结构里还没有可导出的条目，请先在确认页把事实分到条目里。',
)
SECTION_TITLES = dict(basic='基本信息', education='教育背景', work='工作经历', internship='实习经历', project='项目经历', skills='专业技能',
                      certificates='证书', awards='奖项', summary='自我评价', other='其他')
GATE_TEXT = dict(
    malformed='修改格式不对', op_not_allowed='操作不在允许范围内', not_confirmed='引用的事实未确认', stale_fact='引用的事实已变',
    duplicate_fact='重复引用同一条事实', unknown_target='这条事实不是可修改的要点', cross_entry='修改跨了多个条目',
    identity_line='身份行不允许改写', before_mismatch='原文与事实不一致', reorder_set_mismatch='调序改变了条目集合',
    alias_not_whitelisted='换词不在同义白名单里', after_missing='改写后的文字为空', conflict='和另一条已接受的修改冲突')


class TailorActions:
    """Résumé tailoring for one job, mixed into the Store."""

    # ---- storage ----

    def _tailor_ensure(self, c):
        c.execute('CREATE TABLE IF NOT EXISTS tailored(id TEXT PRIMARY KEY, job_id TEXT, version INTEGER, data TEXT NOT NULL, '
                  'created TEXT, UNIQUE(job_id, version))')

    def _tailor_load(self, c, job_id, version=None):
        self._tailor_ensure(c)
        if version is None:
            row = c.execute('SELECT data FROM tailored WHERE job_id=? ORDER BY version DESC LIMIT 1', (job_id,)).fetchone()
        else:
            row = c.execute('SELECT data FROM tailored WHERE job_id=? AND version=?', (job_id, version)).fetchone()
        return json.loads(row[0]) if row else None

    def _tailor_versions(self, c, job_id):
        self._tailor_ensure(c)
        return [dict(version=d['version'], by=d['by'], created_at=d['created_at'], edits=len(d['edits']))
                for d in (json.loads(r[0]) for r in c.execute('SELECT data FROM tailored WHERE job_id=? ORDER BY version', (job_id,)))]

    def _tailor_save(self, c, doc, insert=False):
        if insert:
            c.execute('INSERT INTO tailored(id,job_id,version,data,created) VALUES(?,?,?,?,?)',
                      (doc['id'], doc['job_id'], doc['version'], dumps(doc), doc['created_at']))
        else:
            c.execute('UPDATE tailored SET data=? WHERE id=?', (dumps(doc), doc['id']))

    @staticmethod
    def _tailor_ids(payload):
        job_id, version = payload.get('job_id'), payload.get('version')
        if not isinstance(job_id, str) or not job_id: raise Error('请提供 job_id')
        if version is not None and (type(version) is not int or version < 1): raise Error('version 必须是正整数')
        return job_id, version

    # ---- inputs ----

    def _tailor_gate(self):
        """(structure, confirmed facts, None) when tailoring may go on, else (None, facts, why) with why = dict(code, reason)."""
        current, facts = self.structure_current()
        live = structure.confirmed(facts)
        if not live: return None, [], self._tailor_need('no_facts', None)
        if current is None: return None, live, self._tailor_need('no_structure', None)
        if current.get('status') != 'confirmed': return None, live, self._tailor_need('unconfirmed', current)
        open_items = structure.open_items(current)
        if open_items['stale'] or open_items['uncertain']: return None, live, self._tailor_need('stale', current)
        return current, live, None

    @staticmethod
    def _tailor_need(code, current):
        return dict(code=code, reason=REASONS[code], structure_status=(current or {}).get('status'),
                    open=structure.open_items(current) if current else None)

    @staticmethod
    def _tailor_requirements(m):
        """Rows for the model, with the same refs the rule path writes (k = keywords, d = evidence, h = hard)."""
        rows = []
        for i, r in enumerate(m.get('hard') or []):
            if r.get('status') == 'met': rows.append(dict(ref=f'h{i}', type='hard', value=r.get('requirement'), jd_evidence=r.get('jd_evidence')))
        for i, r in enumerate(m.get('keywords') or []):
            if r.get('coverage') in ('explicit', 'related'): rows.append(dict(ref=f'k{i}', type='keyword', value=r.get('keyword'), jd_evidence=r.get('jd_evidence')))
        for i, r in enumerate(m.get('evidence') or []):
            if r.get('status') in ('supported', 'related'): rows.append(dict(ref=f'd{i}', type='duty', value=r.get('requirement'), jd_evidence=r.get('jd_evidence')))
        return [r for r in rows if isinstance(r['value'], str) and r['value']]

    def _tailor_ai_state(self, facts, requirements):
        a = self._assist_inputs()
        mode, why = orient.model_mode(a['consent'], a['settings'], a['key'], facts)
        if mode and not llm.consent_ok(a['consent'], a['settings'], 'job_text'):
            mode, why = None, '未获得向模型服务发送岗位内容的同意，未使用 AI'
        names = orient.candidate_names(a['candidate'])
        estimate = ai_tailor.estimate(facts, requirements, names, a['settings'], a['consent']) if requirements and facts else None
        return dict(available=bool(mode), reason=why, estimate=estimate), a

    # ---- tailor ----

    def tailor(self, payload):
        """Generate the next version for a job: rule-path edits, plus AI rewrites when `ai` is true and allowed.
        Without a confirmed structure the answer is `needs_structure`, nothing is generated."""
        job_id = self._tailor_ids(payload)[0]
        ai = payload.get('ai', False)
        if type(ai) is not bool: raise Error('ai 必须是布尔值')
        with self.tx() as c: job = self.job(c, job_id)
        current, facts, need = self._tailor_gate()
        if need: return dict(needs_structure=True, **need)
        m = self.job_match(dict(job_id=job_id))
        requirements = self._tailor_requirements(m)
        jd_digest = digest([job.get('title'), job.get('jd')])
        notice = None
        with self.tx() as c:
            versions = self._tailor_versions(c, job_id)
        version = max([v['version'] for v in versions], default=0) + 1
        doc = tailor.build(job_id, version, facts, current, m, jd_digest=jd_digest, created_at=now())
        doc['requirements'] = requirements
        report = dict(requested=ai, used=False, reason=None, spent=0.0, notes=[], cached=False)
        if ai:
            a = self._assist_inputs()
            lines = [l.strip() for l in str(job.get('jd') or '').splitlines() if l.strip()]
            out = ai_tailor.generate(facts, requirements, orient.candidate_names(a['candidate']), a['settings'], a['key'], a['consent'], a['meter'],
                                     root=self.root, transport=a['transport'], jd_digest=jd_digest, jd_lines=lines)
            report.update(used=out['by'] == 'ai', reason=out.get('reason'), spent=out.get('spent', 0.0), notes=out.get('notes') or [],
                          cached=bool(out.get('cached')))
            if out['by'] == 'ai':
                doc['edits'] += out['edits']
                doc['rejected_by_gate'] += out['rejected_by_gate']
                doc.update(by='ai', model=out.get('model'))
        if current and structure.open_items(current)['unassigned']:
            notice = '有已确认的事实还没放进简历结构，它们不会进入定制版；到确认页补一步。'
        with self.tx() as c:
            self._tailor_ensure(c)
            if self._tailor_load(c, job_id, version): raise Error('这个岗位刚生成了新版本，请刷新后重试')
            self._tailor_save(c, doc, insert=True)
        view = self._tailor_view(doc, current, facts, job)
        return dict(view, ai=dict(report, **view['ai']), notice=notice)

    # ---- read ----

    def tailor_get(self, payload):
        job_id, version = self._tailor_ids(payload)
        with self.tx() as c:
            job = self.job(c, job_id)
            doc = self._tailor_load(c, job_id, version)
            versions = self._tailor_versions(c, job_id)
        current, facts, need = self._tailor_gate()
        if not doc:
            if version is not None: raise Error('没有这个版本')
            return dict(document=None, versions=versions, needs_structure=bool(need), **(need or {}))
        view = self._tailor_view(doc, current, facts, job, versions)
        return dict(view, needs_structure=bool(need), **(need or {}))

    def _tailor_view(self, doc, current, facts, job, versions=None):
        """The stored document with its statuses refreshed against today's facts, and what the page draws from it."""
        structure_now = current
        if structure_now is None:
            structure_now = self.structure_current()[0]
        edits = tailor.refresh_status(facts, doc['edits'])
        shown = dict(doc, edits=edits)
        applied = tailor.apply_edits(facts, structure_now, edits)
        result = tailor.check_result(facts, structure_now, applied['rendered'], edits)
        proof = tailor.trace(facts, applied['rendered'], edits)
        original = self._tailor_shape(tailor.apply_edits(facts, structure_now, [])['rendered'])
        shaped = self._tailor_shape(applied['rendered'])
        withheld = self._tailor_withheld(applied['rendered'], facts)
        by_id = {f['id']: f for f in facts}
        cited = {r['id'] for e in edits for r in e['fact_ids']}
        shown['checks'] = dict(shown.get('checks') or {}, trace=proof['status'], result='pass' if result['ok'] else 'fail')
        if versions is None:
            with self.tx() as c: versions = self._tailor_versions(c, doc['job_id'])
        ai_state, _ = self._tailor_ai_state(facts, doc.get('requirements') or [])
        empty = not any(sec['lines'] for sec in shaped['sections'])
        return dict(document=shown, empty=empty, basic_withheld=withheld, rendered=shaped, original=original, applied=applied['applied'], hidden=applied['hidden'],
                    rejected_in_view=[dict(edit_id=r['edit'].get('id'), reason=r['reason'], text=GATE_TEXT.get(r['reason'], r['reason']))
                                      for r in applied['rejected_by_gate']],
                    trace=dict(status=proof['status'], problems=proof['problems']), result=result,
                    facts={i: dict(id=i, version=by_id[i].get('version', 1), text=by_id[i]['text'],
                                   reference=(by_id[i].get('source') or {}).get('reference') if isinstance(by_id[i].get('source'), dict) else None)
                           for i in cited if i in by_id},
                    pending=sum(1 for e in edits if e['status'] == 'pending'), stale=sum(1 for e in edits if e['status'] == 'stale'),
                    structure_changed=(doc.get('structure') or {}).get('version') != (structure_now or {}).get('version'),
                    versions=versions, latest=bool(versions) and versions[-1]['version'] == doc['version'], ai=ai_state,
                    job=dict(id=job['id'], title=job.get('title'), company=job.get('company')))

    # ---- review ----

    def tailor_review(self, payload):
        """Set edit statuses on the newest version: `accept`, `reject`, `pending` are lists of edit ids. An edit is accepted only
        if it still passes the local checks (the hard gate for AI rewrites, the four gates of apply_edits) and is not stale."""
        job_id, version = self._tailor_ids(payload)
        wanted = {}
        for name, status in (('accept', 'accepted'), ('reject', 'rejected'), ('pending', 'pending')):
            ids = payload.get(name) or []
            if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids): raise Error(f'{name} 必须是修改 id 的列表')
            for i in ids:
                if i in wanted: raise Error(f'修改 {i} 被同时放进了多个列表')
                wanted[i] = status
        if not wanted: raise Error('请至少给出一条要改状态的修改（accept、reject 或 pending）')
        with self.tx() as c:
            job = self.job(c, job_id)
            doc = self._tailor_load(c, job_id, version)
            if not doc: raise Error('没有这个版本')
            latest = self._tailor_versions(c, job_id)[-1]['version']
        if doc['version'] != latest: raise Error('旧版本只读；只能审核最新版本')
        current, facts, need = self._tailor_gate()
        if not facts: raise Error(REASONS['no_facts'])
        structure_now = current or self.structure_current()[0]
        edits = tailor.refresh_status(facts, doc['edits'])
        by_edit = {e['id']: e for e in edits}
        unknown = [i for i in wanted if i not in by_edit]
        if unknown: raise Error('没有这些修改：' + '、'.join(unknown))
        by_fact = {f['id']: f for f in facts}
        lines = [l.strip() for l in str(job.get('jd') or '').splitlines() if l.strip()]
        keywords = [r['value'] for r in doc.get('requirements') or [] if r.get('type') == 'keyword']
        for edit_id, status in wanted.items():
            edit = by_edit[edit_id]
            if status == 'accepted':
                if edit['status'] == 'stale': raise Error(f'修改 {edit_id} 引用的事实已变，需重新生成')
                if edit['by'] == 'ai':
                    cited = {r['id']: by_fact[r['id']] for r in edit['fact_ids'] if r['id'] in by_fact}
                    verdict = claims.check_rephrase(edit, cited, jd_lines=lines, keywords=keywords)
                    if not verdict['ok']:
                        raise Error(f'修改 {edit_id} 没通过硬检查，不能接受：' + '；'.join(str(h.get('code')) for h in verdict['hard']))
                    edit['checks'] = dict(edit.get('checks') or {}, flags=verdict['flags'], hard='pass')
            if status == 'accepted' or edit['status'] != 'stale': edit['status'] = status
        trial = tailor.apply_edits(facts, structure_now, edits)
        refused = {r['edit'].get('id'): r['reason'] for r in trial['rejected_by_gate']}
        bad = [i for i, s in wanted.items() if s == 'accepted' and i in refused]
        if bad: raise Error('；'.join(f"修改 {i} 没通过本地检查：{GATE_TEXT.get(refused[i], refused[i])}" for i in bad))
        doc = dict(doc, edits=edits, checks=dict(doc.get('checks') or {}, export=None))
        with self.tx() as c: self._tailor_save(c, doc)
        return self.tailor_get(dict(job_id=job_id, version=doc['version']))

    # ---- export ----

    def tailor_export(self, payload):
        """Write MD / PDF / DOCX and trace.json for a version into <data>/tailored/<job>/v<N>/ (0700, files 0600), re-read each file
        and return the result. Nothing is written when the trace check fails; pending edits are left out."""
        job_id, version = self._tailor_ids(payload)
        formats = payload.get('formats') or list(resume_render.FORMATS)
        if not isinstance(formats, list) or not formats or any(f not in resume_render.FORMATS for f in formats):
            raise Error('formats 只能取：' + '、'.join(resume_render.FORMATS))
        with self.tx() as c:
            job = self.job(c, job_id)
            doc = self._tailor_load(c, job_id, version)
        if not doc: raise Error('没有这个版本；先生成')
        current, facts, need = self._tailor_gate()
        if need: return dict(needs_structure=True, **need)
        edits = tailor.refresh_status(facts, doc['edits'])
        applied = tailor.apply_edits(facts, current, edits)
        proof = tailor.trace(facts, applied['rendered'], edits)
        if proof['status'] != 'pass': raise Error('导出前检查没通过，没有写任何文件：' + '；'.join(f"{p['code']}：{p.get('line', '')}" for p in proof['problems'][:3]))
        m = self.job_match(dict(job_id=job_id))
        conditions = self._assist_inputs()['conditions']
        explain = lambda rows: ai_match.explain(m['structure'], rows, conditions)
        stem = re.sub(r'[\\/:*?"<>|\s]+', '_', f"{job.get('company') or '公司待确认'}-{job.get('title') or '岗位'}")[:MAX_FORMAT_STEMS] + f"-v{doc['version']}"
        include = payload.get('include_private_basic', False)
        if type(include) is not bool: raise Error('include_private_basic 必须是布尔值')
        render = self._tailor_render(applied['rendered'], facts, include)
        if not render['sections']:
            need = self._tailor_need('empty', current)
            if self._tailor_withheld(applied['rendered'], facts):
                need['reason'] = '目前只有披露范围是私密的基本信息，导出文件没有内容：勾选「这次写进导出文件」，或先在确认页把事实分到条目里。'
            return dict(needs_structure=True, **need)
        out_dir = self._tailor_dir(job_id, doc['version'])
        try:
            out = resume_render.export_all(render, out_dir, stem, formats=formats, version=doc['version'], job_id=job_id, explain=explain)
        except (ValueError, OSError) as exc:
            raise Error('导出失败：' + str(exc)) from exc
        ok = bool(out['files']) and all(f['check']['ok'] for f in out['files'].values()) and not out['errors']
        record = dict(at=now(), formats=list(formats), dir=str(out_dir),
                      files={k: dict(path=v['path'], sha256=v['sha256'], size=v['size'], ok=v['check']['ok']) for k, v in out['files'].items()})
        doc = dict(doc, edits=edits, exports=(doc.get('exports') or []) + [record],
                   checks=dict(doc.get('checks') or {}, export='pass' if ok else 'fail'))
        with self.tx() as c: self._tailor_save(c, doc)
        return dict(job_id=job_id, version=doc['version'], dir=str(out_dir), ok=ok, notice=resume_render.NOTICE, excluded_pending=sum(e['status'] == 'pending' for e in edits),
                    withheld_basic=[] if include else self._tailor_withheld(applied['rendered'], facts),
                    files=out['files'], errors=out['errors'], trace_path=out['trace_path'], trace_status=proof['status'])

    def _tailor_dir(self, job_id, version):
        base = self.root / 'tailored'
        for d in (base, base / job_id):
            d.mkdir(exist_ok=True, mode=0o700)
            d.chmod(0o700)
        return base / job_id / f'v{version}'

    @staticmethod
    def _tailor_shape(rendered):
        """What the page draws: the section's standard name from its type, and no title line. A heading fact, or a prefix
        line that is also the entry head, appears once (as the head), never again as a title."""
        return dict(rendered, sections=[dict(s, title=SECTION_TITLES.get(s['key']), lines=[l for l in s['lines'] if l['kind'] != 'title'])
                                        for s in rendered['sections']])

    @staticmethod
    def _tailor_withheld(rendered, facts):
        """Basic-info lines whose disclosure scope is not `application`: the export leaves them out unless the user opts in."""
        by_id = {f['id']: f for f in facts}
        return [dict(id=l['fact_ids'][0]['id'], text=l['text']) for s in rendered['sections'] if s['key'] == 'basic'
                for l in s['lines'] if l['fact_ids'] and by_id.get(l['fact_ids'][0]['id'], {}).get('disclosure') != 'application']

    def _tailor_render(self, rendered, facts, include_private_basic=False):
        """The tailor.py rendering as resume_render's input, standard section names, basic info first and without a title."""
        hold = {w['id'] for w in self._tailor_withheld(rendered, facts)} if not include_private_basic else set()
        sections = []
        for s in self._tailor_shape(rendered)['sections']:
            lines = [dict(text=l['text'], kind='text' if s['key'] == 'basic' else l['kind'], fact_ids=l['fact_ids'], edit_ids=l['edit_ids']) for l in s['lines']
                     if not (s['key'] == 'basic' and l['fact_ids'] and l['fact_ids'][0]['id'] in hold)]
            if lines: sections.append(dict(key=s['key'], title=None if s['key'] == 'basic' else s['title'], lines=lines))
        return dict(sections=sections)
