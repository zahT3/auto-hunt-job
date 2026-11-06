"""Synthetic contract cases; the real JD acceptance is recorded separately."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from hunt.app.cli import main
from hunt.app.store import Store
from hunt.search.sources.acs import build_job


class ACSTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.html = self.root / 'page.html'
        self.html.write_text('<article>synthetic contract fixture</article>')
        self.result = self.root / 'acs.json'
        body = 'Example Company\nSmart Contract Engineer\nRemote\n' + 'Build Solidity applications and review contract security.\n' * 6
        self.document = dict(schema_version=1, operation='extract', execution_status='completed',
            source=dict(url='https://jobs.example.org/?id=1#/job/1',
                        sha256=hashlib.sha256(self.html.read_bytes()).hexdigest(), file='/never/read/me'),
            data=dict(content_text=body, content_sha256=hashlib.sha256(body.encode()).hexdigest()),
            quality=dict(status='checks_passed', kind='article', completeness='unknown'),
            created_at='2026-11-05T00:00:00+00:00', engine='trafilatura')
        self.write()

    def write(self):
        self.result.write_text(json.dumps(self.document))

    def build(self, **changes):
        return build_job(self.result, self.html, **(dict(title='Smart Contract Engineer',
                         company='Example Company', location='Remote') | changes))

    def test_import_has_evidence_but_no_application_approval(self):
        job = self.build()
        store = Store(self.root / 'isolated')
        self.addCleanup(store.prepare_pool.shutdown)
        saved, duplicate = store.import_job(job)
        repeated, duplicate_again = store.import_job(self.build())
        self.assertFalse(duplicate)
        self.assertTrue(duplicate_again)
        self.assertEqual(saved['id'], repeated['id'])
        self.assertEqual(saved['availability'], 'unverified')
        self.assertEqual(saved['status'], 'new')
        self.assertIsNone(saved['approval'])
        self.assertIsNone(saved['package'])
        self.assertIsNone(saved['application_url'])
        self.assertIsNone(saved['salary'])
        self.assertEqual(saved['raw']['source_url'], self.document['source']['url'])
        self.assertEqual(saved['raw']['content_sha256'], self.document['data']['content_sha256'])

    def test_hash_fragment_and_query_are_distinct_identities(self):
        first = self.build()['platform_id']
        self.document['source']['url'] = 'https://jobs.example.org/?id=2#/job/2'
        self.write()
        self.assertNotEqual(first, self.build()['platform_id'])

    def test_rejects_failed_and_unchecked_extraction(self):
        for field, value in [('execution_status', 'failed'), ('operation', 'crawl')]:
            with self.subTest(field=field):
                old = self.document[field]
                self.document[field] = value
                self.write()
                with self.assertRaises(ValueError): self.build()
                self.document[field] = old
        self.document['quality']['status'] = 'unavailable'
        self.write()
        with self.assertRaises(ValueError): self.build()

    def test_refuses_body_or_snapshot_tampering(self):
        self.document['data']['content_text'] += 'tampered'
        self.write()
        with self.assertRaisesRegex(ValueError, '正文哈希'): self.build()
        self.html.write_text('changed')
        with self.assertRaisesRegex(ValueError, '来源哈希'): self.build()

    def test_refuses_invented_fields_and_private_source(self):
        with self.assertRaises(ValueError): self.build(title='Chief Executive Officer')
        with self.assertRaises(ValueError): self.build(location='London')
        self.document['source']['url'] = 'https://127.0.0.1/'
        self.write()
        with self.assertRaises(ValueError): self.build()

    def test_preview_does_not_create_database(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), patch('hunt.app.cli.Store', side_effect=AssertionError('Preview must not open a store')):
            code = main(['acs', '--result', str(self.result), '--html', str(self.html),
                         '--title', 'Smart Contract Engineer', '--company', 'Example Company'])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout.getvalue())['status'], 'preview')
        self.assertFalse(list(self.root.rglob('*.sqlite3')))

    def test_cli_imports_only_into_explicit_data_and_deduplicates(self):
        data = self.root / 'cli-data'
        fetched_at = '2026-11-05T00:00:00+00:00'
        responses = []
        for duplicate in (False, True):
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = main(['acs', '--result', str(self.result), '--html', str(self.html),
                             '--title', 'Smart Contract Engineer', '--company', 'Example Company',
                             '--location', 'Remote', '--fetched-at', fetched_at, '--data', str(data)])
            self.assertEqual(code, 0)
            response = json.loads(stdout.getvalue())
            self.assertEqual(response['status'], 'imported')
            self.assertIs(response['duplicate'], duplicate)
            self.assertEqual(response['availability'], 'unverified')
            self.assertEqual(response['application_status'], 'new')
            self.assertEqual(response['data_dir'], str(data.resolve()))
            responses.append(response)
        self.assertEqual(responses[0]['job_id'], responses[1]['job_id'])
        store = Store(data)
        self.addCleanup(store.prepare_pool.shutdown)
        jobs = store.state()['jobs']
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]['jd'], self.document['data']['content_text'])
        self.assertEqual(jobs[0]['location'], 'Remote')
        self.assertEqual(jobs[0]['raw']['fetched_at'], fetched_at)
        self.assertEqual(jobs[0]['attempts'], [])

    def test_cli_rejects_invalid_input_before_opening_store(self):
        data = self.root / 'rejected'
        self.document['data']['content_text'] += 'tampered'
        self.write()
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr), \
                patch('hunt.app.cli.Store', side_effect=AssertionError('Invalid input must not open a store')):
            code = main(['acs', '--result', str(self.result), '--html', str(self.html),
                         '--title', 'Smart Contract Engineer', '--company', 'Example Company', '--data', str(data)])
        self.assertEqual(code, 1)
        self.assertEqual(stdout.getvalue(), '')
        response = json.loads(stderr.getvalue())
        self.assertEqual(response['status'], 'failed')
        self.assertIn('正文哈希', response['error'])
        self.assertFalse(data.exists())

    def test_missing_metadata_stays_unknown_and_time_needs_timezone(self):
        job = self.build(location=None)
        self.assertIsNone(job['location'])
        self.assertIsNone(job['raw']['fetched_at'])
        self.assertIsNone(job['published_at'])
        with self.assertRaises(ValueError): self.build(fetched_at='2026-11-05T00:00:00')


if __name__ == '__main__':
    unittest.main()
