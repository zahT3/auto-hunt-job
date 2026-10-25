import base64
import builtins
import json
import unittest
from unittest import mock

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from hunt.discovery import discover
from hunt.providers import REGISTRY, route

APP = 'https://app.mokahr.com'
INTL = 'https://hire-r1.mokahr.com'
TENANT = APP + '/social-recruitment/high-flyer/140576'
KEY = '0123456789abcdef'
IV = b'de7c21ed8d6f50fe'


def encrypt(body, key=KEY):
    padder = padding.PKCS7(128).padder()
    padded = padder.update(json.dumps(body, ensure_ascii=False).encode('utf-8')) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key.encode()), modes.CBC(IV)).encryptor()
    return base64.b64encode(encryptor.update(padded) + encryptor.finalize()).decode()


def job(n):
    return dict(id='job-%d' % n, title='产品经理 %d' % n, commitment='全职', department=dict(name='产品部'),
                jobDescription='<p>负责产品规划 %d</p><ul><li>三年以上经验</li></ul>' % n, createdAt='2026-06-23T08:00:00.000Z',
                locations=[dict(provinceName='北京市', cityName='海淀区'), dict(provinceName='浙江', cityName='拱墅区')])


def body_of(jobs):
    return dict(code=0, success=True, data=dict(jobs=jobs, jobStats=dict(total=0)))


def sealed(jobs, key=KEY):
    return json.dumps(dict(data=encrypt(body_of(jobs), key), necromancer=key)).encode()


def plain(jobs):
    return json.dumps(body_of(jobs)).encode()


class Server:
    """Fake transport serving a board of `total` jobs, paged by limit/offset in the POST body."""
    def __init__(self, total, wrap=sealed):
        self.total, self.wrap, self.calls = total, wrap, []

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        body = json.loads(kwargs['data'])
        start = body['offset']
        return self.wrap([job(n) for n in range(start, min(start + body['limit'], self.total))])


def run(transport, url=TENANT, **config):
    entry = dict(kind='mokahr', careers_url=url)
    return discover(dict(dict(keywords=['产品经理'], discovery_sources=[entry], check_entries=False), **config), transport=transport)


class MokahrTests(unittest.TestCase):
    def setUp(self):
        patch = mock.patch('hunt.providers.mokahr.PAUSE', 0)
        patch.start(); self.addCleanup(patch.stop)

    def test_decrypts_envelope(self):
        raw = sealed([job(1), job(2)])
        result = run(lambda url, **kw: raw)
        report = result['sources'][0]
        self.assertEqual((report['status'], report['kind'], report['returned']), ('ok', 'mokahr', 2))
        first = result['jobs'][0]
        self.assertEqual(first['channel'], 'mokahr')
        self.assertEqual(first['platform_id'], '140576:job-1')
        self.assertEqual(first['title'], '产品经理 1')
        self.assertEqual(first['company'], 'high-flyer')
        self.assertEqual(first['url'], TENANT + '#/job/job-1')
        self.assertEqual(first['location'], '北京市 海淀区/浙江 拱墅区')
        self.assertEqual(first['published_at'], '2026-06-23')
        self.assertIn('类型: 全职', first['jd'])
        self.assertIn('部门: 产品部', first['jd'])
        self.assertIn('负责产品规划 1', first['jd'])
        self.assertIn('三年以上经验', first['jd'])
        self.assertNotIn('<p>', first['jd'])

    def test_plaintext_tenant_passthrough(self):
        url = INTL + '/social-recruitment/redotpay/100008889'
        server = Server(2, plain)
        result = run(server, url)
        self.assertEqual((result['sources'][0]['status'], len(result['jobs'])), ('ok', 2))
        self.assertEqual(server.calls[0][0], INTL + '/api/outer/ats-apply/website/jobs/v2')
        self.assertEqual(result['jobs'][0]['url'], url + '#/job/job-0')

    def test_plaintext_needs_no_crypto(self):
        real = builtins.__import__
        def deny(name, *args, **kwargs):
            if name.startswith('cryptography'): raise ImportError(name)
            return real(name, *args, **kwargs)
        with mock.patch('builtins.__import__', deny):
            report = run(Server(1, plain))['sources'][0]
        self.assertEqual((report['status'], report['returned']), ('ok', 1))

    def test_request_shape(self):
        server = Server(1)
        run(server, APP + '/apply/moonshot/148506/')
        url, kwargs = server.calls[0]
        self.assertEqual((url, kwargs['method']), (APP + '/api/outer/ats-apply/website/jobs/v2', 'POST'))
        self.assertEqual({k.lower(): v for k, v in kwargs['headers'].items()}['content-type'], 'application/json')
        self.assertEqual(json.loads(kwargs['data']), dict(siteId=148506, orgId='moonshot', locale='zh-CN', limit=50, offset=0, keyword='产品经理'))

    def test_robots_excluded_paths(self):
        provider = REGISTRY['mokahr']
        for path in ('/social-recruitment/lingjuninvest/46355', '/social-recruitment/shopee/74378', '/social-recruitment/shopee/74378/'):
            self.assertIsNone(provider.detect(dict(careers_url=APP + path)), path)
            server = Server(1)
            report = run(server, APP + path)['sources'][0]
            self.assertEqual((report['status'], len(server.calls)), ('not_configured', 0), path)
        # robots.txt lists exact paths only; other routes of the same org stay allowed.
        self.assertIsNotNone(provider.detect(dict(careers_url=APP + '/social-recruitment/shopee/99999')))
        self.assertIsNotNone(provider.detect(dict(careers_url=APP + '/campus-recruitment/shopee/74378')))

    def test_missing_crypto_dependency_reported(self):
        real = builtins.__import__
        def deny(name, *args, **kwargs):
            if name.startswith('cryptography'): raise ImportError(name)
            return real(name, *args, **kwargs)
        server = Server(1)
        with mock.patch('builtins.__import__', deny):
            report = run(server)['sources'][0]
        self.assertEqual((report['status'], report['returned']), ('not_configured', 0))
        self.assertIn('requirements-sources.txt', report['error'])
        self.assertEqual(len(server.calls), 1)

    def test_pagination_advances_offset_by_50(self):
        server = Server(120)
        report = run(server, max_pages=5, sweep=True)['sources'][0]
        self.assertEqual([json.loads(kw['data'])['offset'] for _, kw in server.calls], [0, 50, 100])
        self.assertEqual((report['pages'], report['fetched'], report['returned'], report['truncated'], report['status']), (3, 120, 120, False, 'ok'))

    def test_exact_multiple_ends_on_empty_page(self):
        server = Server(100)
        report = run(server, max_pages=5, sweep=True)['sources'][0]
        self.assertEqual((len(server.calls), report['returned'], report['truncated']), (3, 100, False))

    def test_page_cap_marks_truncated(self):
        server = Server(300)
        report = run(server, max_pages=2, max_jobs=500)['sources'][0]
        self.assertEqual((len(server.calls), report['fetched']), (2, 100))
        self.assertTrue(report['truncated'])

    def test_limit_marks_truncated(self):
        report = run(Server(30), max_jobs=10)['sources'][0]
        self.assertEqual((report['returned'], report['truncated']), (10, True))

    def test_each_keyword_queried_and_deduped(self):
        keys = []
        def transport(url, **kw):
            keys.append(json.loads(kw['data'])['keyword']); return sealed([job(1), job(2)])
        result = run(transport, keywords=['产品经理', 'AI'], max_jobs=100)
        self.assertEqual(keys, ['产品经理', 'AI'])
        self.assertEqual(len(result['jobs']), 2)

    def test_zero_matches_is_empty_not_error(self):
        report = run(lambda url, **kw: sealed([]))['sources'][0]
        self.assertEqual((report['status'], report['fetched'], report['error']), ('empty', 0, None))

    def test_structure_change_is_parse_error(self):
        changed = (json.dumps(dict(data=encrypt(dict(code=0, success=True, data=dict(positions=[job(1)]))), necromancer=KEY)).encode(),
                   json.dumps(dict(code=0, success=True, data=dict(positions=[job(1)]))).encode(),
                   json.dumps(dict(code=0, success=True, data=[1])).encode(),
                   json.dumps(dict(result='ok')).encode(),
                   json.dumps([1]).encode())
        for raw in changed:
            report = run(lambda url, **kw: raw)['sources'][0]
            self.assertEqual(report['status'], 'parse_error', raw)
            self.assertIn('Moka', report['error'])

    def test_undecryptable_is_parse_error(self):
        good = json.loads(sealed([job(1)]))
        for envelope in (dict(good, necromancer='short'), dict(good, necromancer='fedcba9876543210'), dict(good, data='!!not base64!!'),
                         dict(good, data=base64.b64encode(b'x' * 15).decode()), dict(data=good['data']), dict(good, necromancer=5)):
            report = run(lambda url, **kw: json.dumps(envelope).encode())['sources'][0]
            self.assertEqual(report['status'], 'parse_error', envelope)
            self.assertIn('Moka', report['error'])

    def test_non_json_is_parse_error(self):
        report = run(lambda url, **kw: b'<html>maintenance</html>')['sources'][0]
        self.assertEqual(report['status'], 'parse_error')

    def test_api_error_is_fetch_error(self):
        raw = json.dumps(dict(code=102, success=False, msg='参数错误。{0}')).encode()
        report = run(lambda url, **kw: raw)['sources'][0]
        self.assertEqual(report['status'], 'fetch_error')
        self.assertIn('参数错误', report['error'])

    def test_bad_post_is_reported_and_rest_kept(self):
        for bad in (dict(title='产品经理', jobDescription='负责产品'), 'oops', dict(id='7', title=''), dict(id='8', jobDescription='无名称'), None,
                    dict(job(9), commitment=None, department=None, jobDescription=''), dict(job(9), commitment=None, department=None, jobDescription=None)):
            pages = [sealed([job(1), bad] + [job(n) for n in range(2, 50)]), sealed([job(60)])]
            urls = []
            def transport(url, **kw):
                urls.append(url); return pages[len(urls) - 1]
            result = run(transport, max_pages=2, max_jobs=100)
            report = result['sources'][0]
            self.assertEqual(result['jobs'][0]['platform_id'], '140576:job-1', bad)
            self.assertEqual(result['jobs'][-1]['platform_id'], '140576:job-60', bad)
            self.assertEqual((report['status'], len(urls), len(report['detail_errors'])), ('parse_error', 2, 1), bad)
            self.assertIn('1 个岗位详情无法解析', report['error'])

    def test_bad_post_identity_recorded(self):
        raw = sealed([job(1), dict(id='7', title='')])
        self.assertEqual(run(lambda url, **kw: raw)['sources'][0]['detail_errors'][0]['platform_id'], '7')

    def test_unencodable_id_is_skipped(self):
        raw = plain([job(1), dict(job(2), id='\ud800')])
        result = run(lambda url, **kw: raw)
        self.assertEqual([j['platform_id'] for j in result['jobs']], ['140576:job-1'])
        self.assertEqual(len(result['sources'][0]['detail_errors']), 1)

    def test_created_at_needs_explicit_zone(self):
        cases = {'2026-06-23T08:00:00Z': '2026-06-23', '2026-06-23T20:00:00+00:00': '2026-06-24', '2026-06-23T08:00:00': None,
                 '': None, None: None, 12: None, 'soon': None}
        for value, expected in cases.items():
            raw = sealed([dict(job(1), createdAt=value)])
            self.assertEqual(run(lambda url, **kw: raw)['jobs'][0]['published_at'], expected, value)

    def test_missing_optional_fields_ok(self):
        raw = sealed([dict(id='5', title='产品经理', jobDescription='负责产品')])
        item = run(lambda url, **kw: raw)['jobs'][0]
        self.assertEqual((item['jd'], item['location'], item['published_at']), ('负责产品', None, None))

    def test_company_from_entry(self):
        raw = sealed([job(1)])
        result = discover(dict(keywords=['产品经理'], check_entries=False,
                               discovery_sources=[dict(careers_url=TENANT, company='DeepSeek')]), transport=lambda url, **kw: raw)
        self.assertEqual((result['sources'][0]['kind'], result['jobs'][0]['company']), ('mokahr', 'DeepSeek'))

    def test_invalid_url_on_explicit_kind_is_not_configured(self):
        for url in ('https://evil.test/social-recruitment/a/1', APP + '/social-recruitment/a', 'http://app.mokahr.com/apply/a/1', APP):
            server = Server(1)
            report = run(server, url)['sources'][0]
            self.assertEqual((report['status'], len(server.calls)), ('not_configured', 0), url)

    def test_detect(self):
        provider = REGISTRY['mokahr']
        for url in (TENANT, TENANT + '/', APP + '/apply/moonshot/148506', APP + '/campus-recruitment/zphz/148983',
                    INTL + '/social-recruitment/redotpay/100008889', 'https://APP.mokahr.com/apply/a/1'):
            hit = provider.detect(dict(careers_url=url))
            self.assertEqual(hit['kind'], 'mokahr', url)
            self.assertIs(route(dict(careers_url=url)), provider, url)
        for url in ('http://app.mokahr.com/apply/a/1', 'https://mokahr.com/apply/a/1', 'https://app.mokahr.com.evil.test/apply/a/1',
                    'https://hire-r1-ats.mokahr.com/apply/a/1', 'https://evil.mokahr.com/apply/a/1', 'https://evil.test/app.mokahr.com/apply/a/1',
                    'https://user@app.mokahr.com.evil.test/apply/a/1', 'https://user@app.mokahr.com/apply/a/1', 'https://app.mokahr.com:8443/apply/a/1',
                    APP, APP + '/apply/a', APP + '/apply/a/0', APP + '/apply/a/x', APP + '/apply/a/1/extra', APP + '/jobs/a/1',
                    APP + '/apply//1', APP + '/apply/a/%31'):
            self.assertIsNone(provider.detect(dict(careers_url=url)), url)
        self.assertIsNone(provider.detect(dict()))
        self.assertIsNone(provider.detect(dict(careers_url=None)))


if __name__ == '__main__':
    unittest.main()
