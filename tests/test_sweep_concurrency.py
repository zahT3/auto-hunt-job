"""A sweep scans several sources at once: same results as one worker, one source per host, a shared request budget."""
import threading
import time
import unittest
from collections import defaultdict
from unittest.mock import patch
from urllib.parse import urlsplit

from hunt.app.config import validate_config
from hunt.base import Error
from hunt.search.engine import discover, host_key
from hunt.search.parse import normalize
from hunt.search.sources import Provider, REGISTRY, register


def job(source, n):
    return normalize('conc-test', source + '-' + str(n), 'AI Engineer ' + str(n), 'Build AI systems',
                     'https://jobs.example.test/' + source + '/' + str(n), company=source, status='open')


class Fixture:
    """Fake transport that records when each host was busy and optionally sleeps."""
    def __init__(self, delay=0.0):
        self.delay, self.lock, self.spans, self.calls = delay, threading.Lock(), defaultdict(list), 0
    def __call__(self, url, **kwargs):
        host = urlsplit(url).netloc
        began = time.monotonic()
        if self.delay: time.sleep(self.delay)
        with self.lock:
            self.calls += 1
            self.spans[host].append((began, time.monotonic()))
        return b'{}'
    def overlaps(self):
        return [h for h, spans in self.spans.items() for a, b in zip(sorted(spans), sorted(spans)[1:]) if b[0] < a[1] - 1e-3]


def provider(counts, requests=1):
    def fetch(entry, ctx):
        for _ in range(requests): ctx.read(entry['url'])
        for n in range(min(counts.get(entry['name'], 0), ctx.limit)): yield job(entry['name'], n)
    return Provider(id='conc-test', fetch=fetch)


def sources(*names, shared_host=False):
    return [dict(id=n, kind='conc-test', name=n, url='https://%s.example.test/jobs' % ('same' if shared_host else n)) for n in names]


def run(config, transport, prov, **kwargs):
    with patch.dict(REGISTRY):
        register(prov)
        return discover(dict(dict(keywords=['AI'], check_entries=False, sweep=True), **config), transport=transport, **kwargs)


class ConcurrentSweepTests(unittest.TestCase):
    names = ['s%d' % i for i in range(12)]

    def test_workers_default_and_range(self):
        self.assertEqual(run(dict(discovery_sources=sources('a')), Fixture(), provider({}))['sweep']['workers'], 4)
        self.assertEqual(run(dict(sweep_workers=99, discovery_sources=sources('a')), Fixture(), provider({}))['sweep']['workers'], 8)
        self.assertEqual(validate_config(dict(sweep_workers=8))['sweep_workers'], 8)
        for bad in (0, 9, '4', True):
            with self.assertRaises(Error): validate_config(dict(sweep_workers=bad))

    def test_parallel_matches_serial(self):
        counts = {n: i % 4 for i, n in enumerate(self.names)}
        def go(workers):
            r = run(dict(sweep_workers=workers, discovery_sources=sources(*self.names)), Fixture(0.01), provider(counts, requests=2))
            for s in r['sources']: s.pop('checked_at'); s.pop('elapsed_seconds')
            return [j['platform_id'] for j in r['jobs']], r['sources'], r['requests']
        self.assertEqual(go(1), go(4))
        self.assertEqual(go(1), go(8))

    def test_reports_follow_source_order_and_progress_is_complete(self):
        # earlier sources are slower, so they finish last
        def transport(url, **kw):
            time.sleep(0.2 - 0.01 * int(urlsplit(url).netloc.split('.')[0][1:])); return b'{}'
        seen = []
        r = run(dict(sweep_workers=4, discovery_sources=sources(*self.names[:8])), transport, provider({}), on_source=seen.append)
        self.assertEqual([s['source_id'] for s in r['sources']], self.names[:8])
        self.assertEqual(sorted(s['source_id'] for s in seen), sorted(self.names[:8]))
        self.assertNotEqual([s['source_id'] for s in seen], self.names[:8])

    def test_same_host_sources_never_overlap(self):
        fx = Fixture(0.05)
        run(dict(sweep_workers=4, discovery_sources=sources(*self.names[:6], shared_host=True)), fx, provider({}, requests=2))
        self.assertEqual(fx.calls, 12)
        self.assertEqual(fx.overlaps(), [])
        starts = sorted(a for a, b in fx.spans['same.example.test'])
        self.assertGreater(starts[-1] - starts[0], 0.05 * 10)  # strictly serial: 12 x 0.05 s

    def test_different_hosts_do_overlap(self):
        fx = Fixture(0.1)
        run(dict(sweep_workers=4, discovery_sources=sources(*self.names[:4])), fx, provider({}))
        starts = [a for spans in fx.spans.values() for a, b in spans]
        self.assertLess(max(starts) - min(starts), 0.08)

    def test_blocked_host_does_not_hold_up_other_hosts(self):
        fx = Fixture(0.1)
        mixed = sources('a1', 'a2', 'a3', shared_host=True) + sources('b1', 'b2')
        t = time.monotonic()
        run(dict(sweep_workers=2, discovery_sources=mixed), fx, provider({}))
        # a1..a3 serial = 0.3 s; b1, b2 run beside them instead of waiting behind
        self.assertLess(time.monotonic() - t, 0.4)

    def test_budget_never_exceeded(self):
        fx = Fixture(0.002)
        r = run(dict(sweep_workers=8, sweep_requests=25, discovery_sources=sources(*self.names)), fx, provider({n: 2 for n in self.names}, requests=5))
        self.assertLessEqual(fx.calls, 25)
        self.assertEqual(r['requests'], fx.calls)
        self.assertEqual(sum(s['requests'] for s in r['sources']), r['requests'])
        self.assertTrue(any(s['status'] == 'budget_exhausted' for s in r['sources']))

    def test_job_limit_holds_under_concurrency(self):
        r = run(dict(sweep_workers=8, sweep_max_jobs=7, discovery_sources=sources(*self.names)), Fixture(0.002), provider({n: 5 for n in self.names}))
        self.assertLessEqual(len(r['jobs']), 7)
        self.assertEqual(len(r['jobs']), sum(s['returned'] for s in r['sources']))

    def test_deadline_cancels_remaining_sources(self):
        clock = [0.0]
        fx = Fixture(0.05)
        def ticking(url, **kw):
            clock[0] += 400; return fx(url)  # each request moves the fake clock 400 s
        r = run(dict(sweep_workers=2, sweep_deadline_seconds=600, discovery_sources=sources(*self.names)), ticking, provider({n: 1 for n in self.names}),
                clock=lambda: clock[0])
        statuses = [s['status'] for s in r['sources']]
        self.assertTrue(r['deadline_reached'])
        self.assertIn('cancelled', statuses)
        self.assertEqual(len(statuses), 12)
        self.assertLess(fx.calls, 12)

    def test_wall_time_drops_with_workers(self):
        def timed(workers):
            t = time.monotonic()
            run(dict(sweep_workers=workers, discovery_sources=sources(*self.names[:8])), Fixture(0.2), provider({}))
            return time.monotonic() - t
        serial, four = timed(1), timed(4)
        self.assertGreater(serial, 1.5)
        self.assertLess(four, serial / 2.5)

    def test_second_pass_runs_in_parallel_and_matches_serial(self):
        def fetch(entry, ctx):
            ctx.read(entry['url'])
            for n in range(min(ctx.limit, 10) if entry['name'] in ('s0', 's1', 's2') else 1): yield job(entry['name'], n)
            if entry['name'] in ('s0', 's1', 's2'): ctx.report['truncated'] = True
        def go(workers):
            r = run(dict(sweep_workers=workers, discovery_sources=sources(*self.names[:6])), Fixture(0.01), Provider(id='conc-test', fetch=fetch))
            for s in r['sources']: s.pop('checked_at'); s.pop('elapsed_seconds')
            return [j['platform_id'] for j in r['jobs']], r['sources']
        one, four = go(1), go(4)
        self.assertEqual(one, four)
        self.assertEqual([s['passes'] for s in four[1]], [2, 2, 2, 1, 1, 1])

    def test_host_key(self):
        self.assertEqual(host_key(dict(kind='x', url='https://A.example.com/p')), 'a.example.com')
        self.assertNotEqual(host_key(dict(kind='mokahr', url='https://app.mokahr.com/social-recruitment/a/1')),
                            host_key(dict(kind='mokahr', url='https://app.mokahr.com/social-recruitment/b/1')))
        self.assertNotEqual(host_key(dict(kind='greenhouse', board='a')), host_key(dict(kind='greenhouse', board='b')))
        self.assertEqual(host_key(dict(kind='boss', mode='browser')), host_key(dict(kind='liepin', mode='browser')))


if __name__ == '__main__':
    unittest.main()
