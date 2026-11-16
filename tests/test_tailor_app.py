"""Store actions for per-job tailoring: gate on the confirmed structure, versions, review, export, CLI."""
import contextlib
import io
import json
import stat
import tempfile
import unittest
from pathlib import Path

from hunt.app import cli
from hunt.app.store import ACTIONS, RESULT_ACTIONS, Store
from hunt.base import Error

FIX = Path(__file__).parent / 'fixtures' / 'tailor'
JD = '岗位职责：\n负责后端服务开发，熟悉 Kubernetes 和 PostgreSQL。\n任职要求：\n本科及以上学历，3年以上后端经验，熟练使用 Python，熟悉 SQL、Docker。'


class TailorAppCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / 'demo')
        self.addCleanup(self.store.prepare_pool.shutdown)
        candidate = dict(self.store.state()['candidate'], facts=json.loads((FIX / 'facts.json').read_text(encoding='utf-8')))
        self.store.action(dict(action='candidate', candidate=candidate))
        self.job, _ = self.store.import_job(dict(title='后端工程师', company='某科技有限公司', jd=JD))

    def confirm_structure(self):
        got = self.store.structure_get()['structure']
        self.store.structure_save(dict(structure=got, base_version=got['version'], confirm=True))

    def act(self, name, **payload):
        return self.store.action(dict(action=name, **payload))['result']


class GateTests(TailorAppCase):
    def test_actions_are_registered_as_result_actions(self):
        for name in ('tailor', 'tailor_get', 'tailor_review', 'tailor_export'):
            self.assertIn(name, ACTIONS)
            self.assertIn(name, RESULT_ACTIONS)

    def test_prefilled_structure_sends_the_user_to_confirmation(self):
        result = self.act('tailor', job_id=self.job['id'])
        self.assertTrue(result['needs_structure'])
        self.assertEqual(result['code'], 'unconfirmed')
        self.assertIsNone(self.act('tailor_get', job_id=self.job['id'])['document'])

    def test_changed_fact_makes_the_structure_stale_again(self):
        self.confirm_structure()
        with self.store.tx() as c:
            candidate = self.store.meta(c, 'candidate')
            candidate['facts'][6] = dict(candidate['facts'][6], version=2, text=candidate['facts'][6]['text'] + '。')
            self.store.setmeta(c, 'candidate', candidate)
        result = self.act('tailor', job_id=self.job['id'])
        self.assertTrue(result['needs_structure'])
        self.assertEqual(result['code'], 'stale')


class EmptyStructureTests(unittest.TestCase):
    def test_a_structure_without_entries_exports_nothing_and_says_why(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / 'demo')
            self.addCleanup(store.prepare_pool.shutdown)
            got = store.structure_get()['structure']
            self.assertFalse([e for sec in got['sections'] for e in sec['entries']])
            store.structure_save(dict(structure=got, base_version=got['version'], confirm=True))
            job, _ = store.import_job(dict(title='后端工程师', company='某科技有限公司', jd=JD))
            made = store.action(dict(action='tailor', job_id=job['id']))['result']
            self.assertTrue(made['empty'])
            out = store.action(dict(action='tailor_export', job_id=job['id']))['result']
            self.assertTrue(out['needs_structure'])
            self.assertEqual(out['code'], 'empty')
            self.assertIn('确认页', out['reason'])
            self.assertFalse((Path(tmp) / 'demo' / 'tailored' / job['id']).exists())


class FlowTests(TailorAppCase):
    def setUp(self):
        super().setUp()
        self.confirm_structure()

    def test_generate_review_export(self):
        made = self.act('tailor', job_id=self.job['id'])
        self.assertEqual(made['document']['version'], 1)
        self.assertEqual(made['document']['by'], 'rules')
        self.assertFalse(made['ai']['used'])
        self.assertEqual(made['trace']['status'], 'pass')
        edits = made['document']['edits']
        self.assertTrue(edits and all(e['status'] == 'accepted' for e in edits))
        first = edits[0]['id']
        undone = self.act('tailor_review', job_id=self.job['id'], reject=[first])
        self.assertEqual({e['id']: e['status'] for e in undone['document']['edits']}[first], 'rejected')
        back = self.act('tailor_review', job_id=self.job['id'], accept=[first])
        self.assertEqual({e['id']: e['status'] for e in back['document']['edits']}[first], 'accepted')
        with self.assertRaises(Error):
            self.act('tailor_review', job_id=self.job['id'], accept=['nope'])
        out = self.act('tailor_export', job_id=self.job['id'], formats=['md', 'pdf'])
        self.assertTrue(out['ok'], out)
        self.assertIn('不代表任何招聘系统', out['notice'])
        folder = Path(out['dir'])
        self.assertEqual(stat.S_IMODE(folder.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((folder / 'trace.json').stat().st_mode), 0o600)
        self.assertTrue(folder.name == 'v1' and folder.parent.parent.name == 'tailored')
        self.assertEqual(self.act('tailor_get', job_id=self.job['id'])['document']['checks']['export'], 'pass')

    def test_regenerating_adds_a_version_and_old_versions_are_read_only(self):
        self.act('tailor', job_id=self.job['id'])
        second = self.act('tailor', job_id=self.job['id'])
        self.assertEqual(second['document']['version'], 2)
        self.assertEqual([v['version'] for v in second['versions']], [1, 2])
        with self.assertRaises(Error):
            self.act('tailor_review', job_id=self.job['id'], version=1, reject=['e1'])

    def test_ai_without_consent_falls_back_with_a_reason(self):
        made = self.act('tailor', job_id=self.job['id'], ai=True)
        self.assertTrue(made['ai']['requested'])
        self.assertFalse(made['ai']['used'])
        self.assertIn('未使用 AI', made['ai']['reason'])
        self.assertEqual(made['document']['by'], 'rules')

    def test_an_ai_rewrite_with_a_new_number_cannot_be_accepted(self):
        made = self.act('tailor', job_id=self.job['id'])
        doc = made['document']
        fact = next(f for f in made['facts'].values() if '负责' in f['text'])
        doc['edits'].append(dict(id='a1', op='rephrase', fact_ids=[dict(id=fact['id'], version=fact['version'])],
                                 requirement=dict(type='keyword', value='Docker', jd_evidence='熟悉 SQL、Docker', ref='k2'),
                                 before=fact['text'], after=fact['text'] + '，节省 90% 成本', why='x', by='ai', status='pending',
                                 checks=dict(hard='pass', flags=[], reviewer=None)))
        with self.store.tx() as c: self.store._tailor_save(c, doc)
        with self.assertRaises(Error) as ctx:
            self.act('tailor_review', job_id=self.job['id'], accept=['a1'])
        self.assertIn('硬检查', str(ctx.exception))

    def test_pending_edits_stay_out_of_the_export(self):
        made = self.act('tailor', job_id=self.job['id'])
        ids = [e['id'] for e in made['document']['edits']]
        self.act('tailor_review', job_id=self.job['id'], pending=ids)
        out = self.act('tailor_export', job_id=self.job['id'], formats=['md'])
        self.assertEqual(out['excluded_pending'], len(ids))

    def test_cli_prints_the_same_json(self):
        data = ['--data', str(self.store.root)]
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            self.assertEqual(cli.main(['tailor', self.job['id']] + data), 0)
        result = json.loads(buffer.getvalue())
        self.assertEqual(result['schema_version'], 1)
        self.assertEqual(result['document']['version'], 1)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            self.assertEqual(cli.main(['tailor_review', self.job['id'], '--reject', 'e1'] + data), 0)
        self.assertEqual(json.loads(buffer.getvalue())['document']['edits'][0]['status'], 'rejected')
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            self.assertEqual(cli.main(['tailor_export', self.job['id'], '--format', 'md'] + data), 0)
        self.assertTrue(json.loads(buffer.getvalue())['files']['md']['check']['ok'])


if __name__ == '__main__':
    unittest.main()
