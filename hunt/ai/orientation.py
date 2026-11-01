"""Orientation (questions, answers, chosen directions) and job classification on a Store."""
import json

from .. import classify, directions, llm, network, orient
from ..base import Error, now
from ..profile import build_profile


class OrientActions:
    """Orientation and classification, mixed into the Store."""

    def orientation(self):
        with self.tx() as c:
            return self.meta(c, 'orientation')

    def _orient_inputs(self):
        with self.tx() as c:
            candidate, consent, current = self.meta(c, 'candidate'), self.meta(c, 'ai_consent'), self.meta(c, 'orientation')
        settings = llm.load_settings(self.root)
        key = llm.load_key(self.root, llm.host(settings))  # None for a key entered for another host
        meter = llm.Meter(settings['budget_cny'], settings['price_in'], settings['price_out'])
        return dict(candidate=candidate, consent=consent, current=current, settings=settings, key=key, meter=meter,
                    facts=orient.confirmed_facts(candidate), names=orient.candidate_names(candidate),
                    transport=self.llm_transport or network.fetch)

    def _orient_save(self, change, spent):
        with self.tx() as c:
            o = self.meta(c, 'orientation') or dict(questions=[], answers={}, directions=[], conditions=orient.clean_conditions({}),
                                                    terms=[], by='rules', notes=[], spent_cny=0.0)
            o.update(change, spent_cny=round(float(o.get('spent_cny', 0)) + spent, 6), updated_at=now())
            self.setmeta(c, 'orientation', o)
            return o

    def orient_questions(self):
        a = self._orient_inputs()
        profile = build_profile(a['candidate'], confirmed_only=True)
        result = orient.questions(profile, a['facts'], a['names'], a['settings'], a['key'], a['consent'], a['meter'], a['transport'])
        change = dict(questions=result['questions'], answers={}, notes=result['notes'], questions_by=result['by'])
        if not (a['current'] or {}).get('directions'): change['by'] = result['by']
        return self._orient_save(change, a['meter'].spent)

    def orient_answer(self, payload):
        a = self._orient_inputs()
        asked = {q['id']: q for q in (a['current'] or {}).get('questions') or []}
        if not asked: raise Error('请先获取追问')
        answers = payload.get('answers')
        if not isinstance(answers, dict): raise Error('回答须是对象')
        for ident, value in answers.items():
            q = asked.get(ident)
            if not q: raise Error('回答里有不在追问中的问题')
            values = [value] if isinstance(value, str) else value
            if not (isinstance(values, list) and len(values) <= 20 and all(isinstance(v, str) and len(v) <= orient.ANSWER_CHARS for v in values)):
                raise Error('回答须是不超过 %d 字的文字（选择题可多选）' % orient.ANSWER_CHARS)
            if q['kind'] == 'choice' and not set(values) <= set(q['options']): raise Error('选择题的回答须在给出的选项里')
            if q['kind'] == 'text' and not isinstance(value, str): raise Error('文字题须用文字回答')
        profile = build_profile(a['candidate'], confirmed_only=True)
        found = orient.propose(profile, answers, a['facts'], a['names'], list(asked.values()), a['settings'], a['key'], a['consent'],
                               a['meter'], a['transport'])
        return self._orient_save(dict(answers=answers, directions=found['directions'], conditions=found['conditions'], terms=found['terms'],
                                      by=found['by'], notes=found['notes']), a['meter'].spent)

    def directions_set(self, payload):
        source = payload.get('source', 'user')
        if source not in ('user', 'agent'): raise Error('来源须是 user 或 agent')
        try:
            rows = orient.clean_directions(payload)
            terms = orient.clean_terms(payload['terms']) if 'terms' in payload else orient.terms_for([r['id'] for r in rows])
            conditions = orient.clean_conditions(payload['conditions']) if 'conditions' in payload else None
        except ValueError as e: raise Error(str(e)) from None
        for row in rows: row['source'] = source
        change = dict(directions=rows, terms=terms, by=source, notes=[])
        if conditions is not None: change['conditions'] = conditions
        return self._orient_save(change, 0.0)

    def chosen_families(self):
        """Families of the chosen directions, in order; a sweep scans employers tagged with them first."""
        rows = (self.orientation() or {}).get('directions') or []
        return list(dict.fromkeys(directions.get(d['id'])['family'] for d in rows))

    def classify_run(self):
        """Classify jobs that have no classification or a stale one (directions or job text changed); user and agent choices stay."""
        with self.tx() as c:
            dirs = (self.meta(c, 'orientation') or {}).get('directions') or []
            consent = self.meta(c, 'ai_consent')
            jobs = [json.loads(r[0]) for r in c.execute('SELECT data FROM jobs ORDER BY rowid')]
        if not dirs:
            return dict(directions=[], other_count=0, classify_spent_cny=0.0, classify_errors=[], classify_note='尚未确定方向，岗位未归类')
        ids = [d['id'] for d in dirs]
        todo = [j for j in jobs if classify.stale(j, ids)]
        settings = llm.load_settings(self.root)
        meter = llm.Meter(settings['budget_cny'], settings['price_in'], settings['price_out'])
        out = classify.classify_jobs(todo, dirs, settings, llm.load_key(self.root, llm.host(settings)), consent, meter,
                                     transport=self.llm_transport or network.fetch)
        with self.tx() as c:
            for j in todo:
                current = json.loads((c.execute('SELECT data FROM jobs WHERE id=?', (j['id'],)).fetchone() or ['null'])[0])
                # A choice made while the model was answering wins.
                if current and (current.get('direction') or {}).get('by') not in ('user', 'agent'):
                    current['direction'] = j['direction']
                    self.save(c, current)
            jobs = [json.loads(r[0]) for r in c.execute('SELECT data FROM jobs')]
        rows, other = classify.report(dirs, jobs)
        return dict(directions=rows, other_count=other, classify_spent_cny=round(meter.spent, 6), classify_errors=out['errors'],
                    classify_note=out['note'] if todo else '方向与岗位都没有变化，沿用上次归类')

    def classify(self, payload):
        """One job by hand (user or agent; null means outside the chosen directions), or every stale job when job_id is absent."""
        if 'job_id' not in payload:
            if self.run_lock.locked(): raise Error('本轮搜索正在运行，结束时会自动归类')
            return self.classify_run()
        row = dict(job_id=payload['job_id'], direction_id=payload.get('direction_id'), reason=payload.get('reason'))
        self.classify_many([row], payload.get('source', 'user'))

    def classify_many(self, rows, source):
        """Hand-made classifications [{job_id, direction_id|null, reason?}], all or nothing; returns how many were written."""
        if source not in ('user', 'agent'): raise Error('来源须是 user 或 agent')
        if not isinstance(rows, list) or not 1 <= len(rows) <= 5000: raise Error('归类结果须是 1–5000 条的数组')
        with self.tx() as c:  # any error below rolls back the rows already written
            ids = [d['id'] for d in (self.meta(c, 'orientation') or {}).get('directions') or []]
            for n, row in enumerate(rows, 1):
                if not isinstance(row, dict) or 'job_id' not in row or 'direction_id' not in row:
                    raise Error('第 %d 条须有 job_id 与 direction_id（不属于所选方向时写 null）' % n)
                ident, reason = row['direction_id'], row.get('reason')
                if ident is not None and ident not in ids: raise Error('第 %d 条：方向须是当前所选方向之一，或 null 表示不属于所选方向' % n)
                if reason is not None and not (isinstance(reason, str) and len(reason) <= 200): raise Error('第 %d 条：理由须是不超过 200 字的文字' % n)
                try: j = self.job(c, str(row['job_id']))
                except Error: raise Error('第 %d 条：岗位不存在：%s' % (n, str(row['job_id'])[:40])) from None
                j['direction'] = dict(id=ident, by=source, score=1.0, reason=(reason or '').strip() or ('用户指定' if source == 'user' else '外部 agent 指定'),
                                      dirs=ids, basis=classify.basis(j), unclear=False)
                self.save(c, j)
        return len(rows)
