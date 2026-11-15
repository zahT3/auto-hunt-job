"""miHoYo reader on synthetic fixtures; no live requests."""
import json
import unittest
from pathlib import Path
from unittest import mock

from hunt.net.network import FetchError
from hunt.search.engine import discover
from hunt.search.sources import REGISTRY, route, mihoyo

FIXTURES = Path(__file__).parent / 'fixtures' / 'providers'


def raw(name):
    return (FIXTURES / name).read_bytes()


def info_for(ident):
    data = json.loads(raw('mihoyo-info.json'))
    data['data']['id'] = ident
    return json.dumps(data, ensure_ascii=False).encode()


class Server:
    def __init__(self, list_raw, info=info_for):
        self.list_raw, self.info, self.calls = list_raw, info, []

    def __call__(self, url, **kwargs):
        self.calls.append((url, json.loads(kwargs['data'])))
        if url == mihoyo.LIST_URL: return self.list_raw
        if url == mihoyo.INFO_URL: return self.info(json.loads(kwargs['data'])['id'])
        raise AssertionError(url)


def run(transport, **config):
    entry = dict(kind='mihoyo', careers_url='https://jobs.mihoyo.com/')
    return discover(dict(dict(keywords=['产品经理'], discovery_sources=[entry], check_entries=False), **config), transport=transport)


class MihoyoTests(unittest.TestCase):
    def setUp(self):
        p = mock.patch('hunt.search.sources.mihoyo.PAUSE', 0)
        p.start(); self.addCleanup(p.stop)

    def test_first_page_filters_locally_and_reads_detail_only_for_matches(self):
        server = Server(raw('mihoyo-page1.json'))
        result = run(server)
        report = result['sources'][0]
        self.assertEqual((report['status'], report['kind'], report['returned']), ('ok', 'mihoyo', 1))
        job = result['jobs'][0]
        self.assertEqual((job['platform_id'], job['title'], job['location']), ('9000', 'AI 产品经理（示例）', '上海'))
        self.assertIn('岗位职责', job['jd'])
        self.assertIn('任职要求', job['jd'])
        self.assertEqual(job['url'], 'https://jobs.mihoyo.com/position/9000')
        self.assertEqual([c[0] for c in server.calls], [mihoyo.LIST_URL, mihoyo.INFO_URL])
        self.assertEqual(server.calls[0][1]['hireType'], 0)

    def test_empty_board_is_ok_with_no_jobs(self):
        result = run(Server(raw('mihoyo-empty.json')))
        self.assertEqual((result['sources'][0]['status'], result['jobs']), ('empty', []))

    def test_changed_structure_is_parse_error(self):
        self.assertEqual(run(Server(raw('mihoyo-changed.json')))['sources'][0]['status'], 'parse_error')

    def test_detail_without_text_is_recorded_not_fatal(self):
        empty = lambda ident: json.dumps(dict(code=0, data=dict(id=ident, description='', jobRequire=''))).encode()
        result = run(Server(raw('mihoyo-page1.json'), empty))
        self.assertEqual(result['jobs'], [])
        self.assertEqual(result['sources'][0]['status'], 'parse_error')

    def test_api_error_code_is_fetch_error(self):
        body = json.dumps(dict(code=-3, message='用户未登录或登录失效')).encode()
        self.assertEqual(run(Server(body))['sources'][0]['status'], 'fetch_error')

    def test_http_429_is_reported_as_blocked(self):
        def limited(url, **kw): raise FetchError('HTTP 429 Too Many Requests')
        self.assertEqual(run(limited)['sources'][0]['status'], 'blocked')

    def test_detect(self):
        provider = REGISTRY['mihoyo']
        for url in ('https://jobs.mihoyo.com/', 'https://jobs.mihoyo.com/position/1'):
            self.assertIs(route(dict(careers_url=url)), provider, url)
        for url in ('http://jobs.mihoyo.com/', 'https://jobs.mihoyo.com.evil.test/', 'https://www.mihoyo.com/'):
            self.assertIsNone(provider.detect(dict(careers_url=url)), url)


if __name__ == '__main__':
    unittest.main()
