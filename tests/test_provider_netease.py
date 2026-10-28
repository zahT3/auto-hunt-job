import json
import unittest
from urllib.parse import urlsplit

from hunt.discovery import discover
from hunt.network import FetchError
from hunt.providers import REGISTRY, route

URL='https://hr.163.com/job-list.html'


def post(n,**fields):
    return dict(dict(id=str(n),name='产品经理 '+str(n),description='负责产品规划',requirement='熟悉需求分析',
                     workPlaceNameList=['杭州','北京'],workType='1'),**fields)


def page(rows,total): return json.dumps(dict(data=dict(list=rows,total=total,pages=(total+99)//100))).encode()


class Server:
    def __init__(self,total=150): self.total,self.calls=total,[]
    def __call__(self,url,**kwargs):
        body=json.loads(kwargs['data']); self.calls.append((url,kwargs,body))
        start=(body['currentPage']-1)*100
        return page([post(n) for n in range(start,min(start+100,self.total))],self.total)


def run(transport,**config):
    return discover(dict(dict(keywords=['产品经理'],discovery_sources=[dict(careers_url=URL)],
                              check_entries=False),**config),transport=transport)


class NeteaseTests(unittest.TestCase):
    def test_detect_routes_only_https_host(self):
        provider=REGISTRY['netease']
        self.assertIs(route(dict(careers_url=URL)),provider)
        self.assertEqual(provider.detect(dict(url=URL))['kind'],'netease')
        for url in ('http://hr.163.com/','https://hr.163.com.evil.test/','https://evil.test/hr.163.com','https://163.com/'):
            self.assertIsNone(provider.detect(dict(careers_url=url)),url)
        self.assertIsNone(provider.detect({}))

    def test_field_mapping_and_explicit_list_id_fallback(self):
        result=run(Server(1),discovery_sources=[dict(careers_url=URL,company='网易集团')])
        job=result['jobs'][0]
        self.assertEqual((job['channel'],job['platform_id'],job['title'],job['company'],job['location']),
                         ('netease','0','产品经理 0','网易集团','杭州、北京'))
        self.assertEqual(job['url'],URL+'?id=0')
        self.assertIn('负责产品规划',job['jd']); self.assertIn('熟悉需求分析',job['jd'])
        self.assertEqual(job['raw']['record']['workType'],'1')
        self.assertEqual(result['sources'][0]['search_url'],'https://hr.163.com/api/hr163/position/queryPage')

    def test_json_headers_timeout_and_page_shape(self):
        server=Server()
        run(server,sweep=True,sweep_max_jobs=200)
        self.assertEqual([c[2]['currentPage'] for c in server.calls],[1,2])
        for url,kwargs,body in server.calls:
            self.assertEqual((urlsplit(url).path,kwargs['method']),('/api/hr163/position/queryPage','POST'))
            self.assertEqual(kwargs['headers'],{'Content-Type':'application/json','Referer':URL,'Origin':'https://hr.163.com'})
            self.assertEqual(kwargs['timeout'],20)
            self.assertEqual((body['keyword'],body['pageSize']),('产品经理',100))

    def test_two_pages_stop_at_total(self):
        server=Server()
        report=run(server,sweep=True,sweep_max_jobs=200)['sources'][0]
        self.assertEqual((len(server.calls),report['pages'],report['fetched'],report['returned'],report['truncated']),
                         (2,2,150,150,False))

    def test_empty_page_stops(self):
        server=Server(0)
        report=run(server,max_pages=5)['sources'][0]
        self.assertEqual((len(server.calls),report['status'],report['error']), (1,'empty',None))
        report=run(lambda url,**kw:page([],500),max_pages=5)['sources'][0]
        self.assertEqual(report['pages'],1)

    def test_limit_and_page_cap_mark_truncated(self):
        report=run(Server(30),max_jobs=10)['sources'][0]
        self.assertEqual((report['returned'],report['truncated']),(10,True))
        report=run(Server(300),max_jobs=100,max_pages=1)['sources'][0]
        self.assertEqual((report['pages'],report['truncated']),(1,True))

    def test_each_keyword_queried_and_deduped(self):
        server=Server(2)
        result=run(server,keywords=['产品经理','产品负责人'])
        self.assertEqual([c[2]['keyword'] for c in server.calls],['产品经理','产品负责人'])
        self.assertEqual((len(result['jobs']),result['sources'][0]['fetched']),(2,4))

    def test_sweep_keep_filters_title_before_limit(self):
        rows=[post(1,name='算法工程师'),post(2)]
        result=run(lambda url,**kw:page(rows,2),sweep=True,sweep_max_jobs=1)
        self.assertEqual([j['platform_id'] for j in result['jobs']],['2'])
        self.assertEqual(result['sources'][0]['filtered'],1)

    def test_structure_and_non_json_errors(self):
        for raw in (b'no json',b'null',b'[]',b'{}',b'{"data":[]}',b'{"data":{"total":1}}'):
            self.assertEqual(run(lambda url,**kw:raw)['sources'][0]['status'],'parse_error',raw)
        for total in (None,True,-1,'many',1.5):
            self.assertEqual(run(lambda url,**kw:page([],total) if isinstance(total,(int,float)) else
                                 json.dumps(dict(data=dict(list=[],total=total))).encode())['sources'][0]['status'],
                             'parse_error',total)

    def test_bad_posts_do_not_drop_rest_or_later_pages(self):
        for bad in (None,'oops',{},post('bad',description='',requirement=''),post('bad',workPlaceNameList={}),post(chr(0xd800))):
            def transport(url,**kwargs):
                return page([post(1),bad] if json.loads(kwargs['data'])['currentPage']==1 else [post(2)],150)
            result=run(transport,max_pages=2)
            self.assertEqual([j['platform_id'] for j in result['jobs']],['1','2'])
            self.assertEqual((result['sources'][0]['status'],result['sources'][0]['detail_error_count']),('parse_error',1))

    def test_requirement_only_is_usable(self):
        result=run(lambda url,**kw:page([post(1,description=None,workPlaceNameList=None)],1))
        self.assertEqual(result['sources'][0]['status'],'ok')
        self.assertEqual((result['jobs'][0]['jd'],result['jobs'][0]['location']),('熟悉需求分析',None))

    def test_work_types_are_preserved_without_filtering(self):
        result=run(lambda url,**kw:page([post(i,workType=i) for i in range(3)],3))
        self.assertEqual([j['raw']['record']['workType'] for j in result['jobs']],[0,1,2])

    def test_timeout_is_fetch_error(self):
        def timeout(url,**kwargs):
            self.assertEqual(kwargs['timeout'],20)
            raise FetchError('公开抓取超时')
        report=run(timeout)['sources'][0]
        self.assertEqual((report['status'],report['error']),('fetch_error','公开抓取超时'))

    def test_request_budget_stops_next_page(self):
        report=run(Server(150),discovery_requests=1,max_jobs=100)['sources'][0]
        self.assertEqual((report['status'],report['requests'],report['fetched']),('budget_exhausted',1,100))


if __name__ == '__main__': unittest.main()
