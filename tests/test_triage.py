import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from hunt.app import store as core
from hunt.app.store import Store
from hunt.base import Error
from hunt.workbench.materials import synthetic_candidate
from tests.test_core import job_data


class TriageTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'app')
        self.addCleanup(self.store.prepare_pool.shutdown)
        candidate = synthetic_candidate()
        candidate['synthetic'] = False
        for fact in candidate['facts']:
            fact['source'] = dict(kind='test_fixture', reference='fixture://authorized-profile/' + fact['id'])
        self.store.action(dict(action='candidate', candidate=candidate))
        self.jid = self.add(1)

    def add(self, index, **extra):
        data = dict(job_data(index), **extra)
        return self.store.import_job(data)[0]['id']

    def job(self, state, jid=None):
        return next(j for j in state['jobs'] if j['id'] == (jid or self.jid))

    def triage(self, value, jid=None):
        return self.store.action(dict(action='triage', job_id=jid or self.jid, value=value))

    def set_job(self, **changes):
        with self.store.tx() as c:
            j = self.store.job(c, self.jid)
            j.update(changes)
            self.store.save(c, j)

    def test_skip_moves_job_out_of_pending(self):
        self.triage('skipped')
        s = self.store.state()
        self.assertEqual(self.job(s)['bucket'], 'skipped')
        self.assertEqual(s['counts']['pending'], 0)
        self.assertEqual(s['counts']['skipped'], 1)

    def test_later_goes_to_end_of_pending(self):
        second = self.add(2)
        first = next(j['id'] for j in self.store.state()['jobs'] if j['bucket'] == 'pending')
        s = self.triage('later', first)
        pending = [j['id'] for j in s['jobs'] if j['bucket'] == 'pending']
        self.assertEqual(len(pending), 2)
        self.assertEqual(pending[-1], first)
        self.assertIn(second, pending)

    def test_interested_prepares_in_background(self):
        self.triage('interested')
        self.store.prepare_pool.shutdown(wait=True)
        j = self.job(self.store.state())
        self.assertEqual(j['bucket'], 'materials')
        self.assertIsNone(j['prepare_error'])

    def test_prepare_failure_is_recorded_and_job_stays_chosen(self):
        with mock.patch.object(Store, 'prepare', side_effect=Error('岗位原文为空')):
            self.triage('interested')
            self.store.prepare_pool.shutdown(wait=True)
        j = self.job(self.store.state())
        self.assertEqual(j['bucket'], 'chosen')
        self.assertEqual(j['prepare_error'], '岗位原文为空')

    def test_undo_interested_discards_prepared_package(self):
        self.triage('interested')
        self.store.prepare_pool.shutdown(wait=True)
        self.assertIsNotNone(self.job(self.store.state())['package'])
        j = self.job(self.triage(None))
        self.assertEqual(j['bucket'], 'pending')
        self.assertIsNone(j['package'])
        self.assertEqual(j['status'], 'new')

    def test_undo_refused_after_approval(self):
        self.triage('interested')
        self.store.prepare_pool.shutdown(wait=True)
        self.set_job(status='approved')
        with self.assertRaises(Error):
            self.triage(None)
        self.assertIsNotNone(self.job(self.store.state())['package'])

    def test_undo_while_prepare_is_running_leaves_no_package(self):
        real = Store.prepare
        def prepare_then_undo(store, jid):
            j = real(store, jid)
            store.triage(jid, None)  # the user undoes the choice while prepare is still running
            return j
        with mock.patch.object(Store, 'prepare', prepare_then_undo):
            self.triage('interested')
            self.store.prepare_pool.shutdown(wait=True)
        j = self.job(self.store.state())
        self.assertEqual(j['bucket'], 'pending')
        self.assertIsNone(j['package'])

    def test_locked_or_rejected_job_cannot_be_triaged(self):
        for status in ('unknown', 'submitted', 'rejected'):
            self.set_job(status=status)
            with self.assertRaises(Error):
                self.triage('skipped')

    def test_invalid_value_is_rejected(self):
        with self.assertRaises(Error):
            self.triage('maybe')

    def test_candidate_update_keeps_triage(self):
        self.triage('skipped')
        candidate = self.store.state()['candidate']
        self.store.action(dict(action='candidate', candidate=candidate))
        j = self.job(self.store.state())
        self.assertEqual(j['status'], 'new')
        self.assertEqual(j['triage'], 'skipped')
        self.assertEqual(j['bucket'], 'skipped')

    def test_counts_new_today_uses_local_date(self):
        self.add(2, collected_at=(datetime.now(timezone.utc) - timedelta(days=2)).isoformat())
        self.assertEqual(self.store.state()['counts']['new_today'], 1)

    def test_state_fills_missing_recommendation_once(self):
        self.set_job(recommendation=None)
        import hunt.profile.profile as profile
        real = profile.recommend
        with mock.patch.object(profile, 'recommend', side_effect=real) as spy:
            first = self.job(self.store.state())
            self.job(self.store.state())
        self.assertIn('priority', first['recommendation'])
        self.assertEqual(spy.call_count, 1)

    def test_state_returns_orientation(self):
        self.assertIn('orientation', self.store.state())


if __name__ == '__main__':
    unittest.main()
