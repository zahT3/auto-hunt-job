import unittest
from types import SimpleNamespace
from unittest.mock import patch
from hunt import providers
from hunt.providers import Provider, REGISTRY, register, route
from hunt.discovery import discover
from hunt.sources import normalize


class ProviderRegistryTests(unittest.TestCase):
    def test_existing_kinds_registered(self):
        for pid in ('greenhouse', 'lever', 'ashby', 'boss', 'liepin', 'anker', 'website', 'websearch'):
            self.assertIn(pid, REGISTRY)
            self.assertEqual(REGISTRY[pid].id, pid)

    def test_route_prefers_explicit_kind(self):
        self.assertIs(route(dict(kind='lever', board='x')), REGISTRY['lever'])

    def test_route_uses_detect(self):
        def detect(entry):
            if 'example.test' in (entry.get('careers_url') or ''): return dict(entry, kind='probe-test')
        probe = Provider(id='probe-test', detect=detect, fetch=lambda entry, ctx: iter(()))
        with patch.dict(REGISTRY):
            register(probe)
            self.assertIs(route(dict(careers_url='https://jobs.example.test')), probe)
            self.assertIsNone(route(dict(careers_url='https://jobs.other.test')))
        self.assertNotIn('probe-test', REGISTRY)

    def test_unknown_kind_reports_not_configured(self):
        result = discover(dict(keywords=['AI'], discovery_sources=[dict(kind='nope')]), transport=lambda u, **kw: b'{}')
        self.assertEqual(result['sources'][0]['status'], 'not_configured')

    def test_unhashable_kind_reports_not_configured(self):
        result = discover(dict(keywords=['AI'], discovery_sources=[dict(kind=['x'])]), transport=lambda u, **kw: b'{}')
        self.assertEqual(result['sources'][0]['status'], 'not_configured')

    def test_detected_entry_is_completed_and_fetched(self):
        seen = []
        def detect(entry):
            if 'example.test' in (entry.get('careers_url') or ''): return dict(entry, kind='probe-test', board='acme')
        def fetch(entry, ctx):
            seen.append(entry)
            yield normalize('probe-test', entry['board'] + ':' + entry['careers_url'][-1], 'AI Engineer', 'Build AI',
                            entry['careers_url'], company='Acme', status='open')
        with patch.dict(REGISTRY):
            register(Provider(id='probe-test', detect=detect, fetch=fetch))
            result = discover(dict(keywords=['AI'], discovery_sources=[
                dict(careers_url='https://jobs.example.test/a'), dict(careers_url='https://jobs.example.test/b')]),
                transport=lambda u, **kw: b'{}')
        self.assertEqual([e['board'] for e in seen], ['acme', 'acme'])
        self.assertEqual(len(result['jobs']), 2)
        reports = result['sources']
        self.assertEqual([r['kind'] for r in reports], ['probe-test', 'probe-test'])
        self.assertEqual(len({r['source_id'] for r in reports}), 2)
        self.assertEqual(reports[0]['source_id'], 'probe-test:jobs.example.test/a')

    def test_load_all_imports_every_submodule(self):
        with patch('pkgutil.iter_modules', return_value=[SimpleNamespace(name='demo')]), \
             patch('importlib.import_module') as load:
            providers.load_all()
        load.assert_called_once_with('hunt.providers.demo')



def keyword_board(titles):
    """A remote keyword-search provider over a fixed board: paged_jobs pages through `titles`, 3 per page."""
    def fetch(entry, ctx):
        def fetch_page(term, page):
            return [dict(id=str(n), title=t) for n, t in enumerate(titles)][(page - 1) * 3:page * 3], len(titles)
        make = lambda row: normalize('kw-test', row['id'], row['title'], 'JD ' + row['title'], 'https://kw.example.test/' + row['id'], company='K')
        return providers.paged_jobs(ctx, fetch_page, make, lambda row: row['id'], 3)
    return Provider(id='kw-test', fetch=fetch)


class KeywordBudgetFilterTests(unittest.TestCase):
    TITLES = ['厨师', 'AI 产品经理', '仓库管理员', 'AI产品经理（高级）', '财务', '前台', 'AI 产品经理-搜索', '保安', 'AI 产品专员']

    def collect(self, keep, limit=2, pages=5):
        report = dict(pages=0, fetched=0, truncated=False)
        ctx = providers.Context(lambda url, **kw: b'', ['AI 产品经理'], limit, pages, report, keep=keep)
        return [j['title'] for j in keyword_board(self.TITLES).fetch({}, ctx)], report

    def test_dropped_jobs_do_not_count_toward_the_limit(self):
        titles, report = self.collect(lambda job: 'AI' in job['title'] and '产品经理' in job['title'])
        self.assertEqual(titles, ['AI 产品经理', 'AI产品经理（高级）'])
        # Truncated only once another *kept* job turns up past the limit ('AI 产品经理-搜索'); the four dropped
        # on the way (厨师, 仓库管理员, 财务, 前台) say nothing about whether the board has more.
        self.assertEqual(report['filtered'], 4)
        self.assertTrue(report['truncated'])

    def test_without_keep_every_job_counts(self):
        titles, report = self.collect(None)
        self.assertEqual(titles, ['厨师', 'AI 产品经理'])
        self.assertNotIn('filtered', report)

    def test_sweep_keeps_only_title_matches_from_keyword_providers(self):
        with patch.dict(REGISTRY):
            register(keyword_board(self.TITLES))
            sweep = discover(dict(keywords=['AI 产品经理'], sweep=True, check_entries=False, discovery_sources=[dict(id='k', kind='kw-test')]),
                             transport=lambda u, **kw: b'{}')
            plain = discover(dict(keywords=['AI 产品经理'], check_entries=False, max_pages=5, discovery_sources=[dict(id='k', kind='kw-test')]),
                             transport=lambda u, **kw: b'{}')
        self.assertEqual([j['title'] for j in sweep['jobs']], ['AI 产品经理', 'AI产品经理（高级）', 'AI 产品经理-搜索'])
        self.assertEqual(sweep['sources'][0]['filtered'], 6)
        self.assertEqual(len(plain['jobs']), 9)  # outside a sweep nothing changes: the remote search is trusted as before

    def test_a_company_board_is_not_filtered_even_in_a_sweep(self):
        with patch.dict(REGISTRY):
            register(keyword_board(self.TITLES))
            own = discover(dict(keywords=['AI 产品经理'], sweep=True, check_entries=False,
                                discovery_sources=[dict(id='k', kind='kw-test', broad=False)]), transport=lambda u, **kw: b'{}')
        self.assertEqual((len(own['jobs']), own['sources'][0]['filtered']), (9, 0))


if __name__ == '__main__':
    unittest.main()
