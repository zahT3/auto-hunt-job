"""Bookmarklet sources, javascript: URL builds and the same-origin install page."""
import http.client
import json
import re
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.parse import quote, unquote, urlencode

from hunt import bookmarklets
from hunt.core import Store
from hunt.server import make_server

NAMES = ('boss-zhipin', 'liepin', 'lagou', 'mokahr', 'universal')
BOSS = 'https://www.zhipin.com'
FORM = 'application/x-www-form-urlencoded'


class BuildCase(unittest.TestCase):
    def test_build_produces_javascript_urls(self):
        for name in NAMES:
            with self.subTest(name=name):
                built = bookmarklets.build(name)
                self.assertTrue(built.startswith('javascript:'))
                self.assertLess(len(built), 64 * 1024)
                self.assertIn('__INBOX_URL__', built)
                self.assertIn('__INBOX_TOKEN__', built)

    def test_no_alert_calls(self):
        for name in NAMES:
            with self.subTest(name=name):
                self.assertNotIn('alert(', bookmarklets.source(name))
                self.assertNotIn('alert(', unquote(bookmarklets.build(name)))

    def test_every_source_keeps_the_upstream_notice(self):
        for name in NAMES:
            head = bookmarklets.source(name).split('\n\n')[0]
            with self.subTest(name=name):
                self.assertIn('shuheng-mo/career-ops-china', head)
                self.assertIn('bef1e7122d2d84a0bf7137a9d5ffb88808d05c5c', head)
                self.assertIn('MIT License', head)

    def test_sources_hold_no_secret_or_fixed_address(self):
        for name in NAMES:
            text = bookmarklets.source(name)
            with self.subTest(name=name):
                self.assertNotIn('8787', text)
                self.assertNotRegex(text, r'127\.0\.0\.1|localhost')

    def test_render_fills_placeholders_with_decodable_values(self):
        url = 'http://127.0.0.1:8771/api/inbox'
        rendered = bookmarklets.render('universal', url, 'tok_en-123')
        code = unquote(rendered)
        self.assertNotIn('__INBOX', rendered)
        self.assertIn("const INBOX_URL = '%s';" % url, code)
        self.assertIn("const INBOX_TOKEN = 'tok_en-123';", code)

    def test_render_refuses_values_that_could_break_out_of_the_string(self):
        with self.assertRaises(ValueError):
            bookmarklets.render('universal', 'http://127.0.0.1:1/api/inbox', "x';alert(1);'")
        with self.assertRaises(ValueError):
            bookmarklets.render('universal', "http://127.0.0.1:1/api/inbox';x='", 'abc')

    def test_build_drops_comments_but_keeps_code(self):
        code = unquote(bookmarklets.build('boss-zhipin'))
        self.assertNotIn('Ported from', code)
        self.assertIn('document.body.innerText', code)


class PageCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'app')
        self.server = make_server(self.store, 0)
        self.port = self.server.server_port
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.token = self.store.inbox_token()

    def call(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return response.status, response.read(), response
        finally:
            connection.close()

    def page(self, **headers):
        status, data, response = self.call('GET', '/bookmarklets', headers=headers)
        return status, data.decode('utf-8'), response

    def csrf(self):
        text = self.page()[1]
        return re.search(r'name="csrf" value="([^"]+)"', text).group(1)

    def reset(self, csrf='ok', origin='ok', ctype=FORM, host=None):
        headers = {}
        if csrf == 'ok': csrf = self.csrf()
        if origin == 'ok': origin = 'http://127.0.0.1:%d' % self.port
        if origin is not None: headers['Origin'] = origin
        if ctype: headers['Content-Type'] = ctype
        if host: headers['Host'] = host
        body = urlencode({} if csrf is None else {'csrf': csrf}).encode()
        return self.call('POST', '/bookmarklets/reset', body, headers)

    def inbox(self, token):
        body = json.dumps(dict(platform='universal', url='https://careers.example.com/jobs/1', page_title='后端工程师',
                               extracted=dict(job_title='后端工程师', raw_text='负责服务端开发，熟悉 Python。'))).encode()
        status, data, _ = self.call('POST', '/api/inbox', body, {'Origin': 'https://careers.example.com', 'X-Inbox-Token': token,
                                                                'Content-Type': 'application/json'})
        return status

    def test_install_page_injects_token_same_origin_only(self):
        status, text, response = self.page()
        self.assertEqual(status, 200)
        self.assertIn('text/html', response.getheader('Content-Type'))
        self.assertIn(self.token, text)
        self.assertIn(quote('http://127.0.0.1:%d/api/inbox' % self.port, safe=''), text)
        self.assertEqual(self.page(Origin='http://127.0.0.1:%d' % self.port)[0], 200)
        for origin in ('https://evil.example', 'null', 'http://127.0.0.1:1'):
            with self.subTest(origin=origin):
                status, text, _ = self.page(Origin=origin)
                self.assertEqual(status, 403)
                self.assertNotIn(self.token, text)
        status, text, _ = self.page(Host='evil.example:%d' % self.port)
        self.assertEqual(status, 403)
        self.assertNotIn(self.token, text)

    def test_page_lists_five_draggable_links_and_works_under_the_csp(self):
        status, text, response = self.page()
        links = re.findall(r'<a [^>]*class="bm-link"[^>]*href="(javascript:[^"]+)"', text)
        self.assertEqual(len(links), 5)
        for link in links:
            self.assertNotIn('__INBOX', link)
        self.assertNotIn('<script', text)
        self.assertNotIn(' style=', text)
        self.assertNotIn(' onclick=', text)
        self.assertIn("script-src 'self'", response.getheader('Content-Security-Policy'))
        self.assertEqual(response.headers.get_all('Referrer-Policy'), ['same-origin'])
        self.assertEqual(self.call('GET', '/')[2].headers.get_all('Referrer-Policy'), ['no-referrer'])

    def test_page_warns_that_reset_invalidates_installed_bookmarklets(self):
        text = self.page()[1]
        self.assertIn('重置令牌', text)
        self.assertRegex(text, r'已经?安装.{0,20}失效|失效.{0,30}重新')

    def test_reset_replaces_the_token_and_the_old_one_stops_working_at_once(self):
        self.assertEqual(self.inbox(self.token), 200)
        status, _, response = self.reset()
        self.assertEqual(status, 303)
        self.assertEqual(response.getheader('Location'), '/bookmarklets')
        fresh = self.store.inbox_token()
        self.assertNotEqual(fresh, self.token)
        self.assertEqual(self.inbox(self.token), 403)
        self.assertEqual(self.inbox(fresh), 200)
        self.assertIn(fresh, self.page()[1])
        self.assertNotIn(self.token, self.page()[1])

    def test_reset_requires_same_origin_and_the_page_csrf_token(self):
        cases = dict(missing_csrf=dict(csrf=None), wrong_csrf=dict(csrf='nope'), no_origin=dict(origin=None),
                     cross_site=dict(origin='https://evil.example'), null_origin=dict(origin='null'),
                     other_host=dict(host='evil.example:%d' % self.port), wrong_type=dict(ctype='text/plain'))
        for name, kw in cases.items():
            with self.subTest(case=name):
                status = self.reset(**kw)[0]
                self.assertIn(status, (400, 403, 415))
                self.assertEqual(self.store.inbox_token(), self.token)
                self.assertEqual(self.inbox(self.token), 200)

    def test_reset_is_post_only_and_not_a_get(self):
        self.assertEqual(self.call('GET', '/bookmarklets/reset')[0], 404)


if __name__ == '__main__':
    unittest.main()
