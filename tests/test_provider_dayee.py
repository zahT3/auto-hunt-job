import json
import unittest
from urllib.parse import parse_qs, urlsplit

from hunt.search.engine import discover
from hunt.search.sources import REGISTRY, route

URL = 'https://crc.wintalent.cn/wt/crcbank/web/index?brandCode=1'


def post(n, **fields):
    return dict(dict(postId=1000 + n, postIdToken='%016x' % (0xabc000 + n), postName='客户经理 %d' % n, workPlace='深圳市',
                     orgName='华润银行', workContent='负责对公客户开发', serviceCondition='3年以上银行经验', publishDate='2026-10-20'), **fields)


class Server:
    """Fake 大易 tenant: 1-based `page`, `rowSize` capped like the real server, keyWord filters titles."""
    def __init__(self, posts, cap=50):
        self.posts, self.cap, self.calls = posts, cap, []

    def __call__(self, url, **kwargs):
        q = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
        self.calls.append((url, kwargs, q))
        hits = [p for p in self.posts if q.get('keyWord', '') in (p['postName'] or q.get('keyWord', ''))]
        size = min(int(q['rowSize']), self.cap)
        start = (int(q['page']) - 1) * size
        pages = max(1, -(-len(hits) // size))
        return json.dumps(dict(page=int(q['page']), rowSize=size, rowCount=len(hits), pageCount=pages, postList=hits[start:start + size])).encode()


def run(transport, **config):
    return discover(dict(dict(keywords=['客户经理'], discovery_sources=[dict(careers_url=URL, company='华润银行')],
                              check_entries=False), **config), transport=transport)


class DayeeTests(unittest.TestCase):
    def test_detects_tenants_on_both_domains(self):
        provider = REGISTRY['dayee']
        self.assertIs(route(dict(careers_url=URL)), provider)
        for url in ('https://hotjob.cn/wt/cifi/web/index/social?brandCode=1', 'https://wanda.hotjob.cn/wt/wanda/web/index',
                    'https://www.hotjob.cn/wt/CT/web/index'):
            self.assertEqual(provider.detect(dict(careers_url=url))['kind'], 'dayee', url)
        for url in ('http://hotjob.cn/wt/cifi/web/index', 'https://hotjob.cn/', 'https://crc.wintalent.cn/', 'https://hztp.hotjob.cn/wt/javascript/x.js',
                    'https://hotjob.cn.evil.test/wt/x/web/index', 'https://evil.test/wt/cifi/web/index'):
            self.assertIsNone(provider.detect(dict(careers_url=url)), url)

    def test_request_shape_and_job_mapping(self):
        server = Server([post(1)])
        result = run(server)
        url, kwargs, q = server.calls[0]
        self.assertEqual(urlsplit(url).path, '/wt/crcbank/web/json/position/list')
        self.assertEqual({k: q[k] for k in ('brandCode', 'recruitType', 'page', 'rowSize', 'keyWord')},
                         dict(brandCode='1', recruitType='2', page='1', rowSize='50', keyWord='客户经理'))
        job = result['jobs'][0]
        self.assertEqual((job['channel'], job['platform_id'], job['title'], job['company'], job['location']),
                         ('dayee', 'crcbank:1001', '客户经理 1', '华润银行', '深圳市'))
        self.assertEqual(job['url'], 'https://crc.wintalent.cn/wt/crcbank/web/index/webPositionN310!getOnePosition?'
                                     'postIdEnc=0000000000abc001&recruitType=2&brandCode=1')
        self.assertIn('对公客户', job['jd']); self.assertIn('3年以上', job['jd'])
        self.assertEqual(job['published_at'], '2026-10-20')

    def test_html_breaks_in_text_become_lines(self):
        job = run(Server([post(1, workContent='1.开发客户；<br>2.维护关系')]))['jobs'][0]
        self.assertIn('1.开发客户；\n2.维护关系', job['jd'])

    def test_pages_follow_the_servers_page_count_even_when_it_caps_lower(self):
        server = Server([post(n) for n in range(75)], cap=30)  # asks for 50, gets 30 a page
        result = run(server, sweep=True, sweep_max_jobs=500)
        self.assertEqual(len(result['jobs']), 75)
        self.assertEqual([c[2]['page'] for c in server.calls], ['1', '2', '3'])

    def test_bad_structure_is_parse_error_and_bad_post_is_skipped(self):
        broken = lambda url, **kw: json.dumps(dict(postList='x', pageCount=1)).encode()
        self.assertEqual(run(broken)['sources'][0]['status'], 'parse_error')
        result = run(Server([post(1), post(2, postName=None)]))
        self.assertEqual([j['platform_id'] for j in result['jobs']], ['crcbank:1001'])
        self.assertEqual(result['sources'][0]['detail_error_count'], 1)


if __name__ == '__main__':
    unittest.main()
