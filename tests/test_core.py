"""Independent adversarial checks for authorization, persistence and HTTP boundaries.

All channels/executors are local test doubles. No application is sent.
"""
import copy
import http.client
import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from hunt.core import DEFAULT_CONFIG, Error, Store, dumps
from hunt.materials import synthetic_candidate
from hunt.server import make_server


FACT_TEXT = synthetic_candidate()['facts'][2]['text']


def job_data(index=1):
    pid = str(7000000000000000000 + index)
    return dict(title='本地工具开发', jd=FACT_TEXT, requirements_text=FACT_TEXT,
                company='安克创新', channel='anker', platform_id=pid,
                location='深圳', salary=None, status='open',
                url='https://career.anker.com.cn/larkJobDetail/?websiteId=6962795203808168199&jobId=' + pid,
                application_url='https://anker-in.jobs.feishu.cn/index/resume/' + pid + '/apply')


class LocalChannel:
    def __init__(self):
        self.rows = {}
        self.detail_calls = 0
    def discover(self, limit=5, keyword=''):
        return [copy.deepcopy(item) for item in list(self.rows.values())[:limit]]
    def detail(self, pid):
        self.detail_calls += 1
        return copy.deepcopy(self.rows[str(pid)])


class LocalExecutor:
    def __init__(self, state='submitted'):
        self.calls = 0
        self.state = state
        self.raise_error = False
        self.result = None
    def execute(self, job, package, approval, is_running):
        self.calls += 1
        if self.raise_error:
            raise RuntimeError('fixture interrupted after outbound intent')
        if self.result is not None:
            return copy.deepcopy(self.result)
        if self.state == 'not_sent':
            return dict(state='not_sent', reason='fixture preflight prevented all outward operations', submit_attempted=False, phase='preflight', evidence=dict(kind='preflight', outbound_started=False))
        return dict(state=self.state, receipt=dict(platform_id=job['platform_id'], kind='application_number',
                    evidence='fixture-only receipt #local-001', time=datetime.now(timezone.utc).isoformat()))


class CoreCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.channel, self.executor = LocalChannel(), LocalExecutor()
        self.store = Store(Path(self.temp.name) / 'app', self.channel, self.executor)
        candidate = synthetic_candidate()
        candidate['synthetic'] = False  # Authorized-profile fixture only inside temp DB; never used with a network executor.
        for fact in candidate['facts']:
            fact['source'] = dict(kind='test_fixture', reference='fixture://authorized-profile/' + fact['id'])
        self.store.action(dict(action='candidate', candidate=candidate))
        self.store.action(dict(action='config', config=dict(targets_confirmed=True, cities=['深圳'], submission_limit=5)))

    def prepared(self, index=1):
        data = job_data(index)
        self.channel.rows[data['platform_id']] = data
        job, _ = self.store.import_job(data)
        return self.store.prepare(job['id'])

    def approve(self, jobs, **changes):
        if isinstance(jobs, dict):
            jobs = [jobs]
        payload = dict(job_ids=[j['id'] for j in jobs], decision='approve', permissions=['input', 'upload', 'submit'],
                       snapshots={j['id']: j['package']['snapshot'] for j in jobs}, acknowledge_gaps=True)
        payload.update(changes)
        self.store.review(payload)

    def saved_job(self, jid):
        with self.store.tx() as connection:
            return self.store.job(connection, jid)

    def mutate_job(self, jid, mutation):
        with self.store.tx() as connection:
            job = self.store.job(connection, jid)
            mutation(job)
            self.store.save(connection, job)

    def assert_no_execution(self, jid):
        with self.assertRaises(Error):
            self.store.execute(jid)
        self.assertEqual(self.executor.calls, 0)


class PersistenceTests(CoreCase):
    def test_concurrent_same_id_import_is_one_job_and_preserves_query(self):
        data = job_data()
        data['url'] += '&business=retained#fragment'
        with ThreadPoolExecutor(max_workers=6) as pool:
            outcomes = list(pool.map(lambda _: self.store.import_job(data), range(12)))
        self.assertEqual(len({result[0]['id'] for result in outcomes}), 1)
        self.assertEqual(sum(not result[1] for result in outcomes), 1)
        jobs = self.store.state()['jobs']
        self.assertEqual(len(jobs), 1)
        self.assertIn('&business=retained', jobs[0]['url'])
        self.assertNotIn('#fragment', jobs[0]['url'])

    def test_same_description_different_id_is_not_merged(self):
        first, _ = self.store.import_job(job_data(1))
        second, duplicate = self.store.import_job(job_data(2))
        self.assertFalse(duplicate)
        self.assertNotEqual(first['id'], second['id'])
        self.assertTrue(second['duplicate_hint'])

    def test_rejected_job_cannot_be_reprepared_or_rerun(self):
        job = self.prepared()
        self.approve(job, decision='reject')
        with self.assertRaises(Error):
            self.store.prepare(job['id'])
        result = self.store.run()
        self.assertEqual(result['prepared'], 0)
        self.assertEqual(self.saved_job(job['id'])['status'], 'rejected')
        self.assert_no_execution(job['id'])

    def test_recovery_sending_to_unknown_never_automatically_resends(self):
        job = self.prepared()
        self.approve(job)
        with self.store.tx() as connection:
            sending = dict(id='crash-fixture', job_id=job['id'], state='sending', group='fixture-group', started_at=datetime.now(timezone.utc).isoformat())
            connection.execute('INSERT INTO attempts VALUES(?,?,?,?)', (sending['id'], job['id'], 'sending', dumps(sending)))
            persisted = self.store.job(connection, job['id'])
            persisted['status'] = 'sending'
            self.store.save(connection, persisted)
        restarted = Store(self.store.root, self.channel, self.executor)
        restarted.recover()
        self.assertEqual(restarted.state()['jobs'][0]['status'], 'unknown')
        self.assertEqual(restarted.state()['jobs'][0]['attempts'][0]['state'], 'unknown')
        with self.assertRaises(Error):
            restarted.execute(job['id'])
        self.assertEqual(self.executor.calls, 0)

    def test_updated_duplicate_invalidates_old_approval_and_prepares_new_revision(self):
        original = self.prepared()
        self.approve(original)
        changed = dict(job_data(), title='本地工具开发新版', jd=FACT_TEXT + '\n新增岗位信息。', requirements_text='新增明确任职要求。', status='closed')
        self.channel.rows[changed['platform_id']] = changed
        refreshed, duplicate = self.store.import_job(changed)
        self.assertTrue(duplicate)
        self.assertEqual(refreshed['id'], original['id'])
        self.assertEqual(refreshed['jd'], changed['jd'])
        self.assertEqual(refreshed['title'], changed['title'])
        self.assertEqual(refreshed['requirements_text'], changed['requirements_text'])
        self.assertEqual(refreshed['availability'], 'closed')
        self.assertNotEqual(refreshed['status'], 'approved')
        self.assertIsNone(refreshed['approval'])
        updated = self.store.prepare(refreshed['id'])
        self.assertNotEqual(updated['package']['snapshot'], original['package']['snapshot'])
        self.assertNotEqual(updated['package']['id'], original['package']['id'])
        self.assertEqual(updated['status'], 'review')
        self.assert_no_execution(updated['id'])

    def test_changed_duplicate_cannot_reset_locked_or_rejected_state(self):
        for index, state in enumerate(['rejected', 'sending', 'unknown', 'submitted'], 1):
            with self.subTest(state=state):
                job = self.prepared(index)
                self.approve(job)
                self.mutate_job(job['id'], lambda current: current.update(status=state))
                previous = self.saved_job(job['id'])
                changed = dict(job_data(index), title='Changed title', jd='Changed job text', requirements_text='Changed requirement', status='closed')
                refreshed, duplicate = self.store.import_job(changed)
                self.assertTrue(duplicate)
                self.assertEqual(refreshed['status'], state)
                self.assertEqual(refreshed['package']['snapshot'], previous['package']['snapshot'])
                self.assertEqual(refreshed['approval'], previous['approval'])
                with self.assertRaises(Error):
                    self.store.prepare(job['id'])
        self.assertEqual(self.executor.calls, 0)

    def test_new_store_object_does_not_recover_a_live_attempt(self):
        job = self.prepared()
        with self.store.tx() as connection:
            connection.execute('INSERT INTO attempts VALUES(?,?,?,?)', ('live', job['id'], 'sending', dumps(dict(id='live', state='sending'))))
        another = Store(self.store.root)
        self.assertEqual(another.state()['jobs'][0]['attempts'][0]['state'], 'sending')


class AuthorizationTests(CoreCase):
    def test_review_requires_the_specific_snapshot(self):
        job = self.prepared()
        with self.assertRaises(Error):
            self.approve(job, snapshots={})
        self.assertEqual(self.saved_job(job['id'])['status'], 'review')

    def test_missing_approval_cannot_execute(self):
        self.assert_no_execution(self.prepared()['id'])

    def test_missing_any_operation_permission_cannot_execute(self):
        job = self.prepared()
        self.approve(job, permissions=['input', 'upload'])
        self.assert_no_execution(job['id'])

    def test_default_submission_budget_is_zero(self):
        self.assertEqual(DEFAULT_CONFIG['submission_limit'], 0)
        self.store.action(dict(action='config', config=dict(targets_confirmed=True, cities=['深圳'])))
        job = self.prepared()
        self.approve(job)
        self.assert_no_execution(job['id'])

    def test_expired_approval_cannot_execute(self):
        job = self.prepared()
        self.approve(job)
        self.mutate_job(job['id'], lambda current: current['approval'].update(expires_at=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()))
        self.assert_no_execution(job['id'])

    def test_pause_and_stop_block_outbound(self):
        job = self.prepared()
        self.approve(job)
        for control in ['paused', 'stopped']:
            self.store.action(dict(action='control', value=control))
            self.assert_no_execution(job['id'])
        self.store.action(dict(action='control', value='running'))
        self.store.execute(job['id'])
        self.assertEqual(self.executor.calls, 1)

    def test_candidate_changes_invalidate_snapshot(self):
        job = self.prepared()
        self.approve(job)
        candidate = self.store.state()['candidate']
        candidate['facts'][2]['text'] += ' 新的待审核版本。'
        self.store.action(dict(action='candidate', candidate=candidate))
        self.assert_no_execution(job['id'])

    def test_disclosure_changes_invalidate_snapshot(self):
        job = self.prepared()
        self.approve(job)
        candidate = self.store.state()['candidate']
        candidate['facts'][2]['disclosure'] = 'private'
        self.store.action(dict(action='candidate', candidate=candidate))
        self.assert_no_execution(job['id'])

    def test_config_changes_invalidate_snapshot(self):
        job = self.prepared()
        self.approve(job)
        self.store.action(dict(action='config', config=dict(targets_confirmed=True, cities=['北京'], submission_limit=5)))
        self.assert_no_execution(job['id'])

    def test_package_field_changes_invalidate_snapshot(self):
        job = self.prepared()
        self.approve(job)
        self.mutate_job(job['id'], lambda current: current['package']['fields']['email'].update(value='other@example.invalid'))
        self.assert_no_execution(job['id'])

    def test_package_file_bytes_changes_invalidate_snapshot(self):
        job = self.prepared()
        self.approve(job)
        path = self.store.root / 'packages' / job['package']['id'] / 'resume.txt'
        path.write_text('Changed candidate facts', encoding='utf-8')
        self.assert_no_execution(job['id'])

    def test_package_file_identity_change_invalidates_snapshot(self):
        job = self.prepared()
        self.approve(job)
        directory = self.store.root / 'packages' / job['package']['id']
        (directory / 'renamed-resume.txt').write_bytes((directory / 'resume.txt').read_bytes())
        self.mutate_job(job['id'], lambda current: current['package']['files'].update(text='renamed-resume.txt'))
        self.assert_no_execution(job['id'])

    def test_job_url_identity_mutation_invalidates_snapshot(self):
        job = self.prepared()
        self.approve(job)
        self.mutate_job(job['id'], lambda current: current.update(url='https://unapproved.example/apply'))
        self.assert_no_execution(job['id'])

    def test_fresh_platform_identity_or_status_change_blocks(self):
        job = self.prepared()
        self.approve(job)
        data = self.channel.rows[job['platform_id']]
        for change in [{'platform_id': '7999999999999999999'}, {'status': 'closed'}, {'title': 'Different role'}, {'jd': 'Different duties'}]:
            self.channel.rows[job['platform_id']] = dict(data, **change)
            self.assert_no_execution(job['id'])

    def test_fresh_material_job_conditions_change_requires_review(self):
        job = self.prepared()
        self.approve(job)
        self.channel.rows[job['platform_id']]['location'] = '北京'
        self.assert_no_execution(job['id'])

    def test_fresh_company_or_recipient_changes_require_review(self):
        job = self.prepared()
        self.approve(job)
        original = copy.deepcopy(self.channel.rows[job['platform_id']])
        for changes in [{'company': '不同公司'}, {'url': 'https://unapproved.example/job'}, {'application_url': 'https://unapproved.example/apply'}, {'requirements_text': '新增必需技能'}, {'questions': [{'text': '背景调查同意', 'required': True}]}]:
            self.channel.rows[job['platform_id']] = dict(original, **changes)
            self.assert_no_execution(job['id'])

    def test_valid_short_approval_is_usable_and_outside_range_is_rejected(self):
        job = self.prepared()
        for hours in [0, -1, 73, float('nan'), float('inf')]:
            with self.assertRaises((Error, ValueError)):
                self.approve(job, expires_hours=hours)
        self.approve(job, expires_hours=0.01)
        self.store.execute(job['id'])
        self.assertEqual(self.executor.calls, 1)

    def test_material_change_during_execution_stops_next_outbound_action(self):
        job = self.prepared()
        self.approve(job)
        observed = []
        def execution(current_job, package, approval, can_continue):
            candidate = self.store.state()['candidate']
            candidate['facts'][2]['disclosure'] = 'private'
            self.store.action(dict(action='candidate', candidate=candidate))
            observed.append(can_continue())
            return dict(state='not_sent', submit_attempted=False, phase='preflight', reason='fixture stopped before any outward operation')
        self.executor.execute = execution
        self.store.execute(job['id'])
        self.assertEqual(observed, [False])

    def test_approval_expiring_during_execution_stops_next_outbound_action(self):
        job = self.prepared()
        self.approve(job)
        observed = []
        def execution(current_job, package, approval, can_continue):
            self.mutate_job(job['id'], lambda current: current['approval'].update(expires_at=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()))
            observed.append(can_continue())
            return dict(state='not_sent', submit_attempted=False, phase='preflight', reason='fixture expiry before outward operation')
        self.executor.execute = execution
        self.store.execute(job['id'])
        self.assertEqual(observed, [False])

    def test_group_quota_prevents_second_job(self):
        one, two = self.prepared(1), self.prepared(2)
        self.approve([one, two], limit=1)
        self.store.execute(one['id'])
        with self.assertRaises(Error):
            self.store.execute(two['id'])
        self.assertEqual(self.executor.calls, 1)

    def test_concurrent_execute_only_one_outbound_attempt(self):
        job = self.prepared()
        self.approve(job)
        def execute(_):
            try:
                return self.store.execute(job['id'])
            except Error:
                return None
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(execute, range(4)))
        self.assertEqual(self.executor.calls, 1)
        self.assertEqual(len(self.store.state()['jobs'][0]['attempts']), 1)


class ReceiptTests(CoreCase):
    def test_success_requires_corresponding_receipt_then_no_repeat(self):
        job = self.prepared()
        self.approve(job)
        self.store.execute(job['id'])
        self.assertEqual(self.saved_job(job['id'])['status'], 'submitted')
        with self.assertRaises(Error):
            self.store.execute(job['id'])
        self.assertEqual(self.executor.calls, 1)

    def test_executor_exception_becomes_unknown(self):
        job = self.prepared()
        self.approve(job)
        self.executor.raise_error = True
        self.store.execute(job['id'])
        self.assertEqual(self.saved_job(job['id'])['status'], 'unknown')
        with self.assertRaises(Error):
            self.store.execute(job['id'])
        self.assertEqual(self.executor.calls, 1)

    def test_bad_receipt_persisted_and_returned_as_unknown(self):
        job = self.prepared()
        self.approve(job)
        self.executor.result = dict(state='submitted', receipt=dict(platform_id='wrong-job', evidence='HTTP 200', time=datetime.now(timezone.utc).isoformat(), kind='application_number'))
        result = self.store.execute(job['id'])
        self.assertEqual(self.saved_job(job['id'])['status'], 'unknown')
        self.assertEqual(result['state'], 'unknown')

    def test_receipt_predating_current_intent_cannot_prove_new_application(self):
        job = self.prepared()
        self.approve(job)
        self.executor.result = dict(state='submitted', receipt=dict(platform_id=job['platform_id'], kind='application_number',
            evidence='fixture stale receipt reused from previous event', time=(datetime.now(timezone.utc)-timedelta(days=1)).isoformat()))
        result = self.store.execute(job['id'])
        self.assertEqual(result['state'], 'unknown')
        self.assertEqual(self.saved_job(job['id'])['status'], 'unknown')

    def test_malformed_receipt_time_becomes_unknown(self):
        job = self.prepared()
        self.approve(job)
        self.executor.result = dict(state='submitted', receipt=dict(platform_id=job['platform_id'], kind='application_number', evidence='fixture evidence', time='not-a-time'))
        self.assertEqual(self.store.execute(job['id'])['state'], 'unknown')
        self.assertEqual(self.saved_job(job['id'])['status'], 'unknown')

    def test_proven_preflight_not_sent_is_retryable(self):
        job = self.prepared()
        self.approve(job)
        self.executor.state = 'not_sent'
        self.store.execute(job['id'])
        self.assertEqual(self.saved_job(job['id'])['status'], 'approved')
        self.executor.state = 'submitted'
        self.store.execute(job['id'])
        self.assertEqual(self.executor.calls, 2)
        self.assertEqual(self.saved_job(job['id'])['status'], 'submitted')

    def test_malformed_executor_response_becomes_unknown_without_restart(self):
        job = self.prepared()
        self.approve(job)
        self.executor.execute = lambda *args: None
        result = self.store.execute(job['id'])
        self.assertEqual(result['state'], 'unknown')
        self.assertEqual(self.saved_job(job['id'])['status'], 'unknown')

    def test_bare_not_sent_assertion_cannot_unlock_a_retry(self):
        job = self.prepared()
        self.approve(job)
        self.executor.result = dict(state='not_sent', reason='No proof')
        self.store.execute(job['id'])
        self.assertEqual(self.saved_job(job['id'])['status'], 'unknown')
        with self.assertRaises(Error):
            self.store.execute(job['id'])
        self.assertEqual(self.executor.calls, 1)


class HttpTests(CoreCase):
    def setUp(self):
        super().setUp()
        self.server = make_server(self.store, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.port = self.server.server_port
        status, body = self.request('GET', '/api/state')
        self.assertEqual(status, 200)
        self.token = json.loads(body)['csrf_token']

    def request(self, method, path, data=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        try:
            body = None if data is None else json.dumps(data).encode()
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def test_host_and_origin_guard_state_and_actions(self):
        self.assertEqual(self.request('GET', '/api/state', headers={'Host': 'attacker.invalid'})[0], 403)
        self.assertEqual(self.request('GET', '/api/state', headers={'Origin': 'https://attacker.invalid'})[0], 403)
        headers = {'X-Local-Token': self.token, 'Content-Type': 'application/json', 'Origin': 'https://attacker.invalid'}
        self.assertEqual(self.request('POST', '/api/action', {'action': 'control', 'value': 'stopped'}, headers)[0], 403)
        self.assertTrue(self.store.is_running())

    def test_csrf_required_and_content_type_checked(self):
        body = {'action': 'control', 'value': 'paused'}
        self.assertEqual(self.request('POST', '/api/action', body, {'Content-Type': 'application/json'})[0], 403)
        self.assertEqual(self.request('POST', '/api/action', body, {'X-Local-Token': self.token})[0], 415)
        headers = {'X-Local-Token': self.token, 'Content-Type': 'application/json'}
        self.assertEqual(self.request('POST', '/api/action', body, headers)[0], 200)
        self.assertFalse(self.store.is_running())

    def test_export_route_and_traversal(self):
        job = self.prepared()
        prefix = '/api/file/' + job['package']['id'] + '/'
        self.assertEqual(self.request('GET', prefix + 'resume.pdf')[0], 200)
        for path in ['/../../state.sqlite3', '/api/file/../state.sqlite3', prefix + '../state.sqlite3', prefix + '%2e%2e%2fstate.sqlite3', '/api/file/not-a-package/resume.pdf']:
            self.assertEqual(self.request('GET', path)[0], 404, path)

    def test_http_cannot_manually_assert_application_success(self):
        job = self.prepared()
        headers = {'X-Local-Token': self.token, 'Content-Type': 'application/json'}
        status, _ = self.request('POST', '/api/action', {'action': 'event', 'kind': 'submitted', 'job_id': job['id'], 'evidence': 'trust me'}, headers)
        self.assertEqual(status, 400)
        self.assertEqual(self.saved_job(job['id'])['status'], 'review')


if __name__ == '__main__':
    unittest.main()
