"""Synthetic DiDi transport only; no fixture files or live requests."""
import json
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from hunt.discovery import discover
from hunt.providers import Context, REGISTRY, route
from hunt.providers import didi
from hunt.sources import SourceError


def post(n, **fields):
    row = dict(jdId=n, jdNo='JR202610' + str(n), jobName='产品经理 ' + str(n), jobTypeName='产品',
               deptName='出行事业部', workArea='北京市', refreshTime='2026-10-27',
               jobDuty='负责需求分析与产品规划', jobQualification='熟悉用户研究和数据分析')
    row.update(fields)
    return row


def page_of(items, total):
    return json.dumps(dict(meta=dict(code=0), data=dict(total=total, items=items)), ensure_ascii=False).encode('utf-8')


class Server:
    """Serve the same public board regardless of local keyword count."""
    def __init__(self, total, pages=None):
        self.total, self.pages, self.calls = total, pages, []

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        query = parse_qs(urlsplit(url).query)
        page, size = int(query['page'][0]), int(query['size'][0])
        if self.pages is not None:
            return page_of(self.pages[page - 1], self.total)
        start = (page - 1) * size
        return page_of([post(n + 1) for n in range(start, min(start + size, self.total))], self.total)


def collect(transport, *, terms=None, limit=200, pages=5, keep=None, entry=None):
    report = dict(search_url=None, pages=0, fetched=0, filtered=0, truncated=False)
    ctx = Context(transport, ['产品经理'] if terms is None else terms, limit, pages, report, keep=keep)
    return list(didi.fetch(entry or {}, ctx)), report


def run(transport, **config):
    return discover(dict(dict(keywords=['产品经理'], sources=['didi'], check_entries=False), **config), transport=transport)


class DidiTests(unittest.TestCase):
    def setUp(self):
        # Any accidental fallback to the real reader fails before it can contact a host.
        for name in ('hunt.network.fetch', 'hunt.discovery.fetch'):
            guard = patch(name, side_effect=AssertionError('Tests must use synthetic transport'))
            guard.start()
            self.addCleanup(guard.stop)

    def test_registered_and_detects_both_entry_url_fields(self):
        provider = REGISTRY['didi']
        self.assertIs(provider, didi.PROVIDER)
        self.assertIs(route(dict(kind='didi')), provider)
        for key in ('careers_url', 'url'):
            with self.subTest(key=key):
                entry = {key: 'https://talent.didiglobal.com/social', 'company': '滴滴科技'}
                self.assertEqual(provider.detect(entry), dict(entry, kind='didi'))
                self.assertIs(route(entry), provider)
                self.assertNotIn('kind', entry)

    def test_detect_requires_exact_https_host(self):
        for url in ('http://talent.didiglobal.com/social', 'https://talent.didiglobal.com.evil.test/social',
                    'https://other.didiglobal.com/social', 'https://evil.test/talent.didiglobal.com',
                    '//talent.didiglobal.com/social', 'https://[invalid', '', None, 7):
            with self.subTest(url=url):
                self.assertIsNone(didi.detect(dict(careers_url=url)))
                self.assertIsNone(didi.detect(dict(url=url)))
        self.assertIsNone(didi.detect({}))
        self.assertEqual(didi.detect(dict(careers_url='https://[invalid', url=didi.SOCIAL))['kind'], 'didi')

    def test_fields_and_confirmed_detail_route(self):
        row = post(66320, jdNo='JR2026091000C', jobName='AI 产品经理', jobDuty='<p>负责产品规划</p><p>推进落地</p>',
                   jobQualification='熟悉大模型应用场景')
        result = run(lambda url, **kw: page_of([row], 1))
        job = result['jobs'][0]
        report = result['sources'][0]
        self.assertEqual((report['kind'], report['status'], report['returned']), ('didi', 'ok', 1))
        self.assertEqual((job['channel'], job['platform_id'], job['title']), ('didi', '66320', 'AI 产品经理'))
        self.assertEqual((job['company'], job['location'], job['published_at'], job['status']),
                         ('滴滴', '北京市', '2026-10-27', 'open'))
        self.assertEqual(job['url'], 'https://talent.didiglobal.com/social/jobDetail?jdId=66320')
        self.assertEqual(job['application_url'], job['url'])
        for content in ('岗位职责:', '负责产品规划\n推进落地', '任职要求:', '熟悉大模型应用场景', '类别: 产品', '部门: 出行事业部'):
            self.assertIn(content, job['jd'])
        self.assertNotIn('<p>', job['jd'])
        self.assertEqual(job['raw']['source_kind'], 'didi')
        self.assertEqual(job['raw']['record'], row)
        self.assertEqual(job['raw']['record']['jdNo'], 'JR2026091000C')

    def test_detected_entry_and_company_override(self):
        result = run(lambda url, **kw: page_of([post(1)], 1),
                     discovery_sources=[dict(url=didi.SOCIAL, company='滴滴科技')])
        self.assertEqual(result['sources'][0]['kind'], 'didi')
        self.assertEqual(result['jobs'][0]['company'], '滴滴科技')

    def test_detail_id_is_safely_urlencoded(self):
        ident = 'JR/空 格+&?#=1'
        jobs, _ = collect(lambda url, **kw: page_of([post(ident)], 1))
        parts = urlsplit(jobs[0]['url'])
        self.assertEqual((parts.scheme, parts.hostname, parts.path, parts.fragment),
                         ('https', 'talent.didiglobal.com', '/social/jobDetail', ''))
        self.assertEqual(parse_qs(parts.query), {'jdId': [ident]})
        self.assertEqual(jobs[0]['platform_id'], ident)
        self.assertEqual(jobs[0]['application_url'], jobs[0]['url'])

    def test_get_headers_and_page_query_without_body_or_keywords(self):
        server = Server(101)
        _, report = collect(server, terms=['产品经理', '运营'])
        self.assertEqual(len(server.calls), 2)
        for index, (url, kwargs) in enumerate(server.calls, 1):
            parts = urlsplit(url)
            self.assertEqual((parts.scheme, parts.hostname, parts.path),
                             ('https', 'talent.didiglobal.com', '/recruit-portal-service/api/job/front/list'))
            self.assertEqual(parse_qs(parts.query), {'page': [str(index)], 'size': ['100']})
            self.assertEqual(kwargs, dict(method='GET', headers={
                'Referer': 'https://talent.didiglobal.com/social', 'Origin': 'https://talent.didiglobal.com'}))
        self.assertEqual(report['search_url'], 'https://talent.didiglobal.com/recruit-portal-service/api/job/front/list?page=1&size=100')

    def test_multiple_terms_share_one_board_traversal(self):
        server = Server(150)
        jobs, report = collect(server, terms=['产品经理', '用户研究', '数据分析'])
        self.assertEqual([job['platform_id'] for job in jobs], [str(n) for n in range(1, 151)])
        self.assertEqual((len(server.calls), report['pages'], report['fetched'], report['truncated']), (2, 2, 150, False))

    def test_total_stops_without_requesting_an_extra_page(self):
        for total in (1, 100, 200):
            with self.subTest(total=total):
                server = Server(total)
                jobs, report = collect(server)
                expected_pages = (total + 99) // 100
                self.assertEqual((len(jobs), len(server.calls), report['pages'], report['fetched'], report['truncated']),
                                 (total, expected_pages, expected_pages, total, False))

    def test_empty_page_stops_even_before_advertised_total(self):
        server = Server(500, pages=[[post(1)], []])
        jobs, report = collect(server)
        self.assertEqual([job['platform_id'] for job in jobs], ['1'])
        self.assertEqual((len(server.calls), report['pages'], report['fetched'], report['truncated']), (2, 2, 1, False))

    def test_empty_board(self):
        result = run(lambda url, **kw: page_of([], 0))
        report = result['sources'][0]
        self.assertEqual(result['jobs'], [])
        self.assertEqual((report['status'], report['pages'], report['fetched'], report['truncated'], report['error']),
                         ('empty', 1, 0, False, None))

    def test_page_cap_bounds_requests_and_marks_truncated(self):
        server = Server(350)
        jobs, report = collect(server, pages=2, limit=1000)
        self.assertEqual((len(jobs), len(server.calls), report['pages'], report['fetched'], report['truncated']),
                         (200, 2, 2, 200, True))

    def test_page_cap_marks_truncated_when_all_rows_filtered(self):
        server = Server(350)
        jobs, report = collect(server, terms=['量子密码'], pages=1)
        self.assertEqual(jobs, [])
        self.assertEqual((len(server.calls), report['fetched'], report['truncated']), (1, 100, True))

    def test_limit_cuts_off_only_extra_matching_jobs(self):
        server = Server(30)
        jobs, report = collect(server, limit=10)
        self.assertEqual([job['platform_id'] for job in jobs], [str(n) for n in range(1, 11)])
        self.assertEqual((len(server.calls), report['fetched'], report['truncated']), (1, 30, True))

    def test_limit_equal_to_all_matches_is_not_truncated(self):
        server = Server(10)
        jobs, report = collect(server, limit=10)
        self.assertEqual((len(jobs), report['truncated']), (10, False))

    def test_duplicate_and_unmatched_rows_after_limit_are_not_truncation(self):
        rows = [post(1), post('1'), post(2, jobName='财务专员', jobDuty='核对账款', jobQualification='会计资格')]
        jobs, report = collect(lambda url, **kw: page_of(rows, 3), limit=1)
        self.assertEqual([job['platform_id'] for job in jobs], ['1'])
        self.assertFalse(report['truncated'])

    def test_keywords_match_title_duty_and_qualification(self):
        rows = [post(1, jobName='模型研究员', jobDuty='研究算法', jobQualification='数学基础'),
                post(2, jobName='研究员', jobDuty='开发量子密码方案', jobQualification='数学基础'),
                post(3, jobName='研究员', jobDuty='研究算法', jobQualification='熟悉稀疏编码'),
                post(4, jobName='会计', jobDuty='核对账款', jobQualification='会计资格')]
        jobs, report = collect(lambda url, **kw: page_of(rows, 4), terms=['模型研究员', '量子密码', '稀疏编码'], limit=3)
        self.assertEqual([job['platform_id'] for job in jobs], ['1', '2', '3'])
        self.assertEqual((report['fetched'], report['truncated']), (4, False))

    def test_unmatched_rows_do_not_consume_limit(self):
        rows = [post(n, jobName='财务专员', jobDuty='核对账款', jobQualification='会计资格') for n in range(1, 10)]
        rows += [post(10), post(11)]
        jobs, report = collect(lambda url, **kw: page_of(rows, len(rows)), limit=2)
        self.assertEqual([job['platform_id'] for job in jobs], ['10', '11'])
        self.assertFalse(report['truncated'])

    def test_keep_rejections_count_once_and_do_not_consume_limit(self):
        rows = [post(1), post('1'), post(2), post(3), post(3)]
        visited = []
        def keep(job):
            visited.append(job['platform_id'])
            return job['platform_id'] != '1'
        jobs, report = collect(lambda url, **kw: page_of(rows, len(rows)), limit=2, keep=keep)
        self.assertEqual([job['platform_id'] for job in jobs], ['2', '3'])
        self.assertEqual(visited, ['1', '2', '3'])
        self.assertEqual((report['filtered'], report['truncated']), (1, False))

    def test_keep_receives_only_keyword_matches(self):
        rows = [post(1, jobName='财务专员', jobDuty='核对账款', jobQualification='会计资格'), post(2)]
        visited = []
        def keep(job):
            visited.append(job['platform_id'])
            return False
        jobs, report = collect(lambda url, **kw: page_of(rows, 2), keep=keep)
        self.assertEqual((jobs, visited, report['filtered'], report['truncated']), ([], ['2'], 1, False))

    def test_filtering_continues_across_pages(self):
        rows = [post(n) for n in range(1, 101)]
        server = Server(102, pages=[rows, [post(101), post(102)]])
        jobs, report = collect(server, limit=2, keep=lambda job: int(job['platform_id']) > 100)
        self.assertEqual([job['platform_id'] for job in jobs], ['101', '102'])
        self.assertEqual((len(server.calls), report['filtered'], report['fetched'], report['truncated']), (2, 100, 102, False))

    def test_dedupes_stable_id_across_pages_and_preserves_order(self):
        server = Server(102, pages=[[post(n) for n in range(1, 101)], [post('1'), post(101)]])
        jobs, report = collect(server)
        self.assertEqual([job['platform_id'] for job in jobs], [str(n) for n in range(1, 102)])
        self.assertEqual((len(server.calls), report['fetched'], report['truncated']), (2, 102, False))

    def test_discover_tracks_request_budget_and_keeps_partial_results(self):
        result = run(Server(150), max_jobs=100, discovery_requests=1, max_pages=5)
        report = result['sources'][0]
        self.assertEqual((len(result['jobs']), result['requests'], report['pages'], report['fetched'], report['truncated']),
                         (100, 1, 1, 100, True))
        self.assertEqual(report['status'], 'budget_exhausted')

    def test_bad_list_shapes_raise_source_parse_error(self):
        shapes = (None, [], {}, dict(data=[]), dict(data={}), dict(data=dict(total=1)),
                  dict(data=dict(items=[])), dict(data=dict(total=0, items=None)),
                  dict(data=dict(total=1, items={})), dict(data=dict(total=1, items='oops')))
        for value in shapes:
            with self.subTest(value=value):
                with self.assertRaises(SourceError) as caught:
                    collect(lambda url, **kw: json.dumps(value).encode())
                self.assertEqual(caught.exception.status, 'parse_error')

    def test_invalid_totals_raise_source_parse_error(self):
        for total in (None, True, False, -1, 1.5, {}, [1], '', 'many', '-1'):
            with self.subTest(total=total):
                with self.assertRaises(SourceError) as caught:
                    collect(lambda url, **kw: page_of([post(1)], total))
                self.assertEqual(caught.exception.status, 'parse_error')

    def test_digit_string_total_is_supported(self):
        jobs, report = collect(lambda url, **kw: page_of([post(1)], '1'))
        self.assertEqual((len(jobs), report['pages'], report['truncated']), (1, 1, False))

    def test_non_json_is_source_parse_error(self):
        for raw in (b'<html>maintenance</html>', b'\xff', b'{', b''):
            with self.subTest(raw=raw):
                with self.assertRaises(SourceError) as caught:
                    collect(lambda url, **kw: raw)
                self.assertEqual(caught.exception.status, 'parse_error')
                self.assertEqual(run(lambda url, **kw: raw)['sources'][0]['status'], 'parse_error')

    def test_bad_rows_are_recorded_and_later_rows_and_pages_survive(self):
        bad_rows = [None, [], 'oops', {}, post(7, jdId=None), post(7, jdId=[]), post(7, jdId=True),
                    post(7, jdId=' '), post(7, jobName=None), post(7, jobName=' '), post(7, jobName={}),
                    post(7, jobDuty=None, jobQualification=''), post(7, jobDuty='<p></p>', jobQualification=' '),
                    post(7, jobDuty={}), post(7, jobQualification=[]), post('\ud800')]
        for bad in bad_rows:
            with self.subTest(bad=bad):
                # ASCII JSON also exercises malformed Unicode without any file access.
                responses = [json.dumps(dict(data=dict(total=101, items=[post(1), bad, post(2)]))).encode(),
                             page_of([post(3)], 101)]
                calls = []
                def transport(url, **kw):
                    calls.append(url)
                    return responses[len(calls) - 1]
                result = run(transport, max_pages=2, max_jobs=100)
                report = result['sources'][0]
                self.assertEqual([job['platform_id'] for job in result['jobs']], ['1', '2', '3'])
                self.assertEqual((report['status'], len(calls), report['pages'], report['fetched'], report['detail_error_count']),
                                 ('parse_error', 2, 2, 4, 1))
                self.assertEqual(report['detail_errors'][0]['status'], 'parse_error')

    def test_bad_row_identity_is_preserved(self):
        jobs, report = collect(lambda url, **kw: page_of([post(1), post(7, jobName='')], 2))
        self.assertEqual(len(jobs), 1)
        self.assertEqual(report['detail_errors'][0]['platform_id'], '7')

    def test_bad_row_errors_are_capped_with_true_count(self):
        rows = [post(1)] + [post(n, jobDuty='', jobQualification='') for n in range(2, 27)]
        result = run(lambda url, **kw: page_of(rows, len(rows)))
        report = result['sources'][0]
        self.assertEqual((len(result['jobs']), len(report['detail_errors']), report['detail_error_count']), (1, 20, 25))
        self.assertIn('25 个岗位详情无法解析', report['error'])

    def test_non_parse_source_errors_propagate(self):
        with patch.object(didi, '_job', side_effect=SourceError('cancelled', 'stop')):
            with self.assertRaises(SourceError) as caught:
                collect(lambda url, **kw: page_of([post(1)], 1))
        self.assertEqual(caught.exception.status, 'cancelled')

    def test_optional_fields_and_refresh_date(self):
        for value, expected in (('2026-10-27', '2026-10-27'), ('2026-10-27 12:34:56', '2026-10-27'),
                                ('2026-02-30', None), ('invalid', None), (None, None)):
            with self.subTest(value=value):
                row = post('7', jobTypeName=None, deptName=None, workArea=None, refreshTime=value,
                           jobDuty=None, jobQualification='产品经理需熟悉数据分析')
                jobs, _ = collect(lambda url, **kw: page_of([row], 1))
                self.assertEqual((jobs[0]['location'], jobs[0]['published_at']), (None, expected))
                self.assertIn('产品经理需熟悉数据分析', jobs[0]['jd'])


if __name__ == '__main__':
    unittest.main()
