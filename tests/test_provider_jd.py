import json
import unittest
from urllib.parse import parse_qs, urlsplit

from hunt.discovery import discover
from hunt.network import FetchError
from hunt.providers import REGISTRY, route

URL = 'https://zhaopin.jd.com/web/job/job_info_list/3'


def post(n, **fields):
    return dict(dict(id=n, positionName='内部岗位', positionNameOpen='产品经理 ' + str(n), workCity='北京',
                     workContent='负责产品规划', qualification='熟悉需求分析', formatPublishTime='2026-10-27'), **fields)


class Server:
    def __init__(self, total=150, repeat=False):
        self.total, self.repeat, self.calls = total, repeat, []

    def __call__(self, url, **kwargs):
        form = parse_qs(kwargs['data'].decode())
        self.calls.append((url, kwargs, form))
        if url.endswith('/job_count'): return json.dumps(self.total).encode()
        start = 0 if self.repeat else (int(form['pageIndex'][0]) - 1) * 100
        return json.dumps([post(n) for n in range(start, min(start + 100, self.total))]).encode()


def run(transport, **config):
    return discover(dict(dict(keywords=['产品经理'], discovery_sources=[dict(careers_url=URL)],
                              check_entries=False), **config), transport=transport)


class JDTests(unittest.TestCase):
    def test_detect_and_route_only_https_host(self):
        provider = REGISTRY['jd']
        self.assertIs(route(dict(careers_url=URL)), provider)
        self.assertEqual(provider.detect(dict(url=URL))['kind'], 'jd')
        for url in ('http://zhaopin.jd.com/', 'https://zhaopin.jd.com.evil.test/', 'https://evil.test/zhaopin.jd.com',
                    'https://join.jd.com/home', 'https://hr.163.com/'):
            self.assertIsNone(provider.detect(dict(careers_url=url)), url)
        self.assertIsNone(provider.detect({}))

    def test_maps_external_title_body_company_location_and_fallback_link(self):
        server = Server(1)
        result = run(server, discovery_sources=[dict(careers_url=URL, company='京东集团')])
        job = result['jobs'][0]
        self.assertEqual((job['channel'], job['platform_id'], job['title'], job['company'], job['location']),
                         ('jd', '0', '产品经理 0', '京东集团', '北京'))
        self.assertEqual(job['url'], URL + '?id=0')
        self.assertEqual(job['published_at'], '2026-10-27')
        self.assertIn('负责产品规划', job['jd']); self.assertIn('熟悉需求分析', job['jd'])
        self.assertEqual(result['sources'][0]['search_url'], 'https://zhaopin.jd.com/web/job/job_list')

    def test_form_headers_count_and_page_requests(self):
        server = Server(150)
        run(server, sweep=True, sweep_max_jobs=200)
        self.assertEqual([urlsplit(c[0]).path for c in server.calls],
                         ['/web/job/job_count', '/web/job/job_list', '/web/job/job_list'])
        self.assertEqual([c[2]['pageIndex'] for c in server.calls], [['1'], ['1'], ['2']])
        for url, kwargs, form in server.calls:
            self.assertEqual(kwargs['method'], 'POST')
            self.assertEqual(kwargs['headers'], dict(Origin='https://zhaopin.jd.com', Referer=URL,
                                                     **{'Content-Type':'application/x-www-form-urlencoded'}))
            self.assertEqual(form['jobSearch'], ['产品经理'])
            self.assertEqual((form['pageSize'], form['workCityJson'], form['jobTypeJson']), (['100'], ['[]'], ['[]']))

    def test_pagination_stops_at_total(self):
        server = Server()
        report = run(server, sweep=True, sweep_max_jobs=200)['sources'][0]
        self.assertEqual((report['pages'], report['fetched'], report['returned'], report['truncated']), (2,150,150,False))
        self.assertEqual(len(server.calls), 3)

    def test_repeated_page_stops_and_dedupes(self):
        server = Server(350, repeat=True)
        result = run(server, max_jobs=100, max_pages=5)
        report = result['sources'][0]
        self.assertEqual((len(server.calls), report['pages'], report['fetched'], report['returned']), (3,2,200,100))
        self.assertEqual(len({j['platform_id'] for j in result['jobs']}), 100)
        self.assertTrue(report['truncated'])

    def test_limit_and_page_cap_mark_truncated(self):
        report = run(Server(30), max_jobs=10)['sources'][0]
        self.assertEqual((report['returned'],report['truncated']), (10,True))
        report = run(Server(300), max_jobs=100, max_pages=1)['sources'][0]
        self.assertEqual((report['pages'],report['truncated']), (1,True))

    def test_empty_page_stops_before_advertised_total(self):
        calls=[]
        def transport(url, **kwargs):
            calls.append(url)
            return b'300' if url.endswith('/job_count') else b'[]'
        report=run(transport,max_pages=5)['sources'][0]
        self.assertEqual((len(calls),report['status'],report['fetched']), (2,'empty',0))

    def test_empty_count_is_empty(self):
        report=run(Server(0))['sources'][0]
        self.assertEqual((report['status'],report['error']), ('empty',None))

    def test_keywords_each_get_count_and_list_with_cross_keyword_dedup(self):
        server=Server(2)
        result=run(server,keywords=['产品经理','产品负责人'])
        self.assertEqual([c[2]['jobSearch'][0] for c in server.calls], ['产品经理','产品经理','产品负责人','产品负责人'])
        self.assertEqual(len(result['jobs']),2)
        self.assertEqual(result['sources'][0]['fetched'],4)

    def test_sweep_keep_filters_loose_titles_before_limit(self):
        def transport(url,**kwargs):
            if url.endswith('/job_count'): return b'2'
            return json.dumps([post(1,positionNameOpen='软件工程师'),post(2)]).encode()
        result=run(transport,sweep=True,sweep_max_jobs=1)
        self.assertEqual([j['platform_id'] for j in result['jobs']], ['2'])
        self.assertEqual(result['sources'][0]['filtered'],1)

    def test_non_json_and_bad_list_are_parse_error(self):
        for raw in (b'<html>error</html>',b'{}',b'{"data":[]}',b'null'):
            def transport(url,**kwargs): return b'2' if url.endswith('/job_count') else raw
            self.assertEqual(run(transport)['sources'][0]['status'],'parse_error',raw)

    def test_invalid_count_is_parse_error(self):
        for count in (None,True,-1,{},[],2.5,'many'):
            self.assertEqual(run(lambda url,**kw:json.dumps(count).encode())['sources'][0]['status'],'parse_error',count)

    def test_bad_post_is_recorded_and_later_page_kept(self):
        for bad in (None,'oops',{},dict(id='bad',positionNameOpen='产品经理'),post(chr(0xd800))):
            def transport(url,**kwargs):
                if url.endswith('/job_count'): return b'150'
                rows=[post(1),bad] if parse_qs(kwargs['data'].decode())['pageIndex']==['1'] else [post(2)]
                return json.dumps(rows).encode()
            result=run(transport,max_pages=2)
            self.assertEqual([j['platform_id'] for j in result['jobs']],['1','2'])
            self.assertEqual((result['sources'][0]['status'],result['sources'][0]['detail_error_count']),('parse_error',1))

    def test_all_bad_page_is_skipped_without_hiding_later_pages(self):
        calls=[]
        def transport(url,**kwargs):
            calls.append(url)
            if url.endswith('/job_count'): return b'350'
            number=int(parse_qs(kwargs['data'].decode())['pageIndex'][0])
            return json.dumps({1:[post(1)],2:[None,{}],3:[post(2)],4:[]}[number]).encode()
        result=run(transport,max_jobs=100,max_pages=5)
        self.assertEqual([j['platform_id'] for j in result['jobs']],['1','2'])
        self.assertEqual((len(calls),result['sources'][0]['detail_error_count']),(5,2))

    def test_missing_external_title_does_not_use_internal_title(self):
        def transport(url,**kwargs):
            return b'1' if url.endswith('/job_count') else json.dumps([post(1,positionNameOpen='')]).encode()
        report=run(transport)['sources'][0]
        self.assertEqual((report['status'],report['returned']),('parse_error',0))

    def test_fetch_error_and_request_budget_are_reported(self):
        def down(url,**kwargs): raise FetchError('公开抓取超时')
        self.assertEqual(run(down)['sources'][0]['status'],'fetch_error')
        report=run(Server(150),discovery_requests=1)['sources'][0]
        self.assertEqual((report['status'],report['requests']),('budget_exhausted',1))


if __name__ == '__main__': unittest.main()
