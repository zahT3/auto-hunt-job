"""Bookmarklet sources, javascript: URL builds and the same-origin install page."""
import http.client
import json
import re
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.parse import quote, unquote, urlencode

from hunt.app import bookmarklets
from hunt.app.store import Store
from hunt.app.server import make_server

NAMES = ('boss-zhipin', 'liepin', 'liepin-list', 'lagou', 'mokahr', 'universal')
PORTED = ('boss-zhipin', 'liepin', 'lagou', 'mokahr', 'universal')  # liepin-list was written here
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
                self.assertNotIn('alert(', bookmarklets.assemble(name))
                self.assertNotIn('alert(', unquote(bookmarklets.build(name)))

    def test_every_source_keeps_the_upstream_notice(self):
        for name in PORTED:
            head = bookmarklets.source(name).split('\n\n')[0]
            with self.subTest(name=name):
                self.assertIn('shuheng-mo/career-ops-china', head)
                self.assertIn('bef1e7122d2d84a0bf7137a9d5ffb88808d05c5c', head)
                self.assertIn('MIT License', head)

    def test_every_built_bookmarklet_contains_the_shared_prelude_exactly_once(self):
        prelude = bookmarklets.minify(bookmarklets.prelude())
        self.assertIn('const deliver = async', prelude)
        for name in NAMES:
            code = unquote(bookmarklets.build(name))
            with self.subTest(name=name):
                self.assertEqual(code.count(prelude), 1)
                self.assertEqual(code.count('const toast ='), 1)
                self.assertEqual(code.count('const deliver ='), 1)
                self.assertNotIn('@deliver', code)
                self.assertEqual(bookmarklets.source(name).count('// @deliver'), 1)
                self.assertNotIn('const deliver', bookmarklets.source(name))

    def test_prelude_keeps_the_upstream_notice(self):
        head = bookmarklets.prelude().split('\n\n')[0]
        self.assertIn('bef1e7122d2d84a0bf7137a9d5ffb88808d05c5c', head)
        self.assertIn('MIT License', head)

    def test_boss_does_not_swallow_page_mouse_events(self):
        self.assertNotIn('mousedown', bookmarklets.assemble('boss-zhipin'))

    def test_sources_hold_no_secret_or_fixed_address(self):
        for name in NAMES:
            text = bookmarklets.assemble(name)
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

    def test_page_lists_every_draggable_links_and_works_under_the_csp(self):
        status, text, response = self.page()
        links = re.findall(r'<a [^>]*class="bm-link"[^>]*href="(javascript:[^"]+)"', text)
        self.assertEqual(len(links), len(NAMES))
        for link in links:
            self.assertNotIn('__INBOX', link)
        self.assertNotIn('<script', text)
        self.assertNotIn(' style=', text)
        self.assertNotIn(' onclick=', text)
        self.assertIn("script-src 'self'", response.getheader('Content-Security-Policy'))
        self.assertEqual(response.headers.get_all('Referrer-Policy'), ['same-origin'])
        self.assertEqual(self.call('GET', '/')[2].headers.get_all('Referrer-Policy'), ['no-referrer'])

    def test_page_says_plainly_who_can_see_the_token(self):
        text = self.page()[1]
        self.assertIn('能看到令牌', text)
        self.assertIn('只能往工作台里添加', text)
        self.assertNotIn('证明请求来自你装的书签', text)

    def test_page_is_linked_from_the_workbench_and_readme(self):
        root = Path(__file__).resolve().parent.parent
        self.assertIn('href="/bookmarklets"', (root / 'static' / 'index.html').read_text(encoding='utf-8'))
        self.assertIn('/bookmarklets', (root / 'README.md').read_text(encoding='utf-8'))

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


# A stand-in for BOSS's list page: a Vue-2-like component on the list container, whose jobList and jobDetail are
# reactive properties proxied onto the instance the way Vue 2 does it. userOpens / userTurnsPage stand for the
# page's own handlers running after the user clicks a card or the pager; the bookmarklet never calls them.
VUE_FIXTURE = '''<!doctype html><html><head><meta charset="utf-8"><title>Python 岗位 - BOSS直聘</title></head><body>
<div id="wrap"><div class="page-job-wrapper"><ul class="job-list"><li class="job-card">合成卡片</li></ul></div></div>
<script>
const item = (n, extra) => Object.assign({encryptJobId: 'job' + n, securityId: 'sec' + n, lid: 'lid' + n,
  jobName: '合成岗位 ' + n, salaryDesc: '20-30K', brandName: '合成公司 ' + n, cityName: '上海', areaDistrict: '浦东新区',
  jobExperience: '3-5年', jobDegree: '本科', skills: ['Python', 'SQL'], goldHunter: n === 2 ? 1 : 0,
  lastModifyTime: 1762300000000 + n, bossName: '招聘者' + n, bossTitle: 'HR', bossOnline: true}, extra || {});
const PAGE1 = [item(1), item(2), item(3)], PAGE2 = [item(4), item(5)];
const detail = (n) => ({lid: 'lid' + n, securityId: 'sec' + n,
  jobInfo: {encryptId: 'job' + n, jobName: '合成岗位 ' + n, salaryDesc: '20-30K', experienceName: '3-5年', degreeName: '本科',
    locationName: '上海', showSkills: ['Python'], postDescription: '岗位职责：负责合成岗位 ' + n + ' 的后端开发。任职要求：熟悉 Python。'},
  bossInfo: {name: '招聘者' + n, title: 'HR', activeTimeDesc: '本周活跃'}, brandComInfo: {brandName: '合成公司 ' + n}});
function component(data) {
  const vm = {_data: data};
  for (const key of Object.keys(data))
    Object.defineProperty(vm, key, {configurable: true, enumerable: true,
      get() { return this._data[key]; }, set(v) { this._data[key] = v; }});
  return vm;
}
const vm = component({jobList: PAGE1, jobDetail: {}});
document.querySelector('.page-job-wrapper').__vue__ = vm;
window.userOpens = (n) => { vm.jobDetail = detail(n); };
window.userTurnsPage = () => { vm.jobList = PAGE2; };
</script></body></html>'''

# The old page shape, with no component data at all: the bookmarklet must fall back to reading the page text.
DOM_FIXTURE = '''<!doctype html><html><head><meta charset="utf-8"><title>合成后端工程师 - BOSS直聘</title></head><body>
<div class="job-banner"><div class="name"><h1>合成后端工程师</h1></div><span class="salary">25-35K</span>
<div class="company-info"><a class="name">合成文字公司</a></div></div>
<div class="job-detail-section">岗位职责：维护合成服务。任职要求：熟悉 Go。</div></body></html>'''


class BossVueFixtureTests(unittest.TestCase):
    """The BOSS bookmarklet in a real browser against synthetic pages served as https://www.zhipin.com."""

    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
            cls.runtime = sync_playwright().start()
            # A real user's Chrome asks once before a site may reach 127.0.0.1 (Local Network Access); a test cannot
            # answer that prompt, so the check is switched off here.
            cls.browser = cls.runtime.chromium.launch(headless=True, args=['--disable-features=LocalNetworkAccessChecks'])
        except Exception as exc:
            if hasattr(cls, 'runtime'): cls.runtime.stop()
            raise unittest.SkipTest('Browser fixture unavailable: ' + str(exc))

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.runtime.stop()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'app')
        self.server = make_server(self.store, 0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.code = unquote(bookmarklets.render('boss-zhipin', 'http://127.0.0.1:%d/api/inbox' % self.server.server_port,
                                                self.store.inbox_token()))[len('javascript:'):]
        self.requests = []

    def open(self, html):
        context = self.browser.new_context(service_workers='block')
        self.addCleanup(context.close)
        # Only the fixture page is served for zhipin.com; any other zhipin.com request (an API call) is recorded and refused.
        def route(r):
            if r.request.url == BOSS + '/web/geek/job?query=python': r.fulfill(status=200, content_type='text/html; charset=utf-8', body=html)
            else:
                self.requests.append(r.request.url)
                r.abort()
        context.route(BOSS + '/**', route)
        page = context.new_page()
        page.goto(BOSS + '/web/geek/job?query=python')
        return page

    def jobs(self):
        return {j['url']: j for j in self.store.state()['jobs']}

    def wait_for(self, page, test):
        for _ in range(50):
            if test(): return
            page.wait_for_timeout(100)
        self.fail('timed out')

    def toast(self, page):
        return page.evaluate("document.getElementById('__hunt_toast') && document.getElementById('__hunt_toast').textContent") or ''

    def test_list_mode_sends_the_whole_page_as_list_only_records(self):
        page = self.open(VUE_FIXTURE)
        page.evaluate(self.code)
        self.wait_for(page, lambda: len(self.jobs()) == 3)
        jobs = self.jobs()
        job = jobs[BOSS + '/job_detail/job2.html']
        self.assertEqual((job['title'], job['company'], job['salary'], job['experience']), ('合成岗位 2', '合成公司 2', '20-30K', '3-5年'))
        self.assertIs(job['raw']['summary_only'], True)
        self.assertEqual(job['raw']['capture'], 'list')
        self.assertEqual(job['raw']['structured']['goldHunter'], 1)
        self.assertEqual(job['raw']['source_modified'], dict(field='lastModifyTime', value=1762300000002))
        self.assertIsNone(job['published_at'])
        self.assertIn('不含职位描述', job['jd'])
        self.assertNotIn('招聘者', json.dumps(self.store.state()['jobs'], ensure_ascii=False))
        self.wait_for(page, lambda: '本页 3 个岗位' in self.toast(page))
        self.assertEqual(self.requests, [])

    def test_the_users_own_card_click_and_page_turn_are_received_passively(self):
        page = self.open(VUE_FIXTURE)
        page.evaluate(self.code)
        self.wait_for(page, lambda: len(self.jobs()) == 3)
        page.evaluate('userOpens(1)')
        self.wait_for(page, lambda: '负责合成岗位 1' in self.jobs()[BOSS + '/job_detail/job1.html']['jd'])
        job = self.jobs()[BOSS + '/job_detail/job1.html']
        self.assertNotIn('summary_only', job['raw'])
        self.assertEqual(job['raw']['structured']['bossActiveTimeDesc'], '本周活跃')
        self.assertEqual(len(self.jobs()), 3)
        page.evaluate('userTurnsPage()')
        self.wait_for(page, lambda: len(self.jobs()) == 5)
        page.evaluate('userOpens(5)')
        self.wait_for(page, lambda: '负责合成岗位 5' in self.jobs()[BOSS + '/job_detail/job5.html']['jd'])
        # The page's own data still works after the hooks: the component reads back what was assigned.
        self.assertEqual(page.evaluate("document.querySelector('.page-job-wrapper').__vue__.jobDetail.jobInfo.encryptId"), 'job5')
        self.assertEqual(self.requests, [])

    def test_without_page_data_it_falls_back_to_the_page_text_and_says_so(self):
        page = self.open(DOM_FIXTURE)
        page.evaluate(self.code)
        self.wait_for(page, lambda: len(self.jobs()) == 1)
        [job] = self.jobs().values()
        self.assertEqual(job['title'], '合成后端工程师')
        self.assertIn('维护合成服务', job['jd'])
        self.wait_for(page, lambda: '已改用页面文字读取' in self.toast(page))

    def test_a_list_that_does_not_match_falls_back_too(self):
        page = self.open(VUE_FIXTURE.replace("encryptJobId: 'job' + n", "jobId: 'job' + n"))
        page.evaluate(self.code)
        self.wait_for(page, lambda: '已改用页面文字读取' in self.toast(page))
        self.assertTrue(all('/job_detail/' not in url for url in self.jobs()))


class BossRedLineTests(unittest.TestCase):
    """What the BOSS bookmarklet must never do, checked on the built code (comments stripped)."""

    def test_no_clicks_page_turns_polling_api_calls_or_cookies(self):
        code = unquote(bookmarklets.build('boss-zhipin'))
        for forbidden in ('clickJobCardAction', 'pageChange', '/wapi', 'document.cookie', 'setInterval', '.click(',
                          'dispatchEvent', 'XMLHttpRequest', 'bossName', 'bossOnline', 'bossTitle'):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, code)
        self.assertEqual(code.count('fetch('), 1)  # the one POST to the local inbox, in the shared prelude
