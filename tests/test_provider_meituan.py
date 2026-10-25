import json
import unittest
from pathlib import Path
from unittest import mock

from hunt.discovery import discover
from hunt.providers import REGISTRY, route

FIXTURES = Path(__file__).parent / 'fixtures' / 'providers'


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding='utf-8'))


def page_of(posts, total):
    return json.dumps(dict(code=0, data=dict(page=dict(totalCount=total), list=posts))).encode()


def post(n):
    return dict(jobUnionId=str(n), name='产品经理 ' + str(n), cityList=[dict(name='北京市')], department=[dict(name='到店事业群')],
                jobFamily='产品类', workYear='3-5年', jobDuty='负责产品规划 ' + str(n), jobRequirement='三年以上经验')


class Server:
    """Fake transport serving a board of `total` posts, paged by the nested page object in the POST body."""
    def __init__(self, total):
        self.total, self.calls = total, []

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        page = json.loads(kwargs['data'])['page']
        start = (page['pageNo'] - 1) * page['pageSize']
        return page_of([post(n) for n in range(start, min(start + page['pageSize'], self.total))], self.total)


def run(transport, **config):
    return discover(dict(dict(keywords=['产品经理'], sources=['meituan'], check_entries=False), **config), transport=transport)


class MeituanTests(unittest.TestCase):
    def setUp(self):
        for name in ('PAUSE', 'BACKOFF'):
            patch = mock.patch('hunt.providers.meituan.' + name, 0)
            patch.start(); self.addCleanup(patch.stop)

    def test_parses_page(self):
        raw = json.dumps(fixture('meituan-page1.json')).encode()
        result = run(lambda url, **kw: raw)
        report = result['sources'][0]
        self.assertEqual((report['status'], report['kind'], report['returned']), ('ok', 'meituan', 2))
        first, second = result['jobs']
        self.assertEqual(first['channel'], 'meituan')
        self.assertEqual(first['platform_id'], '1999900000001')
        self.assertEqual(first['title'], 'AI 产品经理（大模型）')
        self.assertEqual(first['url'], 'https://zhaopin.meituan.com/web/position/detail?jobUnionId=1999900000001')
        self.assertEqual(first['location'], '北京市/上海市')
        self.assertEqual(first['company'], '美团')
        self.assertIn('部门: 基础研发平台', first['jd'])
        self.assertIn('序列: 产品类', first['jd'])
        self.assertIn('经验: 3-5年', first['jd'])
        self.assertIn('负责大模型应用产品的规划与落地', first['jd'])
        self.assertIn('熟悉大模型应用场景', first['jd'])
        self.assertEqual(first['published_at'], '2026-06-23')
        self.assertEqual((second['platform_id'], second['location']), ('1999900000002', '深圳市'))
        self.assertNotIn('部门', second['jd'])
        self.assertEqual(second['published_at'], '2026-06-24')

    def test_body_uses_nested_page(self):
        server = Server(1)
        run(server)
        url, kwargs = server.calls[0]
        self.assertEqual((url, kwargs['method']), ('https://zhaopin.meituan.com/api/official/job/getJobList', 'POST'))
        body = json.loads(kwargs['data'])
        # A flat pageNo is silently ignored by the server, which then always answers page 1.
        self.assertEqual(body['page'], dict(pageNo=1, pageSize=100))
        self.assertNotIn('pageNo', body)
        self.assertEqual((body['keywords'], body['jobShareType'], body['jobType']), ('产品经理', '1', [dict(code='3', subCode=[])]))
        for key in ('cityList', 'department', 'jfJgList', 'typeCode', 'specialCode'): self.assertEqual(body[key], [], key)
        self.assertEqual({k.lower(): v for k, v in kwargs['headers'].items()}, {'content-type': 'application/json'})

    def test_pagination_advances_page_no(self):
        server = Server(250)
        report = run(server, max_pages=5, sweep=True)['sources'][0]
        self.assertEqual([json.loads(kw['data'])['page']['pageNo'] for _, kw in server.calls], [1, 2, 3])
        self.assertEqual((report['pages'], report['fetched'], report['returned'], report['truncated'], report['status']), (3, 250, 250, False, 'ok'))

    def test_page_cap_marks_truncated(self):
        server = Server(350)
        report = run(server, max_pages=2, max_jobs=500)['sources'][0]
        self.assertEqual((len(server.calls), report['fetched']), (2, 200))
        self.assertTrue(report['truncated'])

    def test_limit_marks_truncated(self):
        report = run(Server(30), max_jobs=10)['sources'][0]
        self.assertEqual((report['returned'], report['truncated']), (10, True))

    def test_each_keyword_queried_and_deduped_by_id(self):
        raw = json.dumps(fixture('meituan-page1.json')).encode()
        keys = []
        def transport(url, **kw):
            keys.append(json.loads(kw['data'])['keywords']); return raw
        result = run(transport, keywords=['产品经理', 'AI'], max_jobs=100)
        self.assertEqual(keys, ['产品经理', 'AI'])
        self.assertEqual(len(result['jobs']), 2)

    def test_empty_page_retried_before_stop(self):
        # Observed live: the board sporadically answers a mid-pagination request with an empty list.
        pages = [page_of([post(n) for n in range(100)], 150), page_of([], 150), page_of([], 150), page_of([post(n) for n in range(100, 150)], 150)]
        calls = []
        def transport(url, **kw):
            calls.append(json.loads(kw['data'])['page']['pageNo']); return pages[len(calls) - 1]
        result = run(transport, max_pages=5, sweep=True)
        report = result['sources'][0]
        self.assertEqual(calls, [1, 2, 2, 2])
        self.assertEqual((report['status'], len(result['jobs']), report['pages']), ('ok', 150, 2))

    def test_empty_page_after_retries_is_fetch_error_keeping_earlier_posts(self):
        pages = [page_of([post(n) for n in range(100)], 250)] + [page_of([], 250)] * 3
        calls = []
        def transport(url, **kw):
            calls.append(1); return pages[len(calls) - 1]
        result = run(transport, max_pages=5, sweep=True)
        report = result['sources'][0]
        self.assertEqual(len(calls), 4)
        self.assertEqual((report['status'], len(result['jobs'])), ('fetch_error', 100))
        self.assertIn('美团', report['error'])

    def test_empty_answer_with_zero_total_still_uses_known_total(self):
        pages = [page_of([post(n) for n in range(100)], 250)] + [page_of([], 0)] * 3
        calls = []
        def transport(url, **kw):
            calls.append(1); return pages[len(calls) - 1]
        report = run(transport, max_pages=5, sweep=True)['sources'][0]
        self.assertEqual((len(calls), report['status']), (4, 'fetch_error'))

    def test_zero_matches_is_empty_not_error(self):
        calls = []
        def transport(url, **kw):
            calls.append(1); return page_of([], 0)
        report = run(transport)['sources'][0]
        self.assertEqual((report['status'], report['fetched'], report['error']), ('empty', 0, None))
        self.assertEqual(len(calls), 3)

    def test_structure_change_is_parse_error(self):
        raw = json.dumps(fixture('meituan-changed.json')).encode()
        report = run(lambda url, **kw: raw)['sources'][0]
        self.assertEqual(report['status'], 'parse_error')
        self.assertIn('美团', report['error'])

    def test_non_json_is_parse_error(self):
        report = run(lambda url, **kw: b'<html>maintenance</html>')['sources'][0]
        self.assertEqual(report['status'], 'parse_error')

    def test_bad_post_is_reported_and_rest_kept(self):
        bad_rows = [dict(name='产品经理', jobDuty='负责产品'), 'oops', dict(jobUnionId='7', name=''), dict(jobUnionId='8', jobDuty='无名称'), None]
        for bad in bad_rows:
            pages = [page_of([post(1), bad, post(2)], 150), page_of([post(3)], 150)]
            urls = []
            def transport(url, **kw):
                urls.append(url); return pages[len(urls) - 1]
            result = run(transport, max_pages=2, max_jobs=100)
            report = result['sources'][0]
            self.assertEqual([j['platform_id'] for j in result['jobs']], ['1', '2', '3'], bad)
            self.assertEqual((report['status'], len(urls), len(report['detail_errors'])), ('parse_error', 2, 1), bad)
            self.assertIn('1 个岗位详情无法解析', report['error'])

    def test_bad_post_identity_recorded(self):
        raw = page_of([post(1), dict(jobUnionId='7', name='')], 2)
        self.assertEqual(run(lambda url, **kw: raw)['sources'][0]['detail_errors'][0]['platform_id'], '7')

    def test_unencodable_id_is_skipped(self):
        raw = page_of([post(1), dict(post(2), jobUnionId='\ud800')], 2)
        result = run(lambda url, **kw: raw)
        self.assertEqual([j['platform_id'] for j in result['jobs']], ['1'])
        self.assertEqual(len(result['sources'][0]['detail_errors']), 1)

    def test_missing_optional_fields_ok(self):
        raw = page_of([dict(jobUnionId='5', name='产品经理', cityList=None, department=None, jobDuty='负责产品', refreshTime=None, firstPostTime=None)], 1)
        job = run(lambda url, **kw: raw)['jobs'][0]
        self.assertEqual((job['jd'], job['location'], job['published_at']), ('负责产品', None, None))

    def test_total_accepts_digit_string(self):
        raw = json.dumps(dict(data=dict(page=dict(totalCount='2'), list=[post(1), post(2)]))).encode()
        report = run(lambda url, **kw: raw)['sources'][0]
        self.assertEqual((report['status'], report['returned']), ('ok', 2))

    def test_total_of_other_types_is_parse_error(self):
        for total in (None, 'many', '', 2.5, True, [2]):
            raw = json.dumps(dict(data=dict(page=dict(totalCount=total), list=[post(1)]))).encode()
            self.assertEqual(run(lambda url, **kw: raw)['sources'][0]['status'], 'parse_error', total)

    def test_detect(self):
        provider = REGISTRY['meituan']
        hit = provider.detect(dict(careers_url='https://zhaopin.meituan.com/web/social'))
        self.assertEqual(hit['kind'], 'meituan')
        self.assertIs(route(dict(careers_url='https://zhaopin.meituan.com/web/social')), provider)
        for url in ('https://zhaopin.example.com/web/social', 'https://zhaopin.meituan.com.evil.test/web/social',
                    'http://zhaopin.meituan.com/web/social', 'https://evil.test/zhaopin.meituan.com'):
            self.assertIsNone(provider.detect(dict(careers_url=url)), url)
        self.assertIsNone(provider.detect(dict()))

    def test_detected_entry_runs_through_discover(self):
        raw = json.dumps(fixture('meituan-page1.json')).encode()
        result = discover(dict(keywords=['产品经理'], check_entries=False,
                               discovery_sources=[dict(careers_url='https://zhaopin.meituan.com/web/social', company='美团外卖')]),
                          transport=lambda url, **kw: raw)
        report = result['sources'][0]
        self.assertEqual((report['kind'], report['status'], report['returned']), ('meituan', 'ok', 2))
        self.assertEqual(result['jobs'][0]['company'], '美团外卖')


if __name__ == '__main__':
    unittest.main()
