import unittest

from hunt.imtoken import BASE, listed_links, parse_job, read_jobs, sitemap_jobs
from hunt.network import FetchError
from hunt.sources import SourceError


def detail(title='Senior Backend Engineer (Wallet)', email=True):
    return '<div class="sqs-html-content"><h3>' + title + '</h3><h4>Location</h4><ul><li>Singapore | Remote</li></ul><h4>About the role</h4><p>Build the Web3 wallet backend using Python and Golang. Maintain reliable blockchain indexing and transaction services.</p><h4>Skills and qualifications</h4><ul><li>Experience with PostgreSQL, Redis and distributed system observability.</li></ul></div>' + ('<div><h4>Apply by emailing us at <a href="mailto:hr@token.im">hr@token.im</a></h4></div>' if email else '')


def sitemap(*paths):
    return ('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + ''.join(
        '<url><loc>' + BASE + path + '</loc><lastmod>2026-04-03</lastmod></url>' for path in paths) + '</urlset>').encode()


class ImTokenTests(unittest.TestCase):
    def report(self):
        return dict(pages=0, fetched=0, truncated=False)

    def test_current_broken_template_does_not_mean_zero_jobs(self):
        broken = '<script>window.jobs=[{title: ,department: ,area: ,link: }]</script>'
        self.assertEqual(listed_links(broken), [])
        self.assertEqual(listed_links('<script>window.jobs=[{link:"/en/backend"}]</script>'), [BASE + '/en/backend'])

    def test_list_only_accepts_same_employer_job_paths(self):
        html = '<a href="https://evil.example/en/engineer">Engineer</a><a href="/en/home#jobs-table">Jobs</a><a href="/en/backend">Engineer</a>'
        self.assertEqual(listed_links(html), [BASE + '/en/backend'])

    def test_sitemap_deduplicates_languages_and_preserves_metadata(self):
        rows = sitemap_jobs(sitemap('/cn/senior-backend-engineer', '/en/senior-backend-engineer', '/en/home'))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['url'], BASE + '/en/senior-backend-engineer')
        self.assertEqual(rows[0]['lastmod'], '2026-04-03')
        with self.assertRaises(SourceError):
            sitemap_jobs(b'<!DOCTYPE x [<!ENTITY boom "x">]><urlset/>')

    def test_detail_has_actual_body_location_and_exact_email(self):
        row = parse_job(detail(), BASE + '/en/backend')
        self.assertEqual(row['title'], 'Senior Backend Engineer (Wallet)')
        self.assertEqual(row['location'], 'Singapore | Remote')
        self.assertIn('Skills and qualifications\n', row['jd'])
        self.assertEqual(row['raw']['public_application_email'], 'hr@token.im')
        self.assertEqual(row['status'], 'unverified')
        self.assertIsNone(row['published_at'])

    def test_email_is_never_invented_from_plain_text_or_company_name(self):
        row = parse_job(detail(email=False) + '<p>hr@token.im</p>', BASE + '/en/backend')
        self.assertNotIn('public_application_email', row['raw'])

    def test_generic_and_explicitly_closed_pages_are_not_jobs(self):
        with self.assertRaises(SourceError):
            parse_job('<h3>Careers</h3><p>Join imToken</p>', BASE + '/en/backend')
        with self.assertRaises(SourceError) as ctx:
            parse_job('<h1>Position is closed</h1>' + detail(), BASE + '/en/backend')
        self.assertEqual(ctx.exception.status, 'closed')

    def test_sitemap_recovery_never_claims_current_listing_or_open_vacancy(self):
        calls = []
        def read(url):
            calls.append(url)
            if url.endswith('/robots.txt'): return ('Sitemap: ' + BASE + '/sitemap.xml\n').encode()
            if url.endswith('/sitemap.xml'): return sitemap('/en/backend', '/en/frontend')
            return detail().encode()
        report = self.report()
        rows = list(read_jobs(dict(url=BASE + '/', company='imToken'), read, ['Web3'], 1, 2, report, '<script>window.jobs=[{link: }]</script>'))
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(calls), 3)
        self.assertEqual(report['listing_status'], 'unavailable')
        route = rows[0]['raw']['application_route']
        self.assertEqual(route['evidence_type'], 'sitemap')
        self.assertEqual(route['entry_type'], 'email')
        self.assertIn('是否仍在招需确认', route['note'])
        self.assertEqual(rows[0]['status'], 'unverified')
        self.assertIsNone(rows[0]['published_at'])
        self.assertEqual(rows[0]['raw']['page_last_modified'], '2026-04-03')
        self.assertTrue(report['truncated'])

    def test_current_list_does_not_need_sitemap_and_honors_detail_limit(self):
        calls = []
        def read(url):
            calls.append(url); return detail().encode()
        report = self.report()
        rows = list(read_jobs(dict(url=BASE + '/'), read, ['Web3'], 5, 1, report,
                             '<a href="/en/backend">Backend</a><a href="/en/frontend">Frontend</a>'))
        self.assertEqual(calls, [BASE + '/en/backend'])
        self.assertEqual(len(rows), 1)
        self.assertEqual(report['listing_status'], 'observed')
        self.assertEqual(rows[0]['raw']['application_route']['evidence_type'], 'link')

    def test_offsite_sitemap_is_not_followed(self):
        calls = []
        def read(url):
            calls.append(url); return b'Sitemap: https://evil.example/sitemap.xml\n'
        with self.assertRaises(SourceError):
            list(read_jobs(dict(url=BASE + '/'), read, ['Web3'], 2, 2, self.report(), 'No list'))
        self.assertEqual(calls, [BASE + '/robots.txt'])

    def test_home_network_error_can_recover_unverified_sitemap_leads(self):
        def read(url):
            if url == BASE + '/': raise FetchError('Broken pipe')
            if url.endswith('/robots.txt'): return ('Sitemap: ' + BASE + '/sitemap.xml').encode()
            if url.endswith('/sitemap.xml'): return sitemap('/en/backend')
            return detail().encode()
        report = self.report()
        rows = list(read_jobs(dict(url=BASE + '/'), read, ['Web3'], 1, 1, report))
        self.assertEqual(rows[0]['status'], 'unverified')
        self.assertEqual(report['homepage_error'], 'Broken pipe')
        self.assertEqual(report['listing_status'], 'unavailable')

    def test_recent_engineering_page_precedes_stale_exact_slug(self):
        calls = []
        raw = sitemap('/en/blockchain-engineer', '/en/backend-engineer').replace(
            b'blockchain-engineer</loc><lastmod>2026-04-03', b'blockchain-engineer</loc><lastmod>2022-01-01')
        def read(url):
            calls.append(url)
            if url.endswith('/robots.txt'): return ('Sitemap: ' + BASE + '/sitemap.xml').encode()
            if url.endswith('/sitemap.xml'): return raw
            return detail().encode()
        list(read_jobs(dict(url=BASE + '/'), read, ['Web3'], 1, 1, self.report(), 'No list'))
        self.assertEqual(calls[-1], BASE + '/en/backend-engineer')

    def test_failed_detail_does_not_hide_other_roles(self):
        def read(url):
            if url.endswith('/broken'): raise FetchError('Broken pipe')
            return detail().encode()
        report = self.report()
        rows = list(read_jobs(dict(url=BASE + '/'), read, ['Web3'], 2, 2, report,
                             '<a href="/en/broken">Broken</a><a href="/en/backend">Backend</a>'))
        self.assertEqual(len(rows), 1)
        self.assertEqual(report['detail_errors'][0]['status'], 'fetch_error')

    def test_optional_public_renderer_recovers_detail_transport_failure(self):
        class Renderer:
            def read(self, url): return dict(url=url, body=detail().encode(), status=200)
        def read(url): raise FetchError('Broken pipe')
        rows = list(read_jobs(dict(url=BASE + '/'), read, ['Web3'], 1, 1, self.report(),
                             '<a href="/en/backend">Backend</a>', Renderer()))
        self.assertEqual(len(rows), 1)


if __name__ == '__main__': unittest.main()
