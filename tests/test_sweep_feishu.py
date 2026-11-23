"""Offline replay of a multi-keyword board competing for continuation shares."""
import json
import unittest
from unittest.mock import patch

from hunt.search.engine import discover
from hunt.search.sources import Provider, REGISTRY, register


def board_sweep(max_jobs=1000, requests=3000, deadline_page=None, max_pages=20, stop_page=None, workers=1):
    calls = []
    elapsed = [0]
    board = dict(id='board', kind='feishu', url='https://jobs.bytedance.com', broad=False)
    peers = [dict(id=str(i), kind='peer') for i in range(19)]

    def fetch_peer(source, ctx):
        if int(source['id']) < 5:
            for i in range(16):
                yield dict(channel='peer', platform_id=source['id'] + '-' + str(i))
            ctx.report['truncated'] = ctx.pages == 1

    def transport(url, *, data, **kwargs):
        body = json.loads(data)
        term, offset = body['keyword'], body['offset']
        calls.append((term, offset))
        if len(calls) == deadline_page:
            elapsed[0] = 600
        # The two keyword searches overlap. Their forty pages contain 484 different jobs.
        start = offset + (2000 if term == 'Backend' else 0)
        page = start // 100
        if page < 2:
            ids = range(start, start + 100)
        else:
            # Spread 284 later matches across all 38 pages, including the very last one.
            before, after = (page - 2) * 284 // 38, (page - 1) * 284 // 38
            ids = [*range(200 + before, 200 + after), *range(100 - (after - before))]
        rows = [dict(id=str(i), title='Engineer', description='Build tools for engineers') for i in ids]
        return json.dumps(dict(code=0, data=dict(count=2000, job_post_list=rows))).encode()

    with patch.dict(REGISTRY), patch('hunt.search.sources.feishu.PAUSE', 0):
        register(Provider('peer', fetch_peer))
        result = discover(dict(sweep=True, sweep_workers=workers, keywords=['Python', 'Backend'], sweep_max_jobs=max_jobs,
                               sweep_requests=requests, sweep_max_pages=max_pages, discovery_sources=[board, *peers]),
                          transport=transport, clock=lambda: elapsed[0],
                          should_continue=lambda: stop_page is None or len(calls) < stop_page)
    return result, calls


class FeishuContinuationTests(unittest.TestCase):
    def test_reuse_unspent_shares_and_resume_partial_pages(self):
        for workers in (1, 4):
            with self.subTest(workers=workers):
                result, calls = board_sweep(workers=workers)
                board = result['sources'][0]
                self.assertEqual((board['requests'], board['returned']), (40, 484))
                self.assertCountEqual(calls, [(term, offset) for term in ('Python', 'Backend')
                                              for offset in range(0, 2000, 100)])
                self.assertEqual((board['pages'], board['fetched'], board['truncated']), (40, 4000, False))
                self.assertIsNone(board['truncation_reason'])
                self.assertEqual({j['platform_id'] for j in result['jobs'] if j['channel'] == 'feishu'},
                                 {str(i) for i in range(484)})

    def test_reports_the_bound_that_stopped_the_board(self):
        cases = [
            (dict(max_jobs=250), 'job_limit', 170),
            (dict(requests=3), 'request_limit', 207),
            (dict(requests=1), 'request_limit', 100),
            (dict(deadline_page=3), 'deadline', 207),
            (dict(stop_page=3), 'cancelled', 207),
            (dict(max_pages=1), 'page_limit', 108),
        ]
        for config, reason, kept in cases:
            with self.subTest(config=config):
                result, calls = board_sweep(**config)
                board = result['sources'][0]
                self.assertEqual(board['truncation_reason'], reason)
                self.assertTrue(board['truncated'] and board['first_page_read'])
                self.assertEqual(board['returned'], kept)
                self.assertEqual(board['continuation_deadline'], reason == 'deadline')
                self.assertEqual(board['status'] == 'cancelled', reason in ('deadline', 'cancelled'))
                self.assertEqual(board['requests'], len(calls))
