import json
import unittest
from unittest.mock import patch
from urllib.parse import unquote, urlsplit

from hunt.discovery import discover
from hunt.providers import Context, REGISTRY, route
from hunt.providers import xiaohongshu
from hunt.sources import SourceError

API = 'https://job.xiaohongshu.com/websiterecruit/position/pageQueryPosition'
LIST = 'https://job.xiaohongshu.com/social/position'
REFERER = 'https://job.xiaohongshu.com/?type=social'


def post(n, **fields):
    row = dict(positionId=n, positionName='产品经理 ' + str(n), workplace='北京市，上海市',
               publishTime='2026-10-27', duty='负责产品规划', qualification='具备需求分析经验',
               jobType='产品', subDirectionName='社区', recruitStatus='in_recruitment')
    row.update(fields)
    return row


def page_of(posts, total=None, total_page=None):
    total = len(posts) if total is None else total
    total_page = (int(total) + 99) // 100 if total_page is None else total_page
    return json.dumps(dict(data=dict(total=total, totalPage=total_page, list=posts)), ensure_ascii=True).encode()


class Server:
    """Synthetic transport; never delegates to an actual HTTP client."""
    def __init__(self, total, make_post=post):
        self.total, self.make_post, self.calls = total, make_post, []

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        body = json.loads(kwargs['data'])
        start = (body['pageNum'] - 1) * body['pageSize']
        return page_of([self.make_post(n) for n in range(start, min(start + body['pageSize'], self.total))], self.total)


class Pages:
    def __init__(self, *responses):
        self.responses, self.calls = responses, []

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if len(self.calls) > len(self.responses):
            raise AssertionError('Unexpected extra request')
        return self.responses[len(self.calls) - 1]


def run(transport, **config):
    return discover(dict(dict(keywords=['产品经理'], sources=['xiaohongshu'], check_entries=False), **config),
                    transport=transport)


def collect(transport, *, terms=None, limit=500, pages=5, keep=None, entry=None):
    report = dict(pages=0, fetched=0, filtered=0, truncated=False, search_url=None)
    ctx = Context(transport, ['产品经理'] if terms is None else terms, limit, pages, report, keep=keep)
    return list(xiaohongshu.fetch(entry or {}, ctx)), report


class XiaohongshuTests(unittest.TestCase):
    def setUp(self):
        # Fail before any real DNS or socket access, even if a transport is accidentally omitted.
        for target in ('socket.getaddrinfo', 'socket.socket.connect'):
            guard = patch(target, side_effect=AssertionError('These tests must stay offline'))
            guard.start()
            self.addCleanup(guard.stop)

    def test_registered_and_explicit_route(self):
        self.assertIs(REGISTRY['xiaohongshu'], xiaohongshu.PROVIDER)
        self.assertIs(route(dict(kind='xiaohongshu')), xiaohongshu.PROVIDER)

    def test_detect_exact_https_host_for_both_url_fields(self):
        for key in ('careers_url', 'url'):
            for url in (LIST, 'https://job.xiaohongshu.com/social/position/20927', 'https://JOB.XIAOHONGSHU.COM/'):
                with self.subTest(key=key, url=url):
                    entry = {key: url, 'company': '小红书科技'}
                    self.assertEqual(xiaohongshu.detect(entry), dict(entry, kind='xiaohongshu'))
                    self.assertIs(route(entry), xiaohongshu.PROVIDER)

    def test_detect_rejects_other_hosts_schemes_and_malformed_urls(self):
        for url in ('http://job.xiaohongshu.com/', '//job.xiaohongshu.com/',
                    'https://www.xiaohongshu.com/', 'https://sub.job.xiaohongshu.com/',
                    'https://job.xiaohongshu.com.evil.test/', 'https://job.xiaohongshu.com./',
                    'https://evil.test/job.xiaohongshu.com', 'https://job.xiaohongshu.com@evil.test/',
                    'https://[broken', '', None):
            for key in ('careers_url', 'url'):
                with self.subTest(key=key, url=url):
                    self.assertIsNone(xiaohongshu.detect({key: url}))
        self.assertIsNone(xiaohongshu.detect({}))

    def test_detected_source_runs_with_company_override(self):
        result = run(Server(1), discovery_sources=[dict(careers_url=LIST, company='小红书科技')])
        report = result['sources'][0]
        self.assertEqual((report['kind'], report['status'], report['returned']), ('xiaohongshu', 'ok', 1))
        self.assertEqual(result['jobs'][0]['company'], '小红书科技')

    def test_field_mapping_and_normalization(self):
        row = post(20927, positionName='<b>AI 产品经理</b>', duty='<p>负责大模型产品需求分析</p>',
                   qualification='<p>熟悉 RAG 与智能体应用</p>')
        result = run(Pages(page_of([row])))
        job = result['jobs'][0]
        self.assertEqual((job['channel'], job['platform_id'], job['title']),
                         ('xiaohongshu', '20927', 'AI 产品经理'))
        self.assertEqual((job['company'], job['location'], job['published_at']),
                         ('小红书', '北京市，上海市', '2026-10-27'))
        self.assertEqual(job['jd'], '负责大模型产品需求分析\n\n熟悉 RAG 与智能体应用')
        self.assertEqual(job['url'], 'https://job.xiaohongshu.com/social/position/20927')
        self.assertEqual(job['application_url'], job['url'])
        self.assertEqual(job['status'], 'unverified')
        self.assertEqual(job['raw']['source_kind'], 'xiaohongshu')
        self.assertEqual(job['raw']['record'], row)
        self.assertNotIn('社区', job['jd'])

    def test_detail_url_safely_encodes_position_id_as_one_path_segment(self):
        cases = [
            ('id/with/slashes', '/social/position/id%2Fwith%2Fslashes'),
            ('岗位 /?&type=other+#中文',
             '/social/position/%E5%B2%97%E4%BD%8D%20%2F%3F%26type%3Dother%2B%23%E4%B8%AD%E6%96%87'),
            ('id%2Fsegment', '/social/position/id%252Fsegment'),
        ]
        for ident, expected_path in cases:
            with self.subTest(ident=ident):
                job = run(Pages(page_of([post(ident)])))['jobs'][0]
                parts = urlsplit(job['url'])
                self.assertEqual((parts.scheme, parts.hostname, parts.path, parts.query, parts.fragment),
                                 ('https', 'job.xiaohongshu.com', expected_path, '', ''))
                self.assertEqual(unquote(parts.path.rsplit('/', 1)[-1]), ident)
                self.assertEqual(job['application_url'], job['url'])
                self.assertEqual(job['platform_id'], ident)

    def test_status_values_do_not_filter_or_invent_open_state(self):
        rows = [post(n, recruitStatus=status) for n, status in enumerate(('in_recruitment', 'unknown', 'closed', 0, None))]
        result = run(Pages(page_of(rows)))
        self.assertEqual(len(result['jobs']), len(rows))
        self.assertTrue(all(job['status'] == 'unverified' for job in result['jobs']))
        self.assertEqual([job['raw']['record']['recruitStatus'] for job in result['jobs']],
                         ['in_recruitment', 'unknown', 'closed', 0, None])

    def test_optional_fields_and_each_body_section_independently(self):
        rows = [dict(positionId='1', positionName='产品经理', duty='负责产品规划'),
                dict(positionId='2', positionName='产品经理', qualification='熟悉产品设计')]
        result = run(Pages(page_of(rows)))
        self.assertEqual([job['jd'] for job in result['jobs']], ['负责产品规划', '熟悉产品设计'])
        self.assertTrue(all(job['location'] is None and job['published_at'] is None for job in result['jobs']))

    def test_request_headers_body_and_report(self):
        server = Server(1)
        result = run(server)
        url, kwargs = server.calls[0]
        self.assertEqual(url, API)
        self.assertEqual(kwargs['method'], 'POST')
        self.assertIsInstance(kwargs['data'], bytes)
        self.assertEqual(json.loads(kwargs['data']), dict(pageNum=1, pageSize=100, recruitType='social'))
        self.assertEqual(kwargs['headers'], {'Content-Type': 'application/json', 'Referer': REFERER,
                                             'Origin': 'https://job.xiaohongshu.com'})
        report = result['sources'][0]
        self.assertEqual((report['pages'], report['fetched'], report['requests'], report['search_url']), (1, 1, 1, API))
        self.assertFalse(report['truncated'])

    def test_multiple_keywords_share_one_complete_paging_pass(self):
        server = Server(150, lambda n: post(n, positionName='产品经理' if n < 100 else '智能体架构师'))
        jobs, report = collect(server, terms=['产品经理', '智能体'])
        self.assertEqual((len(server.calls), len(jobs), report['fetched']), (2, 150, 150))
        self.assertEqual([json.loads(kw['data']) for _, kw in server.calls],
                         [dict(pageNum=n, pageSize=100, recruitType='social') for n in (1, 2)])
        self.assertFalse(report['truncated'])

    def test_pagination_complete_at_total(self):
        server = Server(225)
        jobs, report = collect(server)
        self.assertEqual((len(server.calls), report['pages'], report['fetched'], len(jobs)), (3, 3, 225, 225))
        self.assertEqual([job['platform_id'] for job in jobs], [str(n) for n in range(225)])
        self.assertFalse(report['truncated'])

    def test_full_last_page_stops_without_extra_request(self):
        server = Server(200)
        jobs, report = collect(server)
        self.assertEqual((len(server.calls), len(jobs), report['pages']), (2, 200, 2))
        self.assertFalse(report['truncated'])

    def test_short_nonempty_page_is_not_an_end_signal(self):
        server = Pages(*(page_of([post(n)], total=250) for n in (1, 2, 3)))
        jobs, report = collect(server)
        self.assertEqual((len(server.calls), len(jobs), report['fetched']), (3, 3, 3))
        self.assertFalse(report['truncated'])

    def test_empty_board(self):
        server = Pages(page_of([], 0))
        result = run(server)
        report = result['sources'][0]
        self.assertEqual((report['status'], report['pages'], report['fetched'], report['returned']), ('empty', 1, 0, 0))
        self.assertIsNone(report['error'])
        self.assertFalse(report['truncated'])
        self.assertEqual(len(server.calls), 1)

    def test_empty_page_stops_even_when_total_is_stale(self):
        server = Pages(page_of([post(1)], 350), page_of([], 350))
        jobs, report = collect(server)
        self.assertEqual((len(server.calls), report['pages'], report['fetched'], len(jobs)), (2, 2, 1, 1))
        self.assertFalse(report['truncated'])

    def test_digit_string_paging_metadata(self):
        server = Pages(page_of([post(1)], '150', '2'), page_of([post(2)], '150', '2'))
        jobs, report = collect(server)
        self.assertEqual((len(server.calls), len(jobs)), (2, 2))
        self.assertFalse(report['truncated'])

    def test_page_cap_is_total_request_cap_across_terms(self):
        server = Server(350)
        jobs, report = collect(server, pages=2, terms=['产品经理', 'AI', '智能体'])
        self.assertEqual((len(server.calls), report['pages'], report['fetched'], len(jobs)), (2, 2, 200, 200))
        self.assertTrue(report['truncated'])

    def test_limit_inside_page(self):
        server = Server(30)
        result = run(server, max_jobs=10)
        report = result['sources'][0]
        self.assertEqual((len(server.calls), report['returned'], report['fetched']), (1, 10, 30))
        self.assertTrue(report['truncated'])

    def test_exact_limit_at_end_is_complete(self):
        result = run(Server(30), max_jobs=30)
        self.assertEqual(result['sources'][0]['returned'], 30)
        self.assertFalse(result['sources'][0]['truncated'])

    def test_limit_at_page_boundary_detects_remaining_jobs(self):
        server = Server(150)
        result = run(server, max_jobs=100, max_pages=5)
        report = result['sources'][0]
        self.assertEqual((len(server.calls), report['pages'], report['fetched'], report['returned']), (2, 2, 150, 100))
        self.assertTrue(report['truncated'])

    def test_local_matching_uses_title_duty_and_qualification(self):
        rows = [post(1, positionName='RAG 产品经理'),
                post(2, positionName='搜索工程师', duty='负责 RAG 系统'),
                post(3, positionName='通用开发', qualification='熟悉检索增强'),
                post(4, positionName='后端开发', duty='维护存储', qualification='熟悉数据库')]
        result = run(Pages(page_of(rows)), keywords=['RAG'])
        self.assertEqual([job['platform_id'] for job in result['jobs']], ['1', '2', '3'])
        self.assertEqual(result['sources'][0]['filtered'], 1)

    def test_local_matching_obeys_shared_multiword_semantics(self):
        rows = [post(1, positionName='AI 算法工程师'),
                post(2, positionName='产品经理', duty='负责大模型需求'),
                post(3, positionName='Product Manager', qualification='熟悉 LLM')]
        result = run(Pages(page_of(rows)), keywords=['AI 产品经理'])
        self.assertEqual([job['platform_id'] for job in result['jobs']], ['2', '3'])
        self.assertEqual(result['sources'][0]['filtered'], 1)

    def test_keyword_filter_cannot_spend_limit_or_stop_pagination(self):
        def make_post(n):
            return post(n, positionName='后端开发' if n < 100 else '产品经理')
        server = Server(102, make_post)
        result = run(server, max_jobs=2, max_pages=5)
        report = result['sources'][0]
        self.assertEqual([job['platform_id'] for job in result['jobs']], ['100', '101'])
        self.assertEqual((len(server.calls), report['pages'], report['fetched'], report['filtered']), (2, 2, 102, 100))
        self.assertFalse(report['truncated'])

    def test_all_filtered_is_reported_as_filtered_empty(self):
        server = Server(150, lambda n: post(n, positionName='后端开发'))
        result = run(server, max_jobs=1, max_pages=5)
        report = result['sources'][0]
        self.assertEqual((report['status'], report['fetched'], report['filtered'], report['returned']),
                         ('filtered_empty', 150, 150, 0))
        self.assertEqual(len(server.calls), 2)
        self.assertFalse(report['truncated'])

    def test_keep_rejections_do_not_spend_limit(self):
        server = Server(150)
        checked = []
        def keep(job):
            checked.append(job['platform_id'])
            return int(job['platform_id']) >= 148
        jobs, report = collect(server, keep=keep, limit=2)
        self.assertEqual([job['platform_id'] for job in jobs], ['148', '149'])
        self.assertEqual((len(server.calls), len(checked), report['filtered'], report['fetched']), (2, 150, 148, 150))
        self.assertFalse(report['truncated'])

    def test_keep_and_keyword_filter_count_each_rejection_once(self):
        rows = [post(1, positionName='后端开发'), post(2), post(3)]
        checked = []
        def keep(job):
            checked.append(job['platform_id'])
            return job['platform_id'] == '3'
        jobs, report = collect(Pages(page_of(rows)), keep=keep, limit=1)
        self.assertEqual(checked, ['2', '3'])
        self.assertEqual([job['platform_id'] for job in jobs], ['3'])
        self.assertEqual(report['filtered'], 2)
        self.assertFalse(report['truncated'])

    def test_dedupes_stable_id_across_pages_and_keywords(self):
        server = Pages(page_of([post(1), post('1'), post(2)], 150), page_of([post('2'), post(3)], 150))
        jobs, report = collect(server, terms=['产品经理', '产品'], limit=3)
        self.assertEqual([job['platform_id'] for job in jobs], ['1', '2', '3'])
        self.assertEqual((report['fetched'], report['filtered'], len(server.calls)), (5, 0, 2))
        self.assertFalse(report['truncated'])

    def test_filtered_duplicates_do_not_repeat_keep_or_inflate_filtered(self):
        rows = [post(1), post('1'), post(2), post('2')]
        checked = []
        def keep(job):
            checked.append(job['platform_id'])
            return job['platform_id'] == '2'
        jobs, report = collect(Pages(page_of(rows)), keep=keep, limit=1)
        self.assertEqual(checked, ['1', '2'])
        self.assertEqual((len(jobs), report['filtered'], report['fetched']), (1, 1, 4))
        self.assertFalse(report['truncated'])

    def test_metadata_cannot_substitute_for_missing_posting_body(self):
        bad = dict(positionId=7, positionName='产品经理', jobType='产品经理', subDirectionName='智能体')
        result = run(Pages(page_of([bad, post(1)])))
        self.assertEqual([job['platform_id'] for job in result['jobs']], ['1'])
        self.assertEqual(result['sources'][0]['detail_errors'][0]['platform_id'], '7')

    def test_bad_rows_are_recorded_and_later_rows_and_pages_survive(self):
        bad_rows = [None, 'oops', [], {}, dict(positionName='产品经理', duty='产品规划'),
                    post(None), post(''), post('  '), post(True), post([]), post({}), post(1.5),
                    post(7, positionName=''), post(7, positionName=[]), post(7, positionName={}),
                    post(7, duty=None, qualification=None), post(7, duty=' ', qualification='<p></p>'),
                    post(7, duty=['负责产品']), post(7, qualification={'text': '要求'}), post('\ud800')]
        for bad in bad_rows:
            with self.subTest(bad=bad):
                server = Pages(page_of([post(1), bad, post(2)], 150), page_of([post(3)], 150))
                result = run(server, max_jobs=100, max_pages=2)
                report = result['sources'][0]
                self.assertEqual([job['platform_id'] for job in result['jobs']], ['1', '2', '3'])
                self.assertEqual((report['status'], report['detail_error_count'], len(report['detail_errors'])),
                                 ('parse_error', 1, 1))
                self.assertEqual(report['detail_errors'][0]['status'], 'parse_error')
                self.assertIn('1 个岗位详情无法解析', report['error'])
                self.assertEqual((len(server.calls), report['pages'], report['fetched']), (2, 2, 4))

    def test_detail_errors_are_capped_but_true_count_is_kept(self):
        rows = [post(1)] + [dict(positionId=100 + n, positionName='空岗位') for n in range(25)] + [post(2)]
        result = run(Pages(page_of(rows)))
        report = result['sources'][0]
        self.assertEqual([job['platform_id'] for job in result['jobs']], ['1', '2'])
        self.assertEqual((len(report['detail_errors']), report['detail_error_count']), (20, 25))
        self.assertIn('25 个岗位详情无法解析', report['error'])

    def test_bad_list_structure_raises_source_error(self):
        bad_pages = [None, [], 1, {}, {'data': None}, {'data': []},
                     {'data': {'total': 0, 'totalPage': 0}},
                     {'data': {'list': None, 'total': 0, 'totalPage': 0}},
                     {'data': {'list': {}, 'total': 0, 'totalPage': 0}},
                     {'data': {'list': 'changed', 'total': 0, 'totalPage': 0}}]
        for payload in bad_pages:
            with self.subTest(payload=payload):
                raw = json.dumps(payload).encode()
                with self.assertRaises(SourceError) as raised:
                    collect(Pages(raw))
                self.assertEqual(raised.exception.status, 'parse_error')
                report = run(Pages(raw))['sources'][0]
                self.assertEqual(report['status'], 'parse_error')
                self.assertIn('小红书', report['error'])

    def test_bad_paging_metadata_raises_source_error(self):
        for field in ('total', 'totalPage'):
            for value in (None, '', 'many', '-1', -1, True, False, 1.5, [], {}):
                with self.subTest(field=field, value=value):
                    body = dict(list=[post(1)], total=1, totalPage=1)
                    body[field] = value
                    with self.assertRaises(SourceError) as raised:
                        collect(Pages(json.dumps(dict(data=body)).encode()))
                    self.assertEqual(raised.exception.status, 'parse_error')
            body = dict(list=[], total=0, totalPage=0)
            del body[field]
            self.assertEqual(run(Pages(json.dumps(dict(data=body)).encode()))['sources'][0]['status'], 'parse_error')

    def test_non_json_raises_source_error(self):
        for raw in (b'<html>maintenance</html>', b'', b'{', b'\xff'):
            with self.subTest(raw=raw):
                with self.assertRaises(SourceError) as raised:
                    collect(Pages(raw))
                self.assertEqual(raised.exception.status, 'parse_error')
                self.assertEqual(run(Pages(raw))['sources'][0]['status'], 'parse_error')

    def test_invalid_later_page_preserves_earlier_jobs(self):
        server = Pages(page_of([post(1), post(2)], 150), b'{}')
        result = run(server, max_pages=2)
        report = result['sources'][0]
        self.assertEqual([job['platform_id'] for job in result['jobs']], ['1', '2'])
        self.assertEqual((report['status'], report['requests'], report['pages'], report['fetched']),
                         ('parse_error', 2, 1, 2))

    def test_request_budget_stops_further_requests_and_preserves_jobs(self):
        server = Server(250)
        result = run(server, max_jobs=100, max_pages=5, discovery_requests=1)
        report = result['sources'][0]
        self.assertEqual((len(server.calls), report['requests'], report['pages'], report['returned']), (1, 1, 1, 100))
        self.assertEqual(report['status'], 'budget_exhausted')
        self.assertTrue(report['truncated'])

    def test_non_parse_row_errors_are_not_swallowed(self):
        with patch.object(xiaohongshu, 'normalize', side_effect=SourceError('blocked', 'stopped')):
            with self.assertRaises(SourceError) as raised:
                collect(Pages(page_of([post(1)])))
        self.assertEqual(raised.exception.status, 'blocked')


if __name__ == '__main__':
    unittest.main()
