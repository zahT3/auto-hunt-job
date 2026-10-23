"""Real local HTTP upload/confirmation and search-state integration checks."""
import base64
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from hunt.core import Store, Error
from hunt.materials import accepted_facts, match
from hunt.server import make_server


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'app')
        self.server = make_server(self.store, 0)
        self.port = self.server.server_port
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        _, state = self.request('GET', '/api/state')
        self.token = state['csrf_token']

    def request(self, method, path, payload=None, token=None, origin=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        headers = {'Content-Type': 'application/json'}
        if token is not None:
            headers['X-Local-Token'] = token
        if origin:
            headers['Origin'] = origin
        connection.request(method, path, None if payload is None else json.dumps(payload), headers)
        response = connection.getresponse()
        result = response.status, json.loads(response.read())
        connection.close()
        return result

    def upload(self, text='姓名：合成示例\n工作经验：3年\n使用 Python 和 RAG 完成本地原型。\n使用 Solidity 完成测试网练习。'):
        return self.request('POST', '/api/resume', dict(filename='synthetic.txt', synthetic=True,
                            content_base64=base64.b64encode(text.encode()).decode()), token=self.token)

    def test_upload_confirmation_is_private_and_only_selected_facts_in_profile(self):
        code, state = self.upload()
        self.assertEqual(code, 200)
        draft = state['candidate_draft']
        self.assertTrue(all(f['status'] == 'unconfirmed' for f in draft['candidate']['facts']))
        self.assertFalse(accepted_facts(draft['candidate']))
        ids = [f['id'] for f in draft['candidate']['facts'] if 'Python' in f['text']]
        code, state = self.request('POST', '/api/action', dict(action='resume_confirm', draft_id=draft['id'], confirmed_fact_ids=ids), token=self.token)
        self.assertEqual(code, 200)
        self.assertTrue(state['candidate']['synthetic'])
        self.assertIsNone(state['candidate_draft'])
        self.assertFalse(accepted_facts(state['candidate']))
        self.assertEqual(state['config']['submission_limit'], 0)
        skills = [s['name'] for s in state['candidate_profile']['skills']]
        self.assertIn('Python', skills)
        self.assertNotIn('Solidity', skills)
        self.assertIsNone(state['candidate_profile']['years_experience'])
        matching = match(state['candidate'], dict(jd='熟悉 Python 开发', location='深圳'))
        self.assertTrue(matching['requirements'][0]['fact_ids'])

    def test_stale_upload_confirmation_and_foreign_fact_are_rejected(self):
        _, first = self.upload()
        _, second = self.upload('Python 工具原型。')
        code, _ = self.request('POST', '/api/action', dict(action='resume_confirm', draft_id=first['candidate_draft']['id'], confirmed_fact_ids=[first['candidate_draft']['candidate']['facts'][0]['id']]), token=self.token)
        self.assertEqual(code, 400)
        code, _ = self.request('POST', '/api/action', dict(action='resume_confirm', draft_id=second['candidate_draft']['id'], confirmed_fact_ids=['invented']), token=self.token)
        self.assertEqual(code, 400)

    def test_upload_requires_session_and_rejects_cross_origin(self):
        payload = dict(filename='x.txt', content_base64='eA==')
        self.assertEqual(self.request('POST', '/api/resume', payload)[0], 403)
        self.assertEqual(self.request('POST', '/api/resume', payload, self.token, 'https://example.com')[0], 403)
        self.assertIsNone(self.store.state()['candidate_draft'])

    def test_bad_file_does_not_replace_previous_draft(self):
        _, previous = self.upload()
        code, _ = self.request('POST', '/api/resume', dict(filename='broken.pdf', content_base64=base64.b64encode(b'not a pdf').decode()), self.token)
        self.assertEqual(code, 400)
        self.assertEqual(self.store.state()['candidate_draft']['id'], previous['candidate_draft']['id'])

    def test_background_run_returns_and_rejects_concurrent_start(self):
        entered, release = threading.Event(), threading.Event()
        class Channel:
            def discover(self, **kwargs):
                entered.set()
                release.wait(5)
                return []
        self.store.channel = Channel()
        self.addCleanup(release.set)
        code, state = self.request('POST', '/api/action', {'action': 'run'}, self.token)
        self.assertEqual(code, 200)
        self.assertTrue(entered.wait(2))
        self.assertTrue(state['search_running'])
        self.assertEqual(self.request('POST', '/api/action', {'action': 'run'}, self.token)[0], 400)
        release.set()
        self.store.search_thread.join(5)
        self.assertFalse(self.store.state()['search_running'])
        self.assertEqual(self.store.state()['runs'][0]['status'], 'empty')

    def test_restart_marks_incomplete_run_interrupted(self):
        with self.store.tx() as c:
            c.execute('INSERT INTO runs VALUES(?,?)', ('interrupted-test', json.dumps(dict(id='interrupted-test',status='running'))))
        self.store.recover()
        self.assertEqual(self.store.state()['runs'][0]['status'], 'interrupted')

    def test_search_budget_does_not_increase_submission_budget(self):
        self.store.action(dict(action='config', config=dict(max_jobs=50, max_pages=5)))
        self.assertEqual(self.store.state()['config']['submission_limit'], 0)
        with self.assertRaises(Error):
            self.store.action(dict(action='config', config=dict(max_jobs=51)))

    def test_synthetic_provenance_cannot_be_cleared_by_top_level_toggle(self):
        candidate = self.store.state()['candidate']
        candidate['synthetic'] = False
        state = self.store.action(dict(action='candidate', candidate=candidate))
        self.assertTrue(state['candidate']['synthetic'])
        _, uploaded = self.upload()
        draft = uploaded['candidate_draft']
        self.store.confirm_resume(dict(draft_id=draft['id'],confirmed_fact_ids=[f['id'] for f in draft['candidate']['facts']]))
        candidate = self.store.state()['candidate']
        candidate['synthetic'] = False
        self.assertTrue(self.store.action(dict(action='candidate', candidate=candidate))['candidate']['synthetic'])

    def test_stop_is_forwarded_to_discovery_and_never_reported_as_empty(self):
        seen = {}
        def scan(config, **kwargs):
            seen.update(kwargs)
            self.store.action(dict(action='control',value='stopped'))
            self.assertFalse(kwargs['should_continue']())
            return dict(jobs=[],sources=[dict(source_id='boss',status='cancelled')],queries=['AI'])
        with patch('hunt.discovery.discover', side_effect=scan):
            result = self.store.run()
        self.assertEqual(result['status'],'stopped')
        self.assertEqual(seen['browser_profile_root'],self.store.root/'browser-search')

    def test_confirming_new_resume_removes_old_recommendation(self):
        job,_=self.store.import_job(dict(title='Python',jd='Python development'))
        self.store.prepare(job['id'])
        self.assertTrue(self.store.state()['jobs'][0]['recommendation']['skill_matches'])
        _, uploaded = self.upload('使用 Solidity 完成测试网原型。')
        draft=uploaded['candidate_draft']
        self.store.confirm_resume(dict(draft_id=draft['id'],confirmed_fact_ids=[f['id'] for f in draft['candidate']['facts']]))
        job=self.store.state()['jobs'][0]
        self.assertIsNone(job['recommendation'])
        self.assertIsNone(job['match'])
        self.assertIsNone(job['approval'])


if __name__ == '__main__':
    unittest.main()
