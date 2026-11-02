"""JD structure, match explanation and natural-language search parameters on a Store (actions jd_extract, job_match, nl_query)."""
import json

from . import jd, llm, match, nlquery, orient
from ..base import Error
from ..net import network

MAX_JOBS = 1000


class AssistActions:
    """Read-only AI assistance, mixed into the Store. Each returns a JSON-ready dict; none writes jobs or runs a search."""

    def _assist_inputs(self):
        with self.tx() as c:
            consent, candidate, orientation = self.meta(c, 'ai_consent'), self.meta(c, 'candidate'), self.meta(c, 'orientation')
        settings = llm.load_settings(self.root)
        return dict(settings=settings, key=llm.load_key(self.root, llm.host(settings)), consent=consent, candidate=candidate,
                    conditions=(orientation or {}).get('conditions'),
                    chosen=[d['id'] for d in (orientation or {}).get('directions') or [] if isinstance(d, dict)],
                    meter=llm.Meter(settings['budget_cny'], settings['price_in'], settings['price_out']),
                    transport=self.llm_transport or network.fetch)

    def _jobs(self, ids, limit):
        with self.tx() as c:
            if ids is None:
                return [json.loads(r[0]) for r in c.execute('SELECT data FROM jobs ORDER BY rowid LIMIT ?', (limit,))]
            return [self.job(c, str(i)) for i in ids]

    def jd_extract(self, payload):
        """payload: job_ids (1-1000 ids) or limit (first N jobs, default 50). Model results are cached by JD digest."""
        ids, limit = payload.get('job_ids'), payload.get('limit', 50)
        if ids is not None and not (isinstance(ids, list) and 1 <= len(ids) <= MAX_JOBS):
            raise Error('job_ids 须是 1 到 %d 个岗位 id' % MAX_JOBS)
        if type(limit) is not int or not 1 <= limit <= MAX_JOBS:
            raise Error('limit 须是 1 到 %d 的整数' % MAX_JOBS)
        jobs = self._jobs(ids, limit)
        a = self._assist_inputs()
        found, report = jd.extract(jobs, self.root, a['settings'], a['key'], a['consent'], a['meter'], transport=a['transport'])
        return dict(schema_version=1, jobs=[dict(job_id=j['id'], title=j.get('title'), company=j.get('company'), structure=found[j['id']])
                                            for j in jobs], report=report)

    def job_match(self, payload):
        """payload: job_id. Reads (or extracts) the job's structure and screens it in ATS order against confirmed facts; no score."""
        if not isinstance(payload.get('job_id'), str):
            raise Error('请提供 job_id')
        job = self._jobs([payload['job_id']], 1)[0]
        a = self._assist_inputs()
        found, report = jd.extract([job], self.root, a['settings'], a['key'], a['consent'], a['meter'], transport=a['transport'])
        structure = found[job['id']]
        return dict(schema_version=1, job_id=job['id'], title=job.get('title'), company=job.get('company'), structure_by=structure['by'],
                    structure=structure, **match.explain(structure, orient.confirmed_facts(a['candidate']), a['conditions']), extract_note=report['note'])

    def nl_query(self, payload):
        """payload: text. Returns search parameters for the caller to confirm; never runs the search."""
        a = self._assist_inputs()
        try:
            out = nlquery.parse(payload.get('text'), a['settings'], a['key'], a['consent'], a['meter'], transport=a['transport'],
                                chosen=a['chosen'])
        except ValueError as e:
            raise Error(str(e)) from None
        return dict(schema_version=1, **out)
