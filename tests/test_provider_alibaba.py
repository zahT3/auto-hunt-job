import json
import unittest
from pathlib import Path
from unittest import mock

from hunt import network
from hunt.discovery import discover
from hunt.providers import REGISTRY, route

FIXTURES = Path(__file__).parent / 'fixtures' / 'providers'


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding='utf-8'))


def page_of(posts, total):
    return json.dumps(dict(success=True, content=dict(totalCount=total, datas=posts))).encode()


def post(n):
    return dict(id=n, name='产品经理 ' + str(n), workLocations=['杭州'], categories=['产品类'],
                experience=dict(**{'from': 3, 'to': None}), description='负责产品规划 ' + str(n), requirement='三年以上经验')


class Server:
    """Fake transport serving a board of `total` posts, paged by pageIndex/pageSize in the POST body."""
    def __init__(self, total):
        self.total, self.calls = total, []

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        body = json.loads(kwargs['data'])
        start = (body['pageIndex'] - 1) * body['pageSize']
        return page_of([post(n) for n in range(start, min(start + body['pageSize'], self.total))], self.total)


def run(transport, **config):
    return discover(dict(dict(keywords=['产品经理'], sources=['alibaba'], check_entries=False), **config), transport=transport)


class AlibabaTests(unittest.TestCase):
    def setUp(self):
        patch = mock.patch('hunt.providers.alibaba.PAUSE', 0)
        patch.start(); self.addCleanup(patch.stop)

    def test_parses_page(self):
        raw = json.dumps(fixture('alibaba-page1.json')).encode()
        result = run(lambda url, **kw: raw)
        report = result['sources'][0]
        self.assertEqual((report['status'], report['kind'], report['returned']), ('ok', 'alibaba', 2))
        first, second = result['jobs']
        self.assertEqual(first['channel'], 'alibaba')
        self.assertEqual(first['platform_id'], '1999900000001')
        self.assertEqual(first['title'], 'AI 产品经理（通义）')
        self.assertEqual(first['url'], 'https://talent.alibaba.com/off-campus/position-detail?positionId=1999900000001')
        self.assertEqual(first['location'], '杭州/北京')
        self.assertEqual(first['company'], '阿里巴巴')
        self.assertIn('类别: 产品类/AI产品', first['jd'])
        self.assertIn('经验: 3-5年', first['jd'])
        self.assertIn('负责大模型应用产品的规划与落地', first['jd'])
        self.assertIn('熟悉大模型应用场景', first['jd'])
        self.assertEqual(first['published_at'], '2026-06-23')
        self.assertEqual((second['platform_id'], second['location']), ('1999900000002', '上海'))
        self.assertIn('经验: 5年以上', second['jd'])
        self.assertNotIn('类别', second['jd'])
        self.assertEqual(second['published_at'], '2026-06-24')

    def test_request_shape(self):
        server = Server(1)
        run(server)
        url, kwargs = server.calls[0]
        self.assertEqual(url, 'https://talent.alibaba.com/position/search')
        self.assertEqual(kwargs['method'], 'POST')
        body = json.loads(kwargs['data'])
        self.assertEqual((body['key'], body['pageIndex'], body['pageSize'], body['channel'], body['language']),
                         ('产品经理', 1, 100, 'group_official_site', 'zh'))
        self.assertEqual((body['deptCodes'], body['batchId'], body['categories'], body['regions'], body['subCategories']), ([], '', '', '', ''))
        headers = {k.lower(): v for k, v in kwargs['headers'].items()}
        self.assertEqual(headers['content-type'], 'application/json')
        token = headers['x-xsrf-token']
        self.assertRegex(token, r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
        self.assertEqual(headers['cookie'], 'XSRF-TOKEN=' + token)

    def test_one_token_per_run(self):
        server = Server(150)
        run(server, max_pages=5, max_jobs=100)
        run(server, max_pages=5, max_jobs=100)
        tokens = [kw['headers']['x-xsrf-token'] for _, kw in server.calls]
        self.assertEqual(len(tokens), 4)
        self.assertEqual((tokens[0], tokens[2]), (tokens[1], tokens[3]))
        self.assertNotEqual(tokens[0], tokens[2])

    def test_pagination_stops_at_total(self):
        server = Server(150)
        result = run(server, max_pages=5, max_jobs=100)
        self.assertEqual(len(server.calls), 2)
        report = result['sources'][0]
        self.assertEqual((report['pages'], report['fetched'], report['returned'], report['truncated']), (2, 150, 100, True))

    def test_pagination_complete_when_limit_allows(self):
        server = Server(150)
        report = run(server, max_pages=5, sweep=True)['sources'][0]
        self.assertEqual((len(server.calls), report['returned'], report['truncated'], report['status']), (2, 150, False, 'ok'))

    def test_page_cap_marks_truncated(self):
        server = Server(350)
        report = run(server, max_pages=2, max_jobs=100)['sources'][0]
        self.assertEqual((len(server.calls), report['pages'], report['fetched']), (2, 2, 200))
        self.assertTrue(report['truncated'])

    def test_limit_marks_truncated(self):
        report = run(Server(30), max_jobs=10)['sources'][0]
        self.assertEqual((report['returned'], report['truncated']), (10, True))

    def test_each_keyword_queried_and_deduped_by_id(self):
        raw = json.dumps(fixture('alibaba-page1.json')).encode()
        keys = []
        def transport(url, **kw):
            keys.append(json.loads(kw['data'])['key']); return raw
        result = run(transport, keywords=['产品经理', 'AI'], max_jobs=100)
        self.assertEqual(keys, ['产品经理', 'AI'])
        self.assertEqual(len(result['jobs']), 2)
        self.assertEqual(result['sources'][0]['fetched'], 4)

    def test_zero_matches_is_empty_not_error(self):
        report = run(lambda url, **kw: page_of([], 0))['sources'][0]
        self.assertEqual((report['status'], report['fetched'], report['error']), ('empty', 0, None))

    def test_api_error_reported(self):
        raw = json.dumps(dict(success=False, errorCode='500', errorMsg='系统繁忙', content=None)).encode()
        report = run(lambda url, **kw: raw)['sources'][0]
        self.assertEqual(report['status'], 'fetch_error')
        self.assertIn('系统繁忙', report['error'])
        self.assertEqual((report['fetched'], report['returned']), (0, 0))

    def test_api_error_without_message_uses_code(self):
        raw = json.dumps(dict(success=False, errorCode='E42', errorMsg=None)).encode()
        report = run(lambda url, **kw: raw)['sources'][0]
        self.assertEqual(report['status'], 'fetch_error')
        self.assertIn('E42', report['error'])

    def test_api_error_midway_keeps_earlier_posts(self):
        pages = [page_of([post(n) for n in range(100)], 250), json.dumps(dict(success=False, errorMsg='限流')).encode()]
        calls = []
        def transport(url, **kw):
            calls.append(url); return pages[len(calls) - 1]
        result = run(transport, max_pages=5, max_jobs=500)
        report = result['sources'][0]
        self.assertEqual((report['status'], len(result['jobs'])), ('fetch_error', 100))
        self.assertIn('限流', report['error'])

    def test_structure_change_is_parse_error(self):
        raw = json.dumps(fixture('alibaba-changed.json')).encode()
        report = run(lambda url, **kw: raw)['sources'][0]
        self.assertEqual(report['status'], 'parse_error')
        self.assertIn('阿里', report['error'])

    def test_non_json_is_parse_error(self):
        report = run(lambda url, **kw: b'<html>maintenance</html>')['sources'][0]
        self.assertEqual(report['status'], 'parse_error')

    def test_bad_post_is_reported_and_rest_kept(self):
        bad_rows = [dict(name='产品经理', description='负责产品'), 'oops', dict(id=7, name='空岗位'), dict(id=8, description='无名称'), None]
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
            self.assertEqual(report['detail_errors'][0]['status'], 'parse_error')

    def test_bad_post_identity_recorded(self):
        raw = page_of([post(1), dict(id=7, name='空岗位')], 2)
        error = run(lambda url, **kw: raw)['sources'][0]['detail_errors'][0]
        self.assertEqual(error['platform_id'], '7')

    def test_bad_post_errors_capped_with_true_count(self):
        raw = page_of([post(1)] + [dict(id=100 + n, name='空') for n in range(25)], 26)
        result = run(lambda url, **kw: raw)
        report = result['sources'][0]
        self.assertEqual((len(result['jobs']), len(report['detail_errors']), report['detail_error_count']), (1, 20, 25))
        self.assertIn('25 个岗位详情无法解析', report['error'])

    def test_unencodable_id_is_skipped(self):
        raw = page_of([post(1), dict(post(2), id='\ud800')], 2)
        result = run(lambda url, **kw: raw)
        self.assertEqual([j['platform_id'] for j in result['jobs']], ['1'])
        self.assertEqual(len(result['sources'][0]['detail_errors']), 1)

    def test_title_with_ampersand_kept(self):
        # Real post (2026-10): the title 'M&T事业部-...' was dropped as empty by the HTML text extractor.
        raw = page_of([dict(post(1), name='M&T事业部-导购产品经理'), dict(post(2), name='Q&A')], 2)
        result = run(lambda url, **kw: raw)
        self.assertEqual([j['title'] for j in result['jobs']], ['M&T事业部-导购产品经理', 'Q&A'])

    def test_null_categories_and_missing_fields_ok(self):
        raw = page_of([dict(id=5, name='产品经理', categories=None, workLocations=None, experience=None, description='负责产品', requirement=None,
                            publishTime=None, modifyTime=None)], 1)
        job = run(lambda url, **kw: raw)['jobs'][0]
        self.assertEqual((job['jd'], job['location'], job['published_at']), ('负责产品', None, None))

    def test_total_accepts_digit_string(self):
        raw = json.dumps(dict(success=True, content=dict(totalCount='2', datas=[post(1), post(2)]))).encode()
        report = run(lambda url, **kw: raw)['sources'][0]
        self.assertEqual((report['status'], report['returned']), ('ok', 2))

    def test_total_of_other_types_is_parse_error(self):
        for total in (None, 'many', '', 2.5, True, [2]):
            raw = json.dumps(dict(success=True, content=dict(totalCount=total, datas=[post(1)]))).encode()
            self.assertEqual(run(lambda url, **kw: raw)['sources'][0]['status'], 'parse_error', total)

    def test_detect(self):
        provider = REGISTRY['alibaba']
        hit = provider.detect(dict(careers_url='https://talent.alibaba.com/off-campus/position-list'))
        self.assertEqual(hit['kind'], 'alibaba')
        self.assertIs(route(dict(careers_url='https://talent.alibaba.com/off-campus/position-list')), provider)
        for url in ('https://talent.example.com/off-campus', 'https://talent.alibaba.com.evil.test/off-campus',
                    'http://talent.alibaba.com/off-campus', 'https://evil.test/talent.alibaba.com'):
            self.assertIsNone(provider.detect(dict(careers_url=url)), url)
        self.assertIsNone(provider.detect(dict()))

    def test_detected_entry_runs_through_discover(self):
        raw = json.dumps(fixture('alibaba-page1.json')).encode()
        result = discover(dict(keywords=['产品经理'], check_entries=False,
                               discovery_sources=[dict(careers_url='https://talent.alibaba.com/off-campus/position-list', company='阿里云')]),
                          transport=lambda url, **kw: raw)
        report = result['sources'][0]
        self.assertEqual((report['kind'], report['status'], report['returned']), ('alibaba', 'ok', 2))
        self.assertEqual(result['jobs'][0]['company'], '阿里云')


class CookieGuardTests(unittest.TestCase):
    """network.fetch still refuses cookies, except the self-minted double-submit XSRF token."""
    def test_arbitrary_cookie_refused(self):
        for value in ('session=abc', 'XSRF-TOKEN=abc', 'XSRF-TOKEN=' + 'a' * 36 + '; session=abc',
                      'XSRF-TOKEN=00000000-0000-4000-8000-000000000000\r\nX: y'):
            with self.assertRaises(network.FetchError, msg=value):
                network.fetch('https://talent.alibaba.com/position/search', method='POST', data=b'{}', headers={'Cookie': value})

    def test_xsrf_token_cookie_passes_header_check(self):
        class Reached(Exception): pass
        with mock.patch('hunt.network.validate_url', side_effect=Reached):
            with self.assertRaises(Reached):
                network.fetch('https://talent.alibaba.com/position/search', method='POST', data=b'{}',
                              headers={'Cookie': 'XSRF-TOKEN=00000000-0000-4000-8000-000000000000'})

    def test_other_guarded_headers_still_refused(self):
        for name in ('Authorization', 'Host', 'Proxy-Authorization'):
            with self.assertRaises(network.FetchError, msg=name):
                network.fetch('https://talent.alibaba.com/', headers={name: 'x'})


if __name__ == '__main__':
    unittest.main()
