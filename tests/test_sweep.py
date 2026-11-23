"""Sweep mode: bounded wide search with fair shares, a deadline and partial preparation."""
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from hunt.ai import classify
from hunt.app.store import Store
from hunt.net.network import TransientFetchError
from hunt.search.query import RecallRule, recall_rules
from hunt.base import Error
from hunt.search.engine import discover
from hunt.search.sources import Provider, REGISTRY, paged_jobs, register
from hunt.search.parse import normalize, SourceError


def job(source, n):
    return normalize('sweep-test', source + '-' + str(n), 'AI Engineer ' + str(n), 'Build AI systems ' + str(n),
                     'https://jobs.example.test/' + source + '/' + str(n), company=source, status='open')


def sources(*names):
    return [dict(id=n, kind='sweep-test', name=n) for n in names]


def provider(counts, hook=None):
    """Yields min(ctx.limit, counts[name]) jobs per source; counts[name] None means unlimited.

    Like the real providers, it marks the report truncated only when more jobs exist beyond ctx.limit."""
    def fetch(entry, ctx):
        if hook: hook(entry, ctx)
        wanted = counts.get(entry['name'], 0)
        n = 0
        while (wanted is None or n < wanted) and n < ctx.limit:
            yield job(entry['name'], n); n += 1
        if wanted is None or wanted > n: ctx.report['truncated'] = True
    return Provider(id='sweep-test', fetch=fetch)


def run_discover(config, prov, **kwargs):
    with patch.dict(REGISTRY):
        register(prov)
        return discover(dict(dict(keywords=['AI'], check_entries=False), **config), transport=lambda u, **kw: b'{}', **kwargs)


class SweepDiscoveryTests(unittest.TestCase):
    def test_new_direction_probes_and_classifies_a_custom_board_from_metadata(self):
        direction = dict(id='sound-review', name='声学评审', titles=['音频评审'])
        rule = RecallRule(dict(direction, recall=dict(
            topics=['声学'], role_patterns=['评审'], remote_probes=['音质', '音轨'],
            role_probe='评审', literal_role_probe='评审师', waive_topic_if='audio_studio')))
        queries = []
        def fetch(source, ctx):
            queries.extend(ctx.terms)
            for n, title in enumerate(['画面设计', '交付评审']):
                row = dict(job(source['id'], n), title=title)
                if ctx.keep(row):
                    yield row
        source = dict(id='sample-board', kind='sweep-test', audio_studio=True)
        with patch.dict(recall_rules(), {direction['id']: rule}):
            result = run_discover(dict(keywords=[direction['name']], sweep=True, discovery_sources=[source]),
                                  Provider('sweep-test', fetch, probe_mode='remote'))
            self.assertEqual(queries, ['评审', '声学评审'])
            self.assertEqual([r['title'] for r in result['jobs']], ['交付评审'])
            record = result['jobs'][0]
            classify.classify_jobs([record], [direction], {}, None, None, None)
            self.assertEqual(record['direction']['id'], direction['id'])
            record['raw']['discovery']['audio_studio'] = False
            self.assertTrue(classify.stale(record, [direction['id']]))
            self.assertEqual(rule.source_queries(['声学评审'], {'probe_limit': 1}, 'remote'), ['声学评审', '音质'])

    def test_sweep_defaults(self):
        result = run_discover(dict(sweep=True, discovery_sources=sources('a')), provider(dict(a=1)))
        self.assertEqual(result['sweep'], dict(max_companies=300, max_jobs=1500, requests=3000, deadline_seconds=600, prepare=50, max_pages=20, workers=4))
        self.assertFalse(result['deadline_reached'])
        self.assertTrue(result['started_at'] and result['finished_at'])

    def test_sweep_bounds_clamped(self):
        result = run_discover(dict(sweep=True, sweep_max_jobs=99999, sweep_deadline_seconds=1, sweep_max_companies=0,
                                   sweep_requests=10 ** 6, sweep_prepare=-3, sweep_max_pages=999, discovery_sources=sources('a')), provider(dict(a=1)))
        self.assertEqual(result['sweep'], dict(max_companies=1, max_jobs=5000, requests=10000, deadline_seconds=30, prepare=0, max_pages=50, workers=4))

    def test_non_sweep_unchanged(self):
        result = run_discover(dict(max_jobs=500, discovery_sources=sources('a')), provider(dict(a=None)))
        self.assertEqual(len(result['jobs']), 100)
        self.assertIsNone(result['sweep'])
        self.assertFalse(result['deadline_reached'])

    def test_non_sweep_keeps_twenty_source_cap(self):
        names = ['s' + str(i) for i in range(30)]
        result = run_discover(dict(discovery_sources=sources(*names)), provider({n: 1 for n in names}))
        self.assertEqual(len(result['sources']), 20)

    def test_sweep_company_cap(self):
        names = ['s' + str(i) for i in range(30)]
        counts = {n: 1 for n in names}
        result = run_discover(dict(sweep=True, sweep_max_companies=25, discovery_sources=sources(*names)), provider(counts))
        self.assertEqual(len(result['sources']), 25)
        wide = run_discover(dict(sweep=True, discovery_sources=sources(*names)), provider(counts))
        self.assertEqual(len(wide['sources']), 30)

    def test_fair_share_with_large_first_source(self):
        result = run_discover(dict(sweep=True, sweep_max_jobs=60, discovery_sources=sources('big', 'small', 'rest')),
                              provider(dict(big=None, small=3, rest=None)))
        got = {r['source_id']: r['returned'] for r in result['sources']}
        self.assertEqual(got, dict(big=20, small=3, rest=37))
        self.assertEqual(len(result['jobs']), 60)

    def test_limit_ignoring_provider_cannot_break_cap_or_fair_share(self):
        def fetch(entry, ctx):
            for n in range(100): yield job(entry['name'], n)
        result = run_discover(dict(sweep=True, sweep_max_jobs=30, discovery_sources=sources('a', 'b', 'c')), Provider(id='sweep-test', fetch=fetch))
        got = {r['source_id']: r['returned'] for r in result['sources']}
        self.assertEqual(got, dict(a=10, b=10, c=10))
        self.assertTrue(all(r['truncated'] for r in result['sources']))
        self.assertEqual(len(result['jobs']), 30)

    def test_quota_exactly_met_is_not_truncated(self):
        result = run_discover(dict(sweep=True, sweep_max_jobs=30, discovery_sources=sources('a', 'b', 'c')), provider(dict(a=10, b=10, c=10)))
        self.assertEqual([r['truncated'] for r in result['sources']], [False] * 3)

    def test_sweep_entry_budget_follows_prepare(self):
        calls = []
        def entry_calls(config):
            calls.clear()
            def fake_check(item, read, renderer=None):
                try: read('https://jobs.example.test/entry/' + item['platform_id'])
                except SourceError: pass
                return item
            with patch('hunt.search.entries.check_job', side_effect=fake_check), patch.dict(REGISTRY):
                register(provider(dict(a=300)))
                discover(dict(dict(keywords=['AI'], check_entries=True, discovery_sources=sources('a')), **config),
                         transport=lambda u, **kw: calls.append(u) or b'{}')
            return len([u for u in calls if '/entry/' in u])
        self.assertEqual(entry_calls(dict(sweep=True, sweep_prepare=50)), 50)
        self.assertEqual(entry_calls(dict(sweep=True, sweep_prepare=0)), 0)
        self.assertEqual(entry_calls(dict(sweep=True, sweep_prepare=50, entry_requests=5)), 5)
        self.assertEqual(entry_calls(dict(sweep=True, sweep_prepare=120, entry_requests=500)), 120)
        self.assertEqual(entry_calls(dict(sweep_prepare=50)), 12)
        self.assertEqual(entry_calls(dict(entry_requests=500, max_jobs=100)), 50)

    def test_fair_share_of_requests(self):
        def hook(entry, ctx):
            for i in range(1000):
                if entry['name'] == 'tiny' and i: break
                ctx.read('https://jobs.example.test/p/%d' % i)
        result = run_discover(dict(sweep=True, sweep_requests=30, discovery_sources=sources('big', 'tiny', 'rest')),
                              provider(dict(big=1, tiny=1, rest=1), hook))
        by = {r['source_id']: r for r in result['sources']}
        self.assertEqual(by['big']['requests'], 10)
        self.assertEqual(by['big']['status'], 'budget_exhausted')
        self.assertTrue(by['big']['truncated'])
        self.assertEqual(by['tiny']['requests'], 1)
        self.assertEqual(by['rest']['requests'], 19)
        self.assertEqual(result['requests'], 30)

    def test_retry_cannot_consume_a_waiting_sources_only_request(self):
        calls = []
        def transport(name):
            calls.append(name)
            if name == 'big':
                raise TransientFetchError('timed out')
        def fetch(entry, ctx):
            ctx.read(entry['id'])
            ctx.report['pages'] += 1
            yield job(entry['id'], 0)
        with patch.dict(REGISTRY):
            register(Provider('sweep-test', fetch))
            result = discover(dict(keywords=['AI'], sweep=True, sweep_requests=3, sweep_max_jobs=1,
                                   discovery_sources=sources('big', 'small', 'last')), transport=transport)
        self.assertEqual(calls, ['big', 'small', 'last'])
        big, small, last = result['sources']
        self.assertEqual((big['status'], big['first_page_read'], big['retries']), ('fetch_error', False, 0))
        self.assertEqual((small['returned'], last['returned'], last['first_page_read']), (1, 0, True))
        self.assertTrue(last['truncated'])
        self.assertFalse(last['continuation_deadline'])

    def test_retry_backoff_that_crosses_deadline_sends_no_request(self):
        calls = []
        now = [0.0]
        def transport(url):
            calls.append(url)
            raise TransientFetchError('timed out')
        def advance(_):
            now[0] = 31
        with patch.dict(REGISTRY), patch('hunt.search.engine.time.sleep', side_effect=advance):
            register(provider({'a': 1}, lambda entry, ctx: ctx.read('list')))
            result = discover(dict(keywords=['AI'], sweep=True, sweep_deadline_seconds=30,
                                   discovery_sources=sources('a')), transport=transport, clock=lambda: now[0])
        self.assertEqual(calls, ['list'])
        report = result['sources'][0]
        self.assertEqual((report['status'], report['truncated'], report['retries']), ('cancelled', True, 0))
        self.assertFalse(report['first_page_read'] or report['continuation_deadline'])

    def test_deadline_stops_new_requests(self):
        now = [0.0]
        def hook(entry, ctx):
            if entry['name'] == 'a': now[0] = 1000.0  # the first source runs past the deadline
        result = run_discover(dict(sweep=True, discovery_sources=sources('a', 'b', 'c')), provider(dict(a=2, b=2, c=2), hook),
                              clock=lambda: now[0])
        statuses = [r['status'] for r in result['sources']]
        self.assertEqual(statuses, ['ok', 'cancelled', 'cancelled'])
        self.assertEqual([j['company'] for j in result['jobs']], ['a', 'a'])
        self.assertTrue(result['deadline_reached'])
        self.assertTrue(result['sources'][1]['truncated'])
        self.assertFalse(result['sources'][1]['first_page_read'] or result['sources'][1]['continuation_deadline'])

    def test_deadline_mid_source_blocks_read_and_keeps_fetched_jobs(self):
        now = [0.0]
        def fetch(entry, ctx):
            yield job('a', 0)
            now[0] = 1000.0
            ctx.read('https://jobs.example.test/next')
            yield job('a', 1)
        result = run_discover(dict(sweep=True, discovery_sources=sources('a', 'b')), Provider(id='sweep-test', fetch=fetch), clock=lambda: now[0])
        self.assertEqual(len(result['jobs']), 1)
        self.assertEqual(result['sources'][0]['status'], 'cancelled')
        self.assertEqual(result['sources'][0]['returned'], 1)
        self.assertEqual(result['sources'][0]['requests'], 0)
        self.assertTrue(result['deadline_reached'])

    def test_deadline_before_entry_checks_keeps_job(self):
        now = [0.0]
        def hook(entry, ctx): now[0] = 1000.0
        with patch('hunt.search.entries.check_job') as check:
            result = run_discover(dict(sweep=True, check_entries=True, discovery_sources=sources('a')), provider(dict(a=1), hook), clock=lambda: now[0])
        check.assert_not_called()
        self.assertEqual(len(result['jobs']), 1)
        self.assertEqual(result['sources'][0]['status'], 'ok')
        self.assertEqual((result['entry_check']['checked'], result['entry_check']['skipped']), (0, 1))
        self.assertTrue(result['deadline_reached'])

    def test_second_pass_gives_leftover_share_to_truncated_source(self):
        result = run_discover(dict(sweep=True, sweep_max_jobs=60, discovery_sources=sources('big', 's1', 's2')),
                              provider(dict(big=None, s1=3, s2=3)))
        got = {r['source_id']: r['returned'] for r in result['sources']}
        self.assertEqual(got, dict(big=54, s1=3, s2=3))
        self.assertEqual(len(result['jobs']), 60)
        self.assertEqual(len({(j['channel'], j['platform_id']) for j in result['jobs']}), 60)
        self.assertEqual([j['platform_id'] for j in result['jobs'][:20]], ['big-%d' % n for n in range(20)])
        big = result['sources'][0]
        self.assertTrue(big['truncated'])
        self.assertEqual((big['status'], big['passes']), ('ok', 2))

    def test_second_pass_sums_elapsed_without_float_noise(self):
        now, steps = [0.0], iter([0.1, 0.0, 0.0, 0.2])
        def hook(entry, ctx): now[0] += next(steps)
        result = run_discover(dict(sweep=True, sweep_max_jobs=60, discovery_sources=sources('big', 's1', 's2')),
                              provider(dict(big=None, s1=3, s2=3), hook), clock=lambda: now[0])
        self.assertEqual(result['sources'][0]['elapsed_seconds'], 0.3)

    def test_first_pass_shares_split_among_relevant_sources_only(self):
        rows = sources('big', 's1', 't1', 't2', 't3', 't4', 't5')
        for row in rows: row['tier'] = 0 if row['name'] == 'big' else 1 if row['name'] == 's1' else 2
        result = run_discover(dict(sweep=True, sweep_max_jobs=60, discovery_sources=rows), provider(dict(big=None, s1=3)))
        # 60 jobs over the 2 relevant sources, not over all 7: big's first pass takes 30, its top-up the rest.
        self.assertEqual([j['platform_id'] for j in result['jobs'][:30]], ['big-%d' % n for n in range(30)])
        self.assertEqual(result['jobs'][30]['platform_id'], 's1-0')
        self.assertEqual({r['source_id']: r['returned'] for r in result['sources']}['big'], 57)

    def test_first_pages_across_tiers_precede_deep_paging_at_deadline(self):
        big = ['large%d' % i for i in range(3)]
        small = ['small%d' % i for i in range(20)]
        entries = sources(*big, *small)
        for entry in entries:
            entry.update(url='https://%s.example.test' % entry['id'], tier=0 if entry['id'] in big else 2)
        lock, calls = threading.Lock(), []
        elapsed = 0

        def transport(url):
            nonlocal elapsed
            name, page = url.split('/')
            page = int(page)
            with lock:
                calls.append((name, page))
                elapsed += 1 if page == 1 else 30
            return range(4 if name in big else 1)

        def clock():
            with lock:
                return elapsed

        def fetch(entry, ctx):
            name = entry['id']
            for page in range(1, ctx.pages + 1):
                rows = ctx.read('%s/%d' % (name, page))
                ctx.report['pages'] += 1
                ctx.report['fetched'] += len(rows)
                for n in rows:
                    yield job(name, 4 * (page - 1) + n)
                if name in small:
                    return
            ctx.report['truncated'] = True

        with patch.dict(REGISTRY):
            register(Provider('sweep-test', fetch))
            result = discover(dict(sweep=True, sweep_workers=4, sweep_deadline_seconds=30,
                                   keywords=['AI'], discovery_sources=entries), transport=transport, clock=clock)
        first_deep = next(i for i, (_, page) in enumerate(calls) if page > 1)
        self.assertEqual({name for name, _ in calls[:first_deep]}, set(big + small))
        returned = {j['platform_id'] for j in result['jobs']}
        self.assertTrue({n + '-0' for n in small} <= returned)
        self.assertTrue({name + '-' + str(n) for name in big for n in range(4)} <= returned)
        self.assertTrue(result['deadline_reached'])
        for r in result['sources']:
            self.assertTrue(r['first_page_read'])
            cut = r['source_id'] in big
            self.assertEqual((r['status'], r['truncated'], r['continuation_deadline']),
                             ('cancelled' if cut else 'ok', cut, cut))

    def test_keyword_first_pages_keep_all_matches_before_continuation(self):
        calls = []
        def fetch(entry, ctx):
            def fetch_page(term, page):
                ctx.read(term)
                calls.append((entry['id'], term, page))
                n = 10 * ctx.terms.index(term) + page
                return [n], 2
            return paged_jobs(ctx, fetch_page, lambda n: job(entry['id'], n), str, 1)

        result = run_discover(dict(keywords=['AI', 'backend'], sweep=True, discovery_sources=sources('a', 'b')),
                              Provider('sweep-test', fetch))
        self.assertEqual(calls[:4], [('a', 'AI', 1), ('a', 'backend', 1), ('b', 'AI', 1), ('b', 'backend', 1)])
        self.assertEqual([j['platform_id'] for j in result['jobs']],
                         ['a-1', 'a-11', 'b-1', 'b-11', 'a-2', 'a-12', 'b-2', 'b-12'])
        self.assertTrue(all(r['first_page_read'] and not r['truncated'] for r in result['sources']))
        self.assertEqual(result['requests'], len(calls))

    def test_filtered_first_page_still_gets_continuation(self):
        def fetch(entry, ctx):
            for page in range(1, min(2, ctx.pages) + 1):
                ctx.read(entry['id'])
                ctx.report['pages'] += 1
                ctx.report['fetched'] += 1
                if page == 2:
                    yield job(entry['id'], page)
            ctx.report['truncated'] = ctx.pages < 2

        result = run_discover(dict(sweep=True, discovery_sources=sources('a', 'b')), Provider('sweep-test', fetch))
        self.assertEqual([j['platform_id'] for j in result['jobs']], ['a-2', 'b-2'])
        for report in result['sources']:
            self.assertEqual((report['passes'], report['truncated'], report['continuation_deadline']), (2, False, False))

    def test_second_pass_ends_untruncated_when_source_runs_dry(self):
        result = run_discover(dict(sweep=True, sweep_max_jobs=60, discovery_sources=sources('big', 's1', 's2')),
                              provider(dict(big=30, s1=3, s2=3)))
        big = result['sources'][0]
        self.assertEqual((big['returned'], big['truncated'], big['status']), (30, False, 'ok'))

    def test_second_pass_shares_leftover_jobs_and_requests(self):
        limits, reads = [], dict(big=1000, rest=3, tiny=1)
        def hook(entry, ctx):
            limits.append((entry['name'], ctx.limit))
            for i in range(reads[entry['name']]):
                try: ctx.read('https://jobs.example.test/%s/%d' % (entry['name'], i))
                except SourceError: break
        result = run_discover(dict(sweep=True, sweep_requests=30, sweep_max_jobs=30, discovery_sources=sources('big', 'rest', 'tiny')),
                              provider(dict(big=40, rest=40, tiny=1), hook))
        # First pass: big 10 jobs / 10 requests, rest 10 / 3, tiny 1 / 1. Left: 9 jobs, 16 requests for two candidates.
        self.assertEqual(limits, [('big', 10), ('rest', 10), ('tiny', 10), ('big', 15), ('rest', 14)])
        by = {r['source_id']: r for r in result['sources']}
        self.assertEqual({k: (r['returned'], r['requests']) for k, r in by.items()}, dict(big=(15, 18), rest=(14, 6), tiny=(1, 1)))
        self.assertEqual((len(result['jobs']), result['requests']), (30, 25))

    def test_second_pass_never_runs_past_deadline(self):
        now, calls = [0.0], []
        def hook(entry, ctx):
            calls.append(entry['name'])
            ctx.read(entry['name'])
            ctx.report['pages'] += 1
            if entry['name'] == 's2': now[0] = 1000.0
        result = run_discover(dict(sweep=True, sweep_max_jobs=60, discovery_sources=sources('big', 's1', 's2')),
                              provider(dict(big=None, s1=3, s2=3), hook), clock=lambda: now[0])
        self.assertEqual(calls, ['big', 's1', 's2'])
        self.assertEqual(result['sources'][0]['returned'], 20)
        self.assertEqual(result['sources'][0]['passes'], 1)
        self.assertTrue(result['sources'][0]['continuation_deadline'])
        self.assertEqual(result['sources'][0]['status'], 'cancelled')
        self.assertTrue(result['deadline_reached'])

    def test_non_sweep_has_no_second_pass(self):
        calls = []
        result = run_discover(dict(max_jobs=60, discovery_sources=sources('big', 's1', 's2')),
                              provider(dict(big=None, s1=3, s2=3), lambda entry, ctx: calls.append((entry['name'], ctx.pages))))
        self.assertEqual(calls, [('big', 2), ('s1', 2), ('s2', 2)])
        self.assertEqual(result['sources'][0]['returned'], 20)

    def test_sweep_uses_sweep_max_pages(self):
        seen = []
        hook = lambda entry, ctx: seen.append(ctx.pages)
        run_discover(dict(sweep=True, max_pages=3, discovery_sources=sources('a')), provider(dict(a=1), hook))
        run_discover(dict(sweep=True, sweep_max_pages=7, discovery_sources=sources('a')), provider(dict(a=1), hook))
        run_discover(dict(sweep=True, sweep_max_pages=0, discovery_sources=sources('a')), provider(dict(a=1), hook))
        run_discover(dict(max_pages=3, sweep_max_pages=7, discovery_sources=sources('a')), provider(dict(a=1), hook))
        self.assertEqual(seen, [20, 7, 1, 3])

    def test_entry_checks_run_after_all_discovery(self):
        events = []
        def fake_check(item, read, renderer=None):
            events.append('check:' + item['platform_id']); return item
        with patch('hunt.search.entries.check_job', side_effect=fake_check):
            result = run_discover(dict(sweep=True, check_entries=True, sweep_prepare=3, discovery_sources=sources('a', 'b')),
                                  provider(dict(a=2, b=2), lambda entry, ctx: events.append('fetch:' + entry['name'])))
        self.assertEqual(events, ['fetch:a', 'fetch:b', 'check:a-0', 'check:a-1', 'check:b-0'])
        self.assertEqual(len(result['jobs']), 4)
        self.assertEqual(result['entry_check']['mode'], 'after_discovery')
        self.assertEqual(result['entry_check']['checked'], 3)

    def test_entry_checks_skip_jobs_already_known(self):
        checked = []
        def fake_check(item, read, renderer=None):
            checked.append(item['platform_id']); return item
        with patch('hunt.search.entries.check_job', side_effect=fake_check):
            run_discover(dict(sweep=True, check_entries=True, sweep_prepare=2, discovery_sources=sources('a')),
                         provider(dict(a=4)), known=lambda item: item['platform_id'] == 'a-0')
        self.assertEqual(checked, ['a-1', 'a-2'])

    def test_entry_checks_stop_at_deadline_and_keep_jobs(self):
        now = [0.0]
        def fake_check(item, read, renderer=None):
            now[0] += 400.0
            read('https://jobs.example.test/entry/' + item['platform_id'])
            item['raw'].setdefault('application_route', {})['entry_check'] = dict(status='job_page_seen')
            return item
        with patch('hunt.search.entries.check_job', side_effect=fake_check):
            result = run_discover(dict(sweep=True, check_entries=True, discovery_sources=sources('a')), provider(dict(a=5)), clock=lambda: now[0])
        self.assertEqual(len(result['jobs']), 5)
        self.assertEqual([bool(j['raw'].get('application_route')) for j in result['jobs']], [True, False, False, False, False])
        self.assertEqual((result['entry_check']['checked'], result['entry_check']['skipped']), (1, 4))
        self.assertEqual(result['entry_check']['elapsed_seconds'], 800.0)
        self.assertEqual(result['sources'][0]['entry_requests'], 1)
        self.assertEqual(result['sources'][0]['status'], 'ok')
        self.assertTrue(result['deadline_reached'])

    def test_non_sweep_entry_checks_stay_inline(self):
        events = []
        def fake_check(item, read, renderer=None):
            events.append('check:' + item['platform_id']); return item
        with patch('hunt.search.entries.check_job', side_effect=fake_check):
            result = run_discover(dict(check_entries=True, discovery_sources=sources('a', 'b')),
                                  provider(dict(a=1, b=1), lambda entry, ctx: events.append('fetch:' + entry['name'])))
        self.assertEqual(events, ['fetch:a', 'check:a-0', 'fetch:b', 'check:b-0'])
        self.assertEqual((result['entry_check']['mode'], result['entry_check']['checked']), ('inline', 2))

    def test_every_source_report_has_elapsed_seconds(self):
        now = [0.0]
        def hook(entry, ctx): now[0] += 2.5
        result = run_discover(dict(sweep=True, discovery_sources=sources('a', 'b')), provider(dict(a=1, b=1), hook), clock=lambda: now[0])
        self.assertEqual([r['elapsed_seconds'] for r in result['sources']], [2.5, 2.5])
        plain = run_discover(dict(discovery_sources=sources('a')), provider(dict(a=1)))
        self.assertIn('elapsed_seconds', plain['sources'][0])
        self.assertIn('elapsed_seconds', plain['entry_check'])

    def test_user_stop_is_not_deadline(self):
        result = run_discover(dict(sweep=True, discovery_sources=sources('a')), provider(dict(a=1)), should_continue=lambda: False)
        self.assertEqual(result['sources'][0]['status'], 'cancelled')
        self.assertFalse(result['deadline_reached'])


class SweepRunTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'app')

    def configure(self, **config):
        base = dict(keywords=['AI'], check_entries=False, discovery_sources=sources('a'))
        return self.store.action(dict(action='config', config=dict(base, **config)))

    def run_with(self, prov, **config):
        self.configure(**config)
        with patch.dict(REGISTRY):
            register(prov)
            return self.store.run()

    def test_run_prepares_only_first_n(self):
        result = self.run_with(provider(dict(a=5)), sweep=True, sweep_prepare=2, max_jobs=2)
        self.assertEqual(result['imported'], 5)
        self.assertEqual(result['prepared'], 2)
        self.assertEqual(result['discovered'], 5)
        jobs = self.store.state()['jobs']
        self.assertEqual(len(jobs), 5)
        self.assertEqual(sorted(j['status'] for j in jobs), ['new', 'new', 'new', 'review', 'review'])
        prepared = {j['platform_id'] for j in jobs if j['status'] == 'review'}
        self.assertEqual(prepared, {'a-0', 'a-1'})

    def test_prepare_slots_go_to_new_jobs_only(self):
        self.run_with(provider(dict(a=2)), sweep=True, sweep_prepare=2)
        checked = []
        def fake_check(item, read, renderer=None):
            checked.append(item['platform_id']); return item
        with patch('hunt.search.entries.check_job', side_effect=fake_check):
            result = self.run_with(provider(dict(a=5)), sweep=True, sweep_prepare=2, check_entries=True)
        self.assertEqual((result['imported'], result['duplicates'], result['prepared']), (5, 2, 2))
        status = {j['platform_id']: j['status'] for j in self.store.state()['jobs']}
        self.assertEqual([status['a-2'], status['a-3'], status['a-4']], ['review', 'review', 'new'])
        self.assertEqual(checked, ['a-2', 'a-3'])
        self.assertEqual((result['entry_check']['mode'], result['entry_check']['checked']), ('after_discovery', 2))

    def test_run_marks_deadline_partial(self):
        now = [0.0]
        def hook(entry, ctx):
            if entry['name'] == 'a': now[0] = 1000.0
        self.configure(sweep=True, discovery_sources=sources('a', 'b'))
        def timed(config, **kwargs):
            return discover(config, clock=lambda: now[0], **kwargs)
        with patch.dict(REGISTRY), patch('hunt.search.engine.discover', side_effect=timed):
            register(provider(dict(a=2, b=2), hook))
            result = self.store.run()
        self.assertEqual(result['status'], 'partial')
        self.assertTrue(result['deadline_reached'])
        self.assertEqual(result['imported'], 2)
        queued = result['sources'][1]
        self.assertEqual((queued['status'], queued['first_page_read'], queued['continuation_deadline']), ('cancelled', False, False))

    def test_run_caps_imports_at_sweep_max_jobs(self):
        with patch('hunt.search.engine.discover', side_effect=lambda config, **kw: dict(
                jobs=[job('a', n) for n in range(40)], sources=[], queries=['AI'], sweep=dict(max_jobs=25, prepare=0), deadline_reached=False)):
            result = self.run_with(provider(dict(a=1)), sweep=True, sweep_max_jobs=25, sweep_prepare=0)
        self.assertEqual(result['imported'], 25)

    def test_run_deadline_with_no_jobs_is_partial(self):
        ticks = []
        def clock():
            ticks.append(1)
            return 0.0 if len(ticks) == 1 else 1000.0
        self.configure(sweep=True)
        with patch.dict(REGISTRY), patch('hunt.search.engine.discover', side_effect=lambda config, **kw: discover(config, clock=clock, **kw)):
            register(provider(dict(a=1)))
            result = self.store.run()
        self.assertEqual(result['imported'], 0)
        self.assertTrue(result['deadline_reached'])
        self.assertEqual(result['status'], 'partial')
        self.assertTrue(result['truncated'])

    def test_non_sweep_run_unchanged(self):
        result = self.run_with(provider(dict(a=None)), max_jobs=3)
        self.assertEqual(result['prepared'], 3)
        self.assertEqual(result['imported'], 3)
        self.assertFalse(result.get('deadline_reached'))

    def test_sweep_config_validation(self):
        for bad in (dict(sweep='yes'), dict(sweep_max_jobs=0), dict(sweep_max_jobs=5001), dict(sweep_deadline_seconds=29),
                    dict(sweep_prepare=201), dict(sweep_requests='many'), dict(sweep_max_companies=True),
                    dict(sweep_max_pages=0), dict(sweep_max_pages=51)):
            with self.assertRaises(Error, msg=str(bad)):
                self.configure(**bad)
        state = self.configure(sweep=True, sweep_max_jobs=5000, sweep_prepare=0, sweep_max_pages=50)
        self.assertTrue(state['config']['sweep'])

    def test_discovery_sources_bounded(self):
        many = lambda n: [dict(kind='website', url='https://e%d.example.test/' % i) for i in range(n)]
        for bad in (dict(discovery_sources='x'), dict(discovery_sources=['x']), dict(discovery_sources=many(21)),
                    dict(sweep=True, sweep_max_companies=5, discovery_sources=many(6)), dict(sweep=True, discovery_sources=many(301))):
            with self.assertRaises(Error, msg=str(bad)):
                self.configure(**bad)
        self.assertEqual(len(self.configure(discovery_sources=many(20))['config']['discovery_sources']), 20)
        self.assertEqual(len(self.configure(sweep=True, discovery_sources=many(300))['config']['discovery_sources']), 300)
        self.assertEqual(len(self.configure(sweep=True, sweep_max_companies=1000, discovery_sources=many(1000))['config']['discovery_sources']), 1000)


if __name__ == '__main__':
    unittest.main()
