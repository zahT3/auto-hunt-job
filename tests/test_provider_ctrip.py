import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from hunt.app.store import Store
from hunt.search.engine import discover
from hunt.search.parse import public_url
from hunt.search.sources import companies, route


FIXTURE = Path(__file__).parent / 'fixtures/providers/ctrip-page1.json'
DETAIL = 'https://job.ctrip.com/#/experienced/job-detail/'


def page(rows, total):
    return json.dumps(dict(retCode='201', retValue=dict(total=total, recruitJobAdList=rows))).encode()


def run(transport, **config):
    return discover(dict(dict(keywords=['产品经理'], sources=['ctrip'], check_entries=False), **config),
                    transport=transport)


class CtripTests(unittest.TestCase):
    def test_seed_routes_to_reader(self):
        chosen = {s['id']: s for s in companies.select(['产品经理'], 300)}
        provider = route(chosen['ctrip'])
        self.assertEqual(provider.id, 'ctrip')
        self.assertIs(route(dict(careers_url='https://job.ctrip.com/')), provider)
        self.assertIsNone(provider.detect(dict(url='https://job.ctrip.com.example.test/')))
        self.assertNotIn('zhaopin-kuaishou-cn-recruit-e', chosen)

    def test_recorded_job_survives_import(self):
        response = json.loads(FIXTURE.read_bytes())
        response['retValue']['recruitJobAdList'][0]['hrUserName'] = 'synthetic-staff'
        transport = Mock(return_value=json.dumps(response).encode())
        result = run(transport)
        self.assertEqual(result['sources'][0]['status'], 'ok')
        job, = result['jobs']
        self.assertEqual((job['platform_id'], job['company'], job['title'], job['location'], job['published_at']),
                         ('MJ037863', '携程', '后台产品经理(MJ037863)', 'Shanghai', '2026-11-16'))
        self.assertIn('负责邮轮相关产品', job['jd'])
        self.assertNotIn('<li>', job['jd'])
        self.assertNotIn('synthetic-staff', json.dumps(job))
        with tempfile.TemporaryDirectory() as tmp:
            stored, duplicate = Store(Path(tmp) / 'app').import_job(job)
            self.assertFalse(duplicate)
            self.assertEqual((stored['url'], stored['application_url']), (DETAIL + 'MJ037863',) * 2)

    def test_fragment_only_keeps_official_social_job_identity(self):
        link = DETAIL + 'MJ037863'
        self.assertEqual(public_url(link + '?sourceTag=example'), link)
        for url in (link.replace('job.ctrip.com', 'example.test'), link.replace('/experienced/', '/campus/'),
                    DETAIL, link + '/apply', link.replace('/#', '/unrelated#')):
            self.assertNotIn('#', public_url(url), url)

    @patch('hunt.search.sources.ctrip.PAUSE', 0)
    def test_pagination_keywords_and_budget(self):
        row = json.loads(FIXTURE.read_bytes())['retValue']['recruitJobAdList'][0]
        calls = []

        def board(url, **kwargs):
            self.assertEqual(url, 'https://job.ctrip.com/api/hrrecruit/getJobAd')
            self.assertEqual((kwargs['method'], kwargs['headers']), ('POST', {'Content-Type': 'application/json'}))
            body = json.loads(kwargs['data'])
            self.assertEqual(body['condition']['category'], 1)
            self.assertEqual(body['pager']['size'], '20')
            term, index = body['condition']['keyword'], body['pager']['index']
            calls.append((term, index))
            indexes = range(20) if index == '1' else [20]
            return page([dict(row, fromId=f'MJ{i}') for i in indexes], 21)

        result = run(board, keywords=['产品经理', '产品负责人'])
        self.assertEqual(calls, [(term, i) for term in ('产品经理', '产品负责人') for i in ('1', '2')])
        self.assertEqual(len(result['jobs']), 21)
        self.assertFalse(result['sources'][0]['truncated'])
        calls.clear()
        result = run(board, discovery_requests=1)
        self.assertEqual((len(calls), len(result['jobs']), result['sources'][0]['status']), (1, 20, 'budget_exhausted'))
        self.assertTrue(result['sources'][0]['truncated'])

    def test_empty_error_and_malformed_responses(self):
        for raw, status in ((page([], 0), 'empty'), (b'{"retCode":"403"}', 'fetch_error'),
                            (b'{"retCode":"201","retValue":{"total":0}}', 'parse_error')):
            self.assertEqual(run(Mock(return_value=raw))['sources'][0]['status'], status)

    def test_bad_detail_id_skipped_without_losing_valid_result(self):
        row = json.loads(FIXTURE.read_bytes())['retValue']['recruitJobAdList'][0]
        result = run(Mock(return_value=page([dict(row, fromId='bad/path'), row], 2)))
        self.assertEqual(result['sources'][0]['status'], 'parse_error')
        self.assertEqual([j['platform_id'] for j in result['jobs']], ['MJ037863'])
