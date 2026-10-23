import json
import unittest
from datetime import datetime, timezone, timedelta
from hunt.careers import linked_boards, preserve_entry_check
from hunt.discovery import discover, source_configs
from hunt.sources import SourceError
from hunt.sources_browser import navigation_state


class CareerTests(unittest.TestCase):
    def test_entry_observation_expires_and_cannot_follow_a_different_receiver(self):
        url = 'https://jobs.lever.co/acme/role/apply'
        check = dict(status='not_found', url=url, checked_at=datetime.now(timezone.utc).isoformat())
        previous = dict(application_route=dict(entry_check=check))
        self.assertEqual(preserve_entry_check(previous, {}, url)['application_route']['entry_check'], check)
        self.assertEqual(preserve_entry_check(previous, {}, url + '/other'), {})
        check['checked_at'] = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        self.assertEqual(preserve_entry_check(previous, {}, url), {})

    def test_only_explicit_supported_board_references_are_used(self):
        html = '''<a href="https://jobs.lever.co/acme/abc">Apply</a>
        <a href="https://jobs.lever.co.evil.example/fake">Ignore</a>
        <iframe src="https://boards.greenhouse.io/acme"></iframe>
        <a href="https://secret@jobs.lever.co/other">Ignore</a>'''
        boards = linked_boards(html, 'https://acme.example/careers')
        self.assertEqual([(b['kind'], b['board']) for b in boards], [('lever', 'acme'), ('greenhouse', 'acme')])
        self.assertTrue(all(b['career_url'] == 'https://acme.example/careers' for b in boards))

    def test_nextjs_explicit_references_are_deduplicated_without_executing_scripts(self):
        html = '<script>self.__next_f.push([1,' + json.dumps('"jobUrl":"https://jobs.ashbyhq.com/acme/id","applyUrl":"https://jobs.ashbyhq.com/acme/id/application"') + ']);</script>'
        boards = linked_boards(html, 'https://acme.example/careers')
        self.assertEqual(len(boards), 1)
        self.assertEqual(boards[0]['kind'], 'ashby')
        self.assertEqual(boards[0]['evidence_type'], 'embedded_url')

    def test_career_page_to_api_body_and_application_link(self):
        calls = []
        def read(url, **kwargs):
            calls.append((url, kwargs))
            if url == 'https://acme.example/careers':
                return b'<a href="https://jobs.lever.co/acme">Open roles</a>'
            return json.dumps([dict(id='role-1', text='AI Developer', descriptionPlain='Build AI agents with Python.',
                hostedUrl='https://jobs.lever.co/acme/role-1', applyUrl='https://jobs.lever.co/acme/role-1/apply')]).encode()
        result = discover(dict(sources=['website'], company_boards=[dict(type='website', url='https://acme.example/careers')],
                          keywords=['AI'], max_pages=2, max_jobs=3), transport=read)
        self.assertEqual(len(result['jobs']), 1)
        job = result['jobs'][0]
        self.assertIn('Python', job['jd'])
        self.assertEqual(job['application_url'], 'https://jobs.lever.co/acme/role-1/apply')
        self.assertEqual(job['raw']['application_route']['career_url'], 'https://acme.example/careers')
        self.assertEqual(result['sources'][0]['pages'], 2)
        self.assertEqual(result['sources'][0]['status'], 'ok')
        self.assertTrue(all(kw.get('method', 'GET') == 'GET' for _, kw in calls))

    def test_career_discovery_budget_applies_to_ats_request(self):
        result = discover(dict(sources=['website'], company_boards=[dict(type='website', url='https://acme.example/careers')],
            keywords=['AI'], max_pages=2, discovery_requests=1), transport=lambda *a, **k: b'<a href="https://jobs.lever.co/acme">Jobs</a>')
        self.assertEqual(result['sources'][0]['status'], 'budget_exhausted')
        self.assertFalse(result['jobs'])

    def test_board_link_with_page_limit_is_partial_not_empty_success(self):
        result = discover(dict(sources=['website'], company_boards=[dict(type='website', url='https://acme.example/careers')],
            keywords=['AI'], max_pages=1), transport=lambda *a, **k: b'<a href="https://jobs.lever.co/acme">Jobs</a>')
        self.assertTrue(result['sources'][0]['truncated'])
        self.assertFalse(result['jobs'])

    def test_official_only_never_contacts_recruitment_platforms(self):
        calls = []
        def read(url, **kwargs): calls.append(url); return b'{"jobs":[]}'
        result = discover(dict(sources=['boss','liepin','ashby'], official_only=True, keywords=['AI']), transport=read)
        self.assertEqual([s['kind'] for s in result['sources']], ['ashby'])
        self.assertTrue(all('ashbyhq.com' in url for url in calls))
        sources = source_configs(dict(discovery_sources=[dict(kind='boss'),dict(kind='lever',board='acme')], official_only=True))
        self.assertEqual([s['kind'] for s in sources], ['lever'])

    def test_blank_login_and_verification_have_distinct_diagnostics(self):
        for url, status in [('about:blank','blank_page'),('https://www.zhipin.com/web/user/','login_required'),
                            ('https://www.zhipin.com/web/passport/zp/verify.html','captcha')]:
            with self.assertRaises(SourceError) as error: navigation_state('boss', url)
            self.assertEqual(error.exception.status, status)
        navigation_state('boss', 'https://www.zhipin.com/web/geek/jobs')
        with self.assertRaises(SourceError): navigation_state('boss', 'https://www.zhipin.com.evil.example/')


if __name__ == '__main__': unittest.main()
