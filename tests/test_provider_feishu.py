import json
import unittest
from pathlib import Path
from unittest import mock

from hunt.discovery import discover
from hunt.providers import REGISTRY, route

FIXTURES = Path(__file__).parent / 'fixtures' / 'providers'
BYTEDANCE = 'https://jobs.bytedance.com'
TENANT = 'https://vrfi1sk8a0.jobs.feishu.cn'
MAC_UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding='utf-8'))


def page_of(posts, total, code=0):
    return json.dumps(dict(code=code, data=dict(count=total, job_post_list=posts))).encode()


def post(n):
    return dict(id=str(n), title='产品经理 ' + str(n), city_list=[dict(name='北京')], job_category=dict(name='产品'),
                recruit_type=dict(name='正式'), description='负责产品规划 ' + str(n), requirement='三年以上经验', publish_time=1782172800000)


class Server:
    """Fake transport serving a board of `total` posts, paged by limit/offset in the POST body."""
    def __init__(self, total):
        self.total, self.calls = total, []

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        body = json.loads(kwargs['data'])
        start = body['offset']
        return page_of([post(n) for n in range(start, min(start + body['limit'], self.total))], self.total)


def run(transport, url=BYTEDANCE, **config):
    entry = dict(kind='feishu', careers_url=url) if url else dict(kind='feishu')
    return discover(dict(dict(keywords=['产品经理'], discovery_sources=[entry], check_entries=False), **config), transport=transport)


class FeishuTests(unittest.TestCase):
    def setUp(self):
        patch = mock.patch('hunt.providers.feishu.PAUSE', 0)
        patch.start(); self.addCleanup(patch.stop)

    def test_parses_page(self):
        raw = json.dumps(fixture('feishu-page1.json')).encode()
        result = run(lambda url, **kw: raw)
        report = result['sources'][0]
        self.assertEqual((report['status'], report['kind'], report['returned']), ('ok', 'feishu', 2))
        first, second = result['jobs']
        self.assertEqual(first['channel'], 'feishu')
        self.assertEqual(first['platform_id'], '7599900000000000001')
        self.assertEqual(first['title'], 'AI 产品经理（大模型应用）')
        self.assertEqual(first['location'], '北京/上海')
        self.assertEqual(first['company'], '字节跳动')
        self.assertIn('类别: 产品', first['jd'])
        self.assertIn('类型: 正式', first['jd'])
        self.assertIn('负责大模型应用产品的规划与落地', first['jd'])
        self.assertIn('熟悉大模型应用场景', first['jd'])
        self.assertEqual(first['published_at'], '2026-06-23')
        self.assertEqual((second['platform_id'], second['location']), ('7599900000000000002', '深圳'))
        self.assertNotIn('类别', second['jd'])
        self.assertIsNone(second['published_at'])

    def test_detail_url_by_host(self):
        raw = page_of([post(7)], 1)
        job = run(lambda url, **kw: raw, BYTEDANCE)['jobs'][0]
        self.assertEqual(job['url'], BYTEDANCE + '/experienced/position/7/detail')
        result = run(lambda url, **kw: raw, TENANT)
        self.assertEqual(result['jobs'][0]['url'], TENANT + '/index/position/7/detail')
        self.assertEqual(result['jobs'][0]['company'], 'vrfi1sk8a0.jobs.feishu.cn')

    def test_company_from_entry(self):
        raw = page_of([post(1)], 1)
        result = discover(dict(keywords=['产品经理'], check_entries=False,
                               discovery_sources=[dict(careers_url=TENANT, company='MiniMax')]), transport=lambda url, **kw: raw)
        self.assertEqual((result['sources'][0]['kind'], result['jobs'][0]['company']), ('feishu', 'MiniMax'))

    def test_sends_ua_and_referer(self):
        for base in (BYTEDANCE, TENANT):
            server = Server(1)
            run(server, base)
            url, kwargs = server.calls[0]
            self.assertEqual((url, kwargs['method']), (base + '/api/v1/search/job/posts', 'POST'))
            headers = {k.lower(): v for k, v in kwargs['headers'].items()}
            # jobs.bytedance.com rejects non-macOS user agents with 405.
            self.assertEqual(headers['user-agent'], MAC_UA)
            self.assertEqual(headers['referer'], base + '/')
            self.assertEqual(headers['content-type'], 'application/json')
            self.assertEqual(json.loads(kwargs['data']), dict(limit=100, offset=0, keyword='产品经理'))

    def test_default_origin_is_bytedance(self):
        server = Server(1)
        run(server, None)
        self.assertEqual(server.calls[0][0], BYTEDANCE + '/api/v1/search/job/posts')

    def test_invalid_url_on_explicit_kind_is_not_configured(self):
        for url in ('https://evil.test', 'http://jobs.bytedance.com', 'https://jobs.bytedance.com.evil.test'):
            server = Server(1)
            report = run(server, url)['sources'][0]
            self.assertEqual((report['status'], len(server.calls)), ('not_configured', 0), url)

    def test_pagination_advances_offset_sequentially(self):
        server = Server(250)
        report = run(server, max_pages=5, sweep=True)['sources'][0]
        self.assertEqual([json.loads(kw['data'])['offset'] for _, kw in server.calls], [0, 100, 200])
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
        raw = json.dumps(fixture('feishu-page1.json')).encode()
        keys = []
        def transport(url, **kw):
            keys.append(json.loads(kw['data'])['keyword']); return raw
        result = run(transport, keywords=['产品经理', 'AI'], max_jobs=100)
        self.assertEqual(keys, ['产品经理', 'AI'])
        self.assertEqual(len(result['jobs']), 2)

    def test_zero_matches_is_empty_not_error(self):
        calls = []
        def transport(url, **kw):
            calls.append(1); return page_of([], 0)
        report = run(transport)['sources'][0]
        self.assertEqual((report['status'], report['fetched'], report['error']), ('empty', 0, None))

    def test_structure_change_is_parse_error(self):
        raw = json.dumps(fixture('feishu-changed.json')).encode()
        report = run(lambda url, **kw: raw)['sources'][0]
        self.assertEqual(report['status'], 'parse_error')
        self.assertIn('飞书招聘', report['error'])

    def test_non_json_is_parse_error(self):
        report = run(lambda url, **kw: b'<html>maintenance</html>')['sources'][0]
        self.assertEqual(report['status'], 'parse_error')

    def test_nonzero_code_is_fetch_error(self):
        raw = json.dumps(dict(code=10001, message='rate limited', data=None)).encode()
        report = run(lambda url, **kw: raw)['sources'][0]
        self.assertEqual(report['status'], 'fetch_error')
        self.assertIn('10001', report['error'])

    def test_bad_post_is_reported_and_rest_kept(self):
        bad_rows = [dict(title='产品经理', description='负责产品'), 'oops', dict(id='7', title=''), dict(id='8', description='无名称'), None]
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
        raw = page_of([post(1), dict(id='7', title='')], 2)
        self.assertEqual(run(lambda url, **kw: raw)['sources'][0]['detail_errors'][0]['platform_id'], '7')

    def test_unencodable_id_is_skipped(self):
        raw = page_of([post(1), dict(post(2), id='\ud800')], 2)
        result = run(lambda url, **kw: raw)
        self.assertEqual([j['platform_id'] for j in result['jobs']], ['1'])
        self.assertEqual(len(result['sources'][0]['detail_errors']), 1)

    def test_missing_optional_fields_ok(self):
        raw = page_of([dict(id='5', title='产品经理', city_list=None, job_category=None, recruit_type=None, description='负责产品',
                            requirement=None, publish_time=None)], 1)
        job = run(lambda url, **kw: raw)['jobs'][0]
        self.assertEqual((job['jd'], job['location'], job['published_at']), ('负责产品', None, None))

    def test_total_accepts_digit_string(self):
        raw = json.dumps(dict(code=0, data=dict(count='2', job_post_list=[post(1), post(2)]))).encode()
        report = run(lambda url, **kw: raw)['sources'][0]
        self.assertEqual((report['status'], report['returned']), ('ok', 2))

    def test_total_of_other_types_is_parse_error(self):
        for total in (None, 'many', '', 2.5, True, [2]):
            raw = json.dumps(dict(code=0, data=dict(count=total, job_post_list=[post(1)]))).encode()
            self.assertEqual(run(lambda url, **kw: raw)['sources'][0]['status'], 'parse_error', total)

    def test_detect(self):
        provider = REGISTRY['feishu']
        for url in (BYTEDANCE, BYTEDANCE + '/experienced/position', TENANT, TENANT + '/index', 'https://JOBS.bytedance.com/'):
            hit = provider.detect(dict(careers_url=url))
            self.assertEqual(hit['kind'], 'feishu', url)
            self.assertIs(route(dict(careers_url=url)), provider, url)
        for url in ('http://jobs.bytedance.com', 'https://bytedance.com', 'https://jobs.bytedance.com.evil.test',
                    'https://evil.jobs.bytedance.com', 'https://jobs.feishu.cn', 'https://feishu.cn',
                    'https://jobs.feishu.cn.evil.test', 'https://a.b.jobs.feishu.cn', 'https://evil.test/jobs.feishu.cn',
                    'https://user@jobs.bytedance.com.evil.test/', 'https://xjobs.feishu.cn'):
            self.assertIsNone(provider.detect(dict(careers_url=url)), url)
        self.assertIsNone(provider.detect(dict()))


if __name__ == '__main__':
    unittest.main()
