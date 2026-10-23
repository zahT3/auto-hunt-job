"""Local material review records never grant outward application authority."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hunt.core import Error, Store, dumps


class MaterialReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'app')

    def prepare(self, number=1, jd='使用 Python 开发本地工具。熟悉 Kubernetes。'):
        job, _ = self.store.import_job(dict(title='合成岗位 ' + str(number), jd=jd, company='示例公司',
                                           channel='website', platform_id='synthetic:' + str(number),
                                           url='https://careers.example/jobs/' + str(number)))
        return self.store.prepare(job['id'])

    def payload(self, *jobs):
        return dict(action='review_materials', job_ids=[j['id'] for j in jobs],
                    snapshots={j['id']: j['package']['snapshot'] for j in jobs}, acknowledge_review=True)

    def saved(self, jid):
        with self.store.tx() as c:
            return self.store.job(c, jid)

    def shown(self, jid):
        return next(j for j in self.store.state()['jobs'] if j['id'] == jid)

    def mutate(self, jid, callback):
        with self.store.tx() as c:
            job = self.store.job(c, jid)
            callback(job)
            self.store.save(c, job)

    def test_review_records_current_version_but_never_grants_authority(self):
        job = self.prepare()
        before = self.store.state()
        payload = self.payload(job)
        # Extra authorization-shaped fields cannot turn this into an approval.
        payload.update(permissions=['input', 'upload', 'submit'], decision='approve', disclosure='application')
        state = self.store.action(payload)
        reviewed = state['jobs'][0]
        self.assertTrue(reviewed['material_review_current'])
        self.assertEqual(reviewed['material_review']['snapshot'], job['package']['snapshot'])
        self.assertEqual(reviewed['material_review']['scope'], 'local_materials')
        self.assertEqual(reviewed['material_review']['meaning'], 'viewed')
        self.assertTrue(reviewed['material_review']['reviewed_at'])
        self.assertEqual(reviewed['status'], job['status'])
        self.assertEqual(reviewed['approval'], job['approval'])
        self.assertEqual(reviewed['attempts'], [])
        self.assertEqual(state['candidate'], before['candidate'])
        self.assertEqual(state['config'], before['config'])
        event = reviewed['events'][-1]
        self.assertEqual(event['kind'], 'materials_reviewed')
        self.assertEqual(event['evidence']['snapshot'], job['package']['snapshot'])

    def test_gaps_are_preserved_and_only_the_material_review_task_is_removed(self):
        job = self.prepare()
        self.assertTrue(job['package']['gaps'])
        self.assertFalse(job['package']['blockers'])
        before = self.store.state()
        self.assertTrue(any(t.get('job_id') == job['id'] for t in before['tasks']))
        state = self.store.action(self.payload(job))
        self.assertEqual(state['jobs'][0]['package']['gaps'], job['package']['gaps'])
        self.assertFalse(any(t.get('job_id') == job['id'] for t in state['tasks']))
        self.assertEqual([t for t in state['tasks'] if not t.get('job_id')], [t for t in before['tasks'] if not t.get('job_id')])

    def test_batch_validation_is_atomic_when_second_snapshot_is_stale(self):
        one, two = self.prepare(1), self.prepare(2)
        payload = self.payload(one, two)
        payload['snapshots'][two['id']] = 'stale'
        with self.assertRaises(Error):
            self.store.action(payload)
        for job in (one, two):
            current = self.saved(job['id'])
            self.assertNotIn('material_review', current)
            self.assertFalse(any(e['kind'] == 'materials_reviewed' for e in current['events']))

    def test_batch_write_rolls_back_if_any_record_cannot_be_saved(self):
        one, two = self.prepare(1), self.prepare(2)
        save = self.store.save
        def fail_second(c, job):
            if job['id'] == two['id']:
                raise Error('fixture save failure')
            save(c, job)
        with patch.object(self.store, 'save', side_effect=fail_second), self.assertRaises(Error):
            self.store.action(self.payload(one, two))
        self.assertNotIn('material_review', self.saved(one['id']))
        self.assertNotIn('material_review', self.saved(two['id']))

    def test_acknowledgement_and_exact_snapshot_are_required(self):
        job = self.prepare()
        invalid = [dict(acknowledge_review=False), dict(acknowledge_review='true'),
                   dict(snapshots={}), dict(snapshots=None), dict(job_ids=[job['id'], job['id']]),
                   dict(job_ids=[]), dict(job_ids='all')]
        for change in invalid:
            with self.subTest(change=change), self.assertRaises(Error):
                self.store.action(dict(self.payload(job), **change))
        self.assertNotIn('material_review', self.saved(job['id']))

    def test_unprepared_job_cannot_be_marked_reviewed(self):
        job, _ = self.store.import_job(dict(title='合成岗位', jd='Python tools', url='https://careers.example/new'))
        with self.assertRaises(Error):
            self.store.action(dict(action='review_materials', job_ids=[job['id']], snapshots={job['id']: 'invented'}, acknowledge_review=True))

    def test_file_changes_invalidate_review_and_old_snapshot_cannot_be_reused(self):
        job = self.prepare(); payload = self.payload(job)
        self.store.action(payload)
        file = self.store.root / 'packages' / job['package']['id'] / job['package']['files']['text']
        file.write_text('改变后的材料', encoding='utf-8')
        self.assertFalse(self.shown(job['id'])['material_review_current'])
        with self.assertRaises(Error):
            self.store.action(payload)
        self.assertTrue(any(t.get('job_id') == job['id'] for t in self.store.state()['tasks']))

    def test_missing_file_and_changed_package_content_invalidate_review(self):
        for change in ('missing_file', 'package_text'):
            with self.subTest(change=change):
                job = self.prepare(1 if change == 'missing_file' else 2)
                self.store.action(self.payload(job))
                def mutate(current):
                    if change == 'missing_file':
                        current['package']['files']['pdf'] = 'absent.pdf'
                    else:
                        current['package']['resume'] += '\n新增未复核文字'
                self.mutate(job['id'], mutate)
                self.assertFalse(self.shown(job['id'])['material_review_current'])
                with self.assertRaises(Error):
                    self.store.action(self.payload(job))

    def test_candidate_config_and_job_changes_invalidate_review(self):
        for index, change in enumerate(('candidate', 'config', 'job'), 1):
            with self.subTest(change=change):
                job = self.prepare(index); payload = self.payload(job)
                self.store.action(payload)
                if change == 'candidate':
                    candidate = self.store.state()['candidate']
                    candidate['facts'][0]['text'] += '新资料'
                    self.store.action(dict(action='candidate', candidate=candidate))
                elif change == 'config':
                    cfg = self.store.state()['config']; cfg['cities'] = ['上海']
                    self.store.action(dict(action='config', config=cfg))
                else:
                    self.mutate(job['id'], lambda j: j.update(jd=j['jd'] + '\n新要求'))
                self.assertFalse(self.shown(job['id'])['material_review_current'])
                with self.assertRaises(Error):
                    self.store.action(payload)

    def test_new_material_version_needs_new_review_and_keeps_history(self):
        job = self.prepare(); first = self.payload(job)
        self.store.action(first)
        refreshed = self.store.prepare(job['id'])
        self.assertFalse(self.shown(job['id'])['material_review_current'])
        with self.assertRaises(Error):
            self.store.action(first)
        self.store.action(self.payload(refreshed))
        shown = self.shown(job['id'])
        self.assertTrue(shown['material_review_current'])
        events = [e for e in shown['events'] if e['kind'] == 'materials_reviewed']
        self.assertEqual(len(events), 2)
        self.assertNotEqual(events[0]['evidence']['snapshot'], events[1]['evidence']['snapshot'])

    def test_unknown_application_state_and_existing_approval_are_untouched(self):
        job = self.prepare()
        approval = dict(snapshot=job['package']['snapshot'], permissions=['input'], decision='approve')
        self.mutate(job['id'], lambda j: j.update(status='unknown', approval=copy.deepcopy(approval), next_action='查证站点申请记录'))
        with self.store.tx() as c:
            c.execute('INSERT INTO attempts VALUES(?,?,?,?)', ('fixture', job['id'], 'unknown', dumps(dict(state='unknown', id='fixture'))))
        state = self.store.action(self.payload(job)); shown = state['jobs'][0]
        self.assertEqual(shown['status'], 'unknown')
        self.assertEqual(shown['approval'], approval)
        self.assertEqual(shown['attempts'], [dict(state='unknown', id='fixture')])
        self.assertTrue(any(t.get('job_id') == job['id'] and t['reason'] == '查证站点申请记录' for t in state['tasks']))

    def test_mandatory_fact_blockers_and_hard_failures_remain_tasks_after_viewing(self):
        for index, kind in enumerate(('blocker', 'hard'), 1):
            with self.subTest(kind=kind):
                job = self.prepare(index)
                with self.store.tx() as c:
                    current = self.store.job(c, job['id'])
                    if kind == 'blocker':
                        current['package']['blockers'].append(dict(text='缺少必填事实'))
                    else:
                        current['match']['hard'].append(dict(status='not_met', text='不符合工作许可要求'))
                    current['package']['snapshot'] = self.store.snapshot(self.store.meta(c, 'candidate'), self.store.meta(c, 'config'), current, current['package'])
                    self.store.save(c, current)
                state = self.store.action(self.payload(current))
                self.assertTrue(self.shown(job['id'])['material_review_current'])
                task = next(t for t in state['tasks'] if t.get('job_id') == job['id'])
                self.assertIn('必填事实' if kind == 'blocker' else '硬条件', task['reason'])

    def test_duplicate_review_is_idempotent_and_does_not_duplicate_events(self):
        job = self.prepare(); payload = self.payload(job)
        self.store.action(payload)
        first = self.saved(job['id'])['material_review']
        self.store.action(payload)
        current = self.saved(job['id'])
        self.assertEqual(current['material_review'], first)
        self.assertEqual(len([e for e in current['events'] if e['kind'] == 'materials_reviewed']), 1)

    def test_demo_dataset_forces_fixture_run_but_normal_synthetic_data_keeps_read_search(self):
        demo = Store(Path(self.temp.name) / 'demo')
        for store, fixture in ((demo, True), (self.store, False)):
            self.assertTrue(store.state()['candidate']['synthetic'])
            with patch.object(store, 'start_run') as run:
                store.action(dict(action='run'))
            run.assert_called_once_with(demo=fixture)


if __name__ == '__main__':
    unittest.main()
