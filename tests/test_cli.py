import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import zipfile

from hunt.__main__ import main
from hunt.core import Store, dumps


class CLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / 'data'
        self.resume = self.root / 'candidate.docx'
        xml = ('<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
               '<w:p><w:r><w:t>Built a Python Agent prototype with local tests.</w:t></w:r></w:p>'
               '<w:p><w:r><w:t>Used SQL to inspect 120 synthetic records.</w:t></w:r></w:p>'
               '</w:body></w:document>')
        with zipfile.ZipFile(self.resume, 'w') as archive:
            archive.writestr('word/document.xml', xml)

    def invoke(self, arguments):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(arguments)
        return code, out.getvalue(), err.getvalue()

    def json(self, arguments):
        code, output, error = self.invoke(arguments + ['--json'])
        return code, json.loads(output), error

    def upload(self, real=False):
        code, result, _ = self.json(['resume', str(self.resume), '--data', str(self.data)] + (['--real'] if real else []))
        self.assertEqual(code, 0)
        return result

    def test_resume_defaults_to_synthetic_and_leaves_every_fact_unconfirmed(self):
        result = self.upload()
        self.assertTrue(result['synthetic'])
        self.assertEqual(len(result['facts']), 2)
        self.assertTrue(all(f['status'] == 'unconfirmed' for f in result['facts']))
        state = Store(self.data).state()
        self.assertEqual(state['candidate_draft']['id'], result['draft_id'])
        saved = self.data / 'resumes' / result['draft_id'] / 'original.docx'
        self.assertEqual(saved.read_bytes(), self.resume.read_bytes())
        self.assertFalse(state['jobs'])

    def test_real_flag_only_marks_local_draft_and_does_not_confirm_it(self):
        result = self.upload(real=True)
        self.assertFalse(result['synthetic'])
        self.assertTrue(all(f['status'] == 'unconfirmed' for f in result['facts']))
        self.assertTrue(Store(self.data).state()['candidate']['synthetic'])

    def test_confirm_cannot_default_to_all_facts(self):
        result = self.upload()
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as failure:
            main(['confirm', '--data', str(self.data), '--draft', result['draft_id']])
        self.assertEqual(failure.exception.code, 2)
        state = Store(self.data).state()
        self.assertEqual(state['candidate_draft']['id'], result['draft_id'])
        self.assertTrue(all(f['status'] == 'unconfirmed' for f in state['candidate_draft']['candidate']['facts']))

    def test_confirm_changes_only_explicit_facts_and_keeps_disclosure_private(self):
        result = self.upload(); selected = result['facts'][0]['id']
        code, response, _ = self.json(['confirm', '--data', str(self.data), '--draft', result['draft_id'], '--fact', selected])
        self.assertEqual(code, 0)
        self.assertEqual(response['confirmed_fact_ids'], [selected])
        state = Store(self.data).state()
        self.assertIsNone(state['candidate_draft'])
        for fact in state['candidate']['facts']:
            self.assertEqual(fact['status'], 'confirmed' if fact['id'] == selected else 'unconfirmed')
            self.assertEqual(fact['disclosure'], 'private')
        self.assertTrue(state['candidate']['synthetic'])

    def test_stale_draft_and_unknown_facts_return_errors_without_promoting_claims(self):
        result = self.upload()
        for draft_id, fact_id in [('stale', result['facts'][0]['id']), (result['draft_id'], 'unknown')]:
            code, response, _ = self.json(['confirm', '--data', str(self.data), '--draft', draft_id, '--fact', fact_id])
            self.assertEqual(code, 1)
            self.assertIn('error', response)
            self.assertEqual(Store(self.data).state()['candidate_draft']['id'], result['draft_id'])

    def test_configure_preserves_other_preferences_and_existing_target_confirmation(self):
        store = Store(self.data)
        cfg = store.state()['config']
        cfg.update(cities=['上海'], salary_min=25000, max_jobs=7, targets_confirmed=True,
                   submission_limit=3, keywords=['old'], discovery_sources=[dict(kind='boss')])
        store.action(dict(action='config', config=cfg))
        code, result, _ = self.json(['configure', '--data', str(self.data), '--catalog', 'minimax', '--catalog', 'imtoken',
                                    '--keyword', 'Agent', '--keyword', 'AI', '--official-browser'])
        self.assertEqual(code, 0)
        saved = result['config']
        self.assertEqual(saved['sources'], ['website'])
        self.assertTrue(saved['official_only'])
        self.assertTrue(saved['official_browser'])
        self.assertTrue(saved['targets_confirmed'])
        self.assertEqual(saved['cities'], ['上海'])
        self.assertEqual(saved['salary_min'], 25000)
        self.assertEqual(saved['max_jobs'], 7)
        self.assertEqual(saved['submission_limit'], 0)
        self.assertEqual(saved['keywords'], ['Agent', 'AI'])
        self.assertEqual(len(saved['company_boards']), 2)
        self.assertNotIn('discovery_sources', saved)

    def test_configure_does_not_confirm_development_targets_or_reset_browser_preference(self):
        self.json(['configure', '--data', str(self.data), '--catalog', 'minimax', '--official-browser'])
        code, result, _ = self.json(['configure', '--data', str(self.data), '--keyword', 'Agent'])
        self.assertEqual(code, 0)
        self.assertFalse(result['config']['targets_confirmed'])
        self.assertTrue(result['config']['official_browser'])
        self.assertEqual(result['config']['company_boards'][0]['company'], 'MiniMax')

    def test_status_returns_verification_ids_without_recovering_inflight_attempts(self):
        store = Store(self.data)
        job, _ = store.import_job(dict(title='Agent Engineer', jd='Build agents', url='https://careers.example/job/1'))
        with store.tx() as c:
            store.save(c, dict(job, status='sending'))
            c.execute('INSERT INTO attempts VALUES(?,?,?,?)', ('attempt-one', job['id'], 'sending', dumps(dict(state='sending'))))
        with patch.object(Store, 'recover', side_effect=AssertionError('CLI must not call recovery')):
            code, result, _ = self.json(['status', '--data', str(self.data)])
        self.assertEqual(code, 0)
        self.assertEqual(result['attempts_count'], 1)
        self.assertEqual(result['jobs'][0]['id'], job['id'])
        self.assertEqual(result['jobs'][0]['status'], 'sending')
        self.assertTrue(result['synthetic'])
        self.assertEqual(Store(self.data).state()['jobs'][0]['attempts'][0]['state'], 'sending')

    def test_existing_entrypoints_receive_arguments_and_runner_keeps_its_lock(self):
        original = sys.argv
        for command, module in [('web', 'run'), ('scan', 'hunt.app.scan'), ('verify', 'hunt.app.verify'), ('prepare', 'run')]:
            observed = []
            fake = types.SimpleNamespace(main=lambda: observed.append(list(sys.argv)))
            with patch('hunt.__main__.importlib.import_module', return_value=fake) as load:
                self.assertEqual(main([command, '--data', str(self.data)]), 0)
            load.assert_called_once_with(module)
            self.assertEqual(observed[0][1:], (['--once'] if command == 'prepare' else []) + ['--data', str(self.data)])
            self.assertIs(sys.argv, original)

    def test_scan_dispatch_runs_existing_discovery_with_stubbed_network(self):
        payload = [dict(id='one', text='Agent Engineer', descriptionPlain='Build AI agents with Python',
                        hostedUrl='https://jobs.lever.co/binance/one', applyUrl='https://jobs.lever.co/binance/one/apply',
                        categories=dict(location='Remote'))]
        with patch('hunt.discovery.fetch', return_value=json.dumps(payload).encode()) as transport:
            code, output, _ = self.invoke(['scan', '--source', 'lever', '--keyword', 'Agent', '--max-jobs', '1', '--skip-entry-checks'])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)['jobs'], 1)
        self.assertEqual(transport.call_count, 1)

    def test_no_submission_command_is_exposed(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as failure:
            main(['execute', '--data', str(self.data)])
        self.assertEqual(failure.exception.code, 2)

    def test_catalog_is_machine_readable_without_creating_a_store(self):
        with patch('hunt.__main__.Store', side_effect=AssertionError('Catalog must not initialize private data')):
            code, result, _ = self.json(['catalog'])
        self.assertEqual(code, 0)
        self.assertIn('minimax', [row['id'] for row in result['companies']])


class AgentModeTests(unittest.TestCase):
    """Commands an external agent (Claude Code, Codex) uses to orient and classify; every one prints JSON."""
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.data = self.root / 'data'
        store = Store(self.data)
        source = dict(kind='resume', reference='test://cv')
        facts = [dict(id='f-name', text='姓名：林测试', source=source, status='confirmed', version=1, disclosure='private'),
                 dict(id='f-phone', text='电话 138 1234 5678，邮箱 lin.test@example.com', source=source, status='confirmed', version=1, disclosure='private'),
                 dict(id='f-work', text='3 年 Python 后端开发，熟练使用 SQL。', source=source, status='confirmed', version=1, disclosure='private'),
                 dict(id='f-draft', text='未确认：精通 Go', source=source, status='unconfirmed', version=1, disclosure='private')]
        store.action(dict(action='candidate', candidate=dict(name='林测试', facts=facts)))
        for n, (title, jd) in enumerate([('后端开发工程师', '任职要求：\n3年以上 Python 经验，熟悉 SQL 与 Docker。'),
                                         ('软件工程师', '写页面为主。' + '长' * 5000), ('厨师', '负责后厨。')]):
            store.import_job(dict(title=title, jd=jd, company='公司%d' % n, channel='local', platform_id='p%d' % n))
        self.ids = {j['title']: j['id'] for j in store.state()['jobs']}

    def run_cli(self, *arguments):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = main(list(arguments) + ['--data', str(self.data)])
        return code, json.loads(out.getvalue())

    def write(self, name, value):
        path = self.root / name
        path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
        return str(path)

    def choose(self, *ids):
        return self.run_cli('directions', 'set', self.write('dirs.json', dict(directions=list(ids))))

    def test_profile_has_redacted_confirmed_facts_and_no_contact_details(self):
        code, result = self.run_cli('profile', '--json')
        self.assertEqual(code, 0)
        text = json.dumps(result, ensure_ascii=False)
        for secret in ('138 1234 5678', '13812345678', 'lin.test@example.com', '林测试'):
            self.assertNotIn(secret, text)
        self.assertEqual([f['id'] for f in result['facts']], ['f-name', 'f-phone', 'f-work'])
        self.assertIn('Python', text)
        self.assertNotIn('精通 Go', text)
        self.assertNotIn('fields', result['profile'])

    def test_directions_list_and_set_by_agent(self):
        code, listed = self.run_cli('directions', 'list')
        self.assertEqual(code, 0)
        row = next(r for r in listed['directions'] if r['id'] == 'backend')
        self.assertEqual((row['name'], row['family']), ('后端开发', '技术研发'))
        code, result = self.choose('backend', 'frontend')
        self.assertEqual(code, 0)
        self.assertEqual([d['id'] for d in result['directions']], ['backend', 'frontend'])
        self.assertEqual(result['by'], 'agent')
        code, result = self.run_cli('directions', 'set', self.write('bad.json', dict(directions=['no-such'])))
        self.assertEqual(code, 1)
        self.assertIn('no-such', result['error'])

    def test_jobs_export_lists_unclassified_with_clipped_text(self):
        self.choose('backend', 'frontend')
        code, result = self.run_cli('jobs', 'export', '--unclassified')
        self.assertEqual(code, 0)
        self.assertEqual([d['id'] for d in result['directions']], ['backend', 'frontend'])
        rows = {r['title']: r for r in result['jobs']}
        self.assertEqual(set(rows), {'后端开发工程师', '软件工程师', '厨师'})  # nothing classified yet
        self.assertEqual(set(rows['软件工程师']), {'id', 'title', 'company', 'jd', 'direction'})
        self.assertEqual(len(rows['软件工程师']['jd']), 4000)
        Store(self.data).action(dict(action='classify'))
        code, result = self.run_cli('jobs', 'export', '--unclassified')
        self.assertEqual([r['title'] for r in result['jobs']], ['软件工程师'])  # rules were unclear only here
        code, result = self.run_cli('jobs', 'export', '--limit', '1')
        self.assertEqual(len(result['jobs']), 1)

    def test_classify_import_writes_agent_choices_all_or_nothing(self):
        self.choose('backend', 'frontend')
        good = [dict(job_id=self.ids['软件工程师'], direction_id='frontend', reason='写页面'), dict(job_id=self.ids['厨师'], direction_id=None)]
        code, result = self.run_cli('classify', 'import', self.write('ok.json', good))
        self.assertEqual((code, result['imported']), (0, 2))
        jobs = {j['title']: j.get('direction') for j in Store(self.data).state()['jobs']}
        self.assertEqual((jobs['软件工程师']['id'], jobs['软件工程师']['by'], jobs['软件工程师']['reason']), ('frontend', 'agent', '写页面'))
        self.assertEqual((jobs['厨师']['id'], jobs['厨师']['by']), (None, 'agent'))
        for bad in ([dict(job_id=self.ids['后端开发工程师'], direction_id='backend'), dict(job_id=self.ids['厨师'], direction_id='sales')],
                    [dict(job_id='nope', direction_id='backend')], [dict(job_id=self.ids['厨师'])], {'not': 'a list'},
                    [dict(job_id=self.ids['厨师'], direction_id='backend', reason='x' * 201)]):
            code, result = self.run_cli('classify', 'import', self.write('bad.json', bad))
            self.assertEqual(code, 1)
            self.assertTrue(result['error'])
        self.assertNotIn('direction', next(j for j in Store(self.data).state()['jobs'] if j['title'] == '后端开发工程师'))

    def test_summary_per_direction_and_for_one(self):
        self.choose('backend', 'frontend')
        Store(self.data).action(dict(action='classify'))
        code, result = self.run_cli('summary')
        self.assertEqual(code, 0)
        self.assertEqual([s['id'] for s in result['directions']], ['backend', 'frontend'])
        backend = result['directions'][0]
        self.assertEqual((backend['name'], backend['count']), ('后端开发', 1))
        self.assertIn('Docker', backend['missing'])
        self.assertEqual(backend['matched_facts'], ['f-work'])
        self.assertEqual(result['other_count'], 2)
        code, result = self.run_cli('summary', '--direction', 'frontend')
        self.assertEqual([s['id'] for s in result['directions']], ['frontend'])
        code, result = self.run_cli('summary', '--direction', 'sales')
        self.assertEqual(code, 1)


if __name__ == '__main__':
    unittest.main()
