import json
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from hunt.discovery import discover
from hunt.providers import REGISTRY, route

FIXTURES = Path(__file__).parent / 'fixtures' / 'providers'


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding='utf-8'))


def page_of(posts, count):
    return json.dumps(dict(Code=200, Data=dict(Count=count, Posts=posts))).encode()


def post(n):
    return dict(PostId=str(n), RecruitPostName='产品经理 ' + str(n), CountryName='中国', LocationName='深圳',
                Responsibility='负责产品规划 ' + str(n))


class Server:
    """Fake transport serving a board of `total` posts, paged by pageIndex/pageSize."""
    def __init__(self, total):
        self.total, self.urls = total, []

    def __call__(self, url, **kwargs):
        self.urls.append(url)
        query = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
        start = (int(query['pageIndex']) - 1) * int(query['pageSize'])
        return page_of([post(n) for n in range(start, min(start + int(query['pageSize']), self.total))], self.total)


def run(transport, **config):
    return discover(dict(dict(keywords=['产品经理'], sources=['tencent'], check_entries=False), **config), transport=transport)


class TencentTests(unittest.TestCase):
    def test_parses_page(self):
        raw = json.dumps(fixture('tencent-page1.json')).encode()
        result = run(lambda url, **kw: raw)
        report = result['sources'][0]
        self.assertEqual((report['status'], report['kind'], report['returned']), ('ok', 'tencent', 2))
        first, second = result['jobs']
        self.assertEqual(first['channel'], 'tencent')
        self.assertEqual(first['platform_id'], '1999900000001')
        self.assertEqual(first['title'], 'AI 产品经理（混元大模型）')
        self.assertEqual(first['url'], 'https://careers.tencent.com/jobdesc.html?postId=1999900000001')
        self.assertEqual(first['location'], '中国-深圳')
        self.assertEqual(first['company'], '腾讯')
        self.assertIn('负责大模型应用产品的需求分析', first['jd'])
        self.assertIn('熟悉大模型应用场景', first['jd'])
        self.assertEqual(first['published_at'], '2026-06-23')
        self.assertEqual((second['platform_id'], second['location']), ('1999900000002', '中国-北京'))
        self.assertIn('postId=1999900000002', second['url'])

    def test_request_shape(self):
        server = Server(1)
        run(server)
        parts = urlsplit(server.urls[0])
        query = parse_qs(parts.query)
        self.assertEqual((parts.hostname, parts.path), ('careers.tencent.com', '/tencentcareer/api/post/Query'))
        self.assertEqual((query['keyword'], query['pageIndex'], query['pageSize'], query['language']),
                         (['产品经理'], ['1'], ['100'], ['zh-cn']))

    def test_pagination_stops_at_total(self):
        server = Server(150)
        result = run(server, max_pages=5, max_jobs=100)
        self.assertEqual(len(server.urls), 2)
        report = result['sources'][0]
        self.assertEqual((report['pages'], report['fetched'], report['returned'], report['truncated']), (2, 150, 100, True))

    def test_pagination_complete_when_limit_allows(self):
        server = Server(150)
        result = run(server, max_pages=5, sweep=True)
        report = result['sources'][0]
        self.assertEqual((len(server.urls), report['returned'], report['truncated'], report['status']), (2, 150, False, 'ok'))

    def test_page_cap_marks_truncated(self):
        server = Server(350)
        result = run(server, max_pages=2, max_jobs=100)
        report = result['sources'][0]
        self.assertEqual((len(server.urls), report['pages'], report['fetched']), (2, 2, 200))
        self.assertTrue(report['truncated'])

    def test_limit_marks_truncated(self):
        result = run(Server(30), max_jobs=10)
        report = result['sources'][0]
        self.assertEqual((report['returned'], report['truncated']), (10, True))

    def test_each_keyword_queried_and_deduped_by_post_id(self):
        raw = json.dumps(fixture('tencent-page1.json')).encode()
        urls = []
        def transport(url, **kw):
            urls.append(parse_qs(urlsplit(url).query)['keyword'][0]); return raw
        result = run(transport, keywords=['产品经理', 'AI'], max_jobs=100)
        self.assertEqual(urls, ['产品经理', 'AI'])
        self.assertEqual(len(result['jobs']), 2)
        self.assertEqual(result['sources'][0]['fetched'], 4)

    def test_zero_matches_is_empty_not_error(self):
        result = run(lambda url, **kw: page_of([], 0))
        report = result['sources'][0]
        self.assertEqual((report['status'], report['fetched'], report['error']), ('empty', 0, None))

    def test_live_no_match_shape_is_empty_and_next_keyword_runs(self):
        # Live no-match answer (2026-10-26): Posts is null rather than an empty list.
        raw = (FIXTURES / 'tencent-empty.json').read_bytes()
        report = run(lambda url, **kw: raw)['sources'][0]
        self.assertEqual((report['status'], report['error']), ('empty', None))
        good = json.dumps(fixture('tencent-page1.json')).encode()
        keywords = []
        def transport(url, **kw):
            keywords.append(parse_qs(urlsplit(url).query)['keyword'][0])
            return raw if len(keywords) == 1 else good
        result = run(transport, keywords=['无此岗位', '产品经理'])
        self.assertEqual(keywords, ['无此岗位', '产品经理'])
        self.assertEqual((result['sources'][0]['status'], len(result['jobs'])), ('ok', 2))

    def test_structure_change_is_parse_error(self):
        raw = json.dumps(fixture('tencent-changed.json')).encode()
        report = run(lambda url, **kw: raw)['sources'][0]
        self.assertEqual(report['status'], 'parse_error')
        self.assertIn('腾讯', report['error'])

    def test_non_json_is_parse_error(self):
        report = run(lambda url, **kw: b'<html>maintenance</html>')['sources'][0]
        self.assertEqual(report['status'], 'parse_error')

    def test_bad_post_is_reported_and_rest_kept(self):
        good = lambda n: post(n)
        bad_rows = [dict(RecruitPostName='产品经理', Responsibility='负责产品'), 'oops', dict(PostId='7', RecruitPostName='空岗位'), None]
        for bad in bad_rows:
            pages = [page_of([good(1), bad, good(2)], 150), page_of([good(3)], 150)]
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
        raw = page_of([post(1), dict(PostId='7', RecruitPostName='空岗位')], 2)
        error = run(lambda url, **kw: raw)['sources'][0]['detail_errors'][0]
        self.assertEqual(error['platform_id'], '7')

    def test_bad_post_errors_capped_with_true_count(self):
        raw = page_of([post(1)] + [dict(PostId=str(100 + n), RecruitPostName='空') for n in range(25)], 26)
        result = run(lambda url, **kw: raw)
        report = result['sources'][0]
        self.assertEqual((len(result['jobs']), len(report['detail_errors']), report['detail_error_count']), (1, 20, 25))
        self.assertIn('25 个岗位详情无法解析', report['error'])

    def test_count_accepts_digit_string(self):
        raw = json.dumps(dict(Data=dict(Count='2', Posts=[post(1), post(2)]))).encode()
        report = run(lambda url, **kw: raw)['sources'][0]
        self.assertEqual((report['status'], report['returned']), ('ok', 2))

    def test_count_of_other_types_is_parse_error(self):
        for count in (None, 'many', '', 2.5, True, [2]):
            raw = json.dumps(dict(Data=dict(Count=count, Posts=[post(1)]))).encode()
            self.assertEqual(run(lambda url, **kw: raw)['sources'][0]['status'], 'parse_error', count)

    def test_detect(self):
        provider = REGISTRY['tencent']
        hit = provider.detect(dict(careers_url='https://careers.tencent.com/search.html'))
        self.assertEqual(hit['kind'], 'tencent')
        self.assertIs(route(dict(careers_url='https://careers.tencent.com/search.html')), provider)
        for url in ('https://careers.example.com/search.html', 'https://careers.tencent.com.evil.test/search.html',
                    'http://careers.tencent.com/search.html', 'https://evil.test/careers.tencent.com'):
            self.assertIsNone(provider.detect(dict(careers_url=url)), url)
        self.assertIsNone(provider.detect(dict()))

    def test_detected_entry_runs_through_discover(self):
        raw = json.dumps(fixture('tencent-page1.json')).encode()
        result = discover(dict(keywords=['产品经理'], check_entries=False,
                               discovery_sources=[dict(careers_url='https://careers.tencent.com/search.html', company='腾讯科技')]),
                          transport=lambda url, **kw: raw)
        report = result['sources'][0]
        self.assertEqual((report['kind'], report['status'], report['returned']), ('tencent', 'ok', 2))
        self.assertEqual(result['jobs'][0]['company'], '腾讯科技')


if __name__ == '__main__':
    unittest.main()
