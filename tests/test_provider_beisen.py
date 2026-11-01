import json
import unittest

from hunt.search.engine import discover
from hunt.search.sources import REGISTRY, route

URL = 'https://njzq.zhiye.com/social'


def post(n, **fields):
    return dict(dict(Id='0000000%d-aaaa-bbbb-cccc-dddddddddddd' % n, JobAdId=230000000 + n, JobAdName='投行项目审核岗 %d' % n,
                     Duty='负责投行项目质量控制', Require='5年以上投行经验', LocNames=['南京市'], PostDate='2026-10-20T00:00:00'), **fields)


class Server:
    """Fake 北森 tenant: PageIndex is 0-based; KeyWords filters titles like the real search."""
    def __init__(self, posts):
        self.posts, self.calls = posts, []

    def __call__(self, url, **kwargs):
        body = json.loads(kwargs['data'])
        self.calls.append((url, kwargs, body))
        hits = [p for p in self.posts if body['KeyWords'] in (p['JobAdName'] or body['KeyWords'])]  # broken rows still come back
        start = body['PageIndex'] * body['PageSize']
        return json.dumps(dict(Code=200, Count=len(hits), Data=hits[start:start + body['PageSize']])).encode()


def run(transport, **config):
    return discover(dict(dict(keywords=['审核'], discovery_sources=[dict(careers_url=URL, company='南京证券')],
                              check_entries=False), **config), transport=transport)


class BeisenTests(unittest.TestCase):
    def test_detects_tenant_hosts_only(self):
        provider = REGISTRY['beisen']
        self.assertIs(route(dict(careers_url=URL)), provider)
        self.assertEqual(provider.detect(dict(url='https://chinalife.zhiye.com/custom/social?hideMenu=1'))['kind'], 'beisen')
        for url in ('http://njzq.zhiye.com/', 'https://zhiye.com/', 'https://portal-oss.zhiye.com/x.png',
                    'https://njzq.zhiye.com.evil.test/', 'https://evil.test/njzq.zhiye.com'):
            self.assertIsNone(provider.detect(dict(careers_url=url)), url)

    def test_request_shape_and_job_mapping(self):
        server = Server([post(1)])
        result = run(server)
        url, kwargs, body = server.calls[0]
        self.assertEqual(url, 'https://njzq.zhiye.com/api/Jobad/GetJobAdPageList')
        self.assertEqual(kwargs['method'], 'POST')
        self.assertEqual(kwargs['headers']['Content-Type'], 'application/json')
        self.assertEqual(body, dict(PageIndex=0, PageSize=100, KeyWords='审核', SpecialType=0, PortalId=''))
        job = result['jobs'][0]
        self.assertEqual((job['channel'], job['platform_id'], job['title'], job['company'], job['location']),
                         ('beisen', '00000001-aaaa-bbbb-cccc-dddddddddddd', '投行项目审核岗 1', '南京证券', '南京市'))
        self.assertEqual(job['url'], 'https://njzq.zhiye.com/social/detail?jobAdId=00000001-aaaa-bbbb-cccc-dddddddddddd')
        self.assertIn('质量控制', job['jd']); self.assertIn('5年以上', job['jd'])
        self.assertEqual(job['published_at'], '2026-10-20')

    def test_placeholder_date_and_empty_location(self):
        job = run(Server([post(1, PostDate='0001-01-01T00:00:00', LocNames=[])]))['jobs'][0]
        self.assertIsNone(job['published_at'])
        self.assertIsNone(job['location'])

    def test_pages_until_count(self):
        server = Server([post(n) for n in range(150)])
        result = run(server, sweep=True, sweep_max_jobs=500)
        self.assertEqual(len(result['jobs']), 150)
        self.assertEqual([c[2]['PageIndex'] for c in server.calls], [0, 1])

    def test_bad_structure_is_parse_error_and_bad_post_is_skipped(self):
        broken = lambda url, **kw: json.dumps(dict(Code=200, Count='x', Data=None)).encode()
        self.assertEqual(run(broken)['sources'][0]['status'], 'parse_error')
        result = run(Server([post(1), post(2, JobAdName=None)]))
        self.assertEqual([j['platform_id'] for j in result['jobs']], ['00000001-aaaa-bbbb-cccc-dddddddddddd'])
        self.assertEqual(result['sources'][0]['detail_error_count'], 1)


if __name__ == '__main__':
    unittest.main()
