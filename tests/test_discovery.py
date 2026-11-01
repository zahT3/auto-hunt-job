import json
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from hunt.core import DEFAULT_CONFIG
from hunt.discovery import discover, default_sources, source_configs, DEFAULT_KINDS
from hunt.search.query import search_terms, matches, expanded_terms
from hunt.sources import SourceError, Document, jd_text, gate, jsonld_jobs, platform_detail, platform_links


def raw(value): return json.dumps(value).encode()


class DiscoveryTests(unittest.TestCase):
    def test_anker_bad_detail_does_not_hide_later_jobs(self):
        def transport(url, **kwargs):
            if 'getJobPosts/' in url:
                return raw({'code': 200, 'data': [{'id': '100000000000001', 'title': 'AI Engineer'}, {'id': '100000000000002', 'title': 'AI Engineer'}]})
            if 'jobPostId=100000000000001' in url:
                return raw({'code': 200, 'data': {'id': '100000000000001', 'title': 'AI Engineer'}})
            return raw({'code': 200, 'data': {'id': '100000000000002', 'title': 'AI Engineer', 'description': 'Build AI applications', 'job_active_status': 1}})
        result = discover({'sources': ['anker'], 'keywords': ['AI'], 'max_jobs': 1}, transport=transport)
        self.assertEqual([j['platform_id'] for j in result['jobs']], ['100000000000002'])
        self.assertEqual(result['sources'][0]['status'], 'parse_error')
        self.assertEqual(result['sources'][0]['detail_errors'][0]['platform_id'], '100000000000001')

    def test_login_gated_platforms_are_off_by_default(self):
        gated = {'boss', 'liepin'}
        self.assertEqual({s['id']: s['enabled'] for s in default_sources() if s['id'] in gated}, {'boss': False, 'liepin': False})
        self.assertTrue(all(s['enabled'] for s in default_sources() if s['id'] not in gated))
        self.assertFalse(gated & set(DEFAULT_KINDS))
        self.assertFalse(gated & set(DEFAULT_CONFIG['sources']))
        self.assertFalse(gated & {s['kind'] for s in source_configs({})})
        self.assertFalse(gated & {s['kind'] for s in source_configs(dict(DEFAULT_CONFIG))})

    def test_login_gated_platforms_still_selectable_explicitly(self):
        self.assertEqual([s['kind'] for s in source_configs(dict(sources=['boss', 'liepin'], source_modes={'boss': 'browser'}))], ['boss', 'liepin'])
        self.assertEqual([s['kind'] for s in source_configs(dict(discovery_sources=[dict(kind='boss')]))], ['boss'])

    def test_private_profile_never_becomes_search_query(self):
        calls = []
        def transport(url, **kwargs):
            calls.append(url); return raw({'jobs': []})
        result = discover({'sources': ['ashby'], 'keywords': ['AI', 'private@example.com', '13812345678']},
                          profile={'name':'PRIVATE_PERSON', 'resume':'SECRET_RESUME'}, transport=transport)
        self.assertEqual(result['queries'], ['AI'])
        self.assertNotIn('PRIVATE', repr(calls)); self.assertNotIn('SECRET', repr(calls))

    def test_empty_and_blocked_are_distinct(self):
        result = discover({'sources': ['boss','ashby'], 'keywords':['AI']}, transport=lambda u, **kw: b'<html>Loading</html>' if 'zhipin' in u else raw({'jobs':[]}))
        self.assertEqual([s['status'] for s in result['sources']], ['blocked','empty'])

    def test_gates_ignore_sdk_and_footer_login(self):
        gate('<script>captcha 验证码</script><footer>登录/注册</footer><h1>AI</h1>')
        with self.assertRaises(SourceError) as error: gate('<h1>请完成安全验证</h1>')
        self.assertEqual(error.exception.status, 'captcha')
        with self.assertRaises(SourceError) as error: gate('登录后查看完整职位')
        self.assertEqual(error.exception.status, 'login_required')

    def test_platform_reads_detail_not_search_snippet(self):
        detail = '<div class="job-banner"><h1>AI 应用开发</h1><span class="salary">20-30K</span></div><div class="company-name">合成公司</div><div class="job-sec-text">负责 AI 应用服务开发与评测，使用 Python 实现检索与生成，至少一年经验。</div>'
        def transport(url, **kw):
            return detail.encode() if '/job_detail/' in url else b'<a href="/job_detail/test123.html?ka=1">AI</a>'
        result=discover({'sources':['boss'],'keywords':['AI'],'max_jobs':3,'max_pages':2},transport=transport)
        self.assertEqual(len(result['jobs']),1)
        self.assertEqual(result['jobs'][0]['salary'],'20-30K')
        self.assertIn('Python',result['jobs'][0]['jd'])
        self.assertEqual(result['jobs'][0]['status'],'unverified')

    def test_platform_missing_detail_is_parse_failure(self):
        def transport(url, **kw):
            return b'<h1>AI</h1>' if '/job_detail/' in url else b'<a href="/job_detail/test.html">AI</a>'
        result=discover({'sources':['boss'],'keywords':['AI']},transport=transport)
        self.assertEqual(result['sources'][0]['status'],'parse_error'); self.assertFalse(result['jobs'])

    def test_greenhouse_reads_only_matching_details_and_preserves_ids(self):
        calls=[]
        def transport(url, **kw):
            calls.append(url)
            if url.endswith('/jobs'): return raw({'jobs':[{'id':1,'title':'AI Engineer'},{'id':2,'title':'Account Manager'},{'id':3,'title':'AI Engineer'}]})
            return raw({'id':int(url.rsplit('/',1)[-1]),'title':'AI Engineer','content':'Build AI applications and tools','absolute_url':'https://example.com/jobs/'+url.rsplit('/',1)[-1]})
        config={'sources':['greenhouse'],'company_boards':[{'type':'greenhouse','slug':'example'}],'keywords':['AI'],'max_jobs':10}
        result=discover(config,transport=transport)
        self.assertEqual(len(result['jobs']),2)
        self.assertNotEqual(result['jobs'][0]['platform_id'],result['jobs'][1]['platform_id'])
        self.assertEqual(len(calls),3)

    def test_lever_paginates_and_keeps_partial_budget_results(self):
        def transport(url, **kw):
            if 'skip=50' in url: return raw([])
            return raw([{'id':str(i),'text':'AI Engineer','descriptionPlain':'AI job','hostedUrl':'https://jobs.lever.co/example/'+str(i)} for i in range(50)])
        result=discover({'sources':['lever'],'company_boards':[{'type':'lever','slug':'example'}],'keywords':['AI'],'max_jobs':100,'max_pages':2,'discovery_requests':1},transport=transport)
        self.assertEqual(len(result['jobs']),50)
        self.assertEqual(result['sources'][0]['status'],'budget_exhausted')
        self.assertTrue(result['sources'][0]['truncated'])

    def test_global_budget_is_hard_and_fair(self):
        calls=[]
        def transport(url, **kw): calls.append(url); return raw({'jobs':[]})
        result=discover({'sources':['ashby','greenhouse'],'keywords':['AI'],'discovery_requests':1},transport=transport)
        self.assertEqual(len(calls),1)
        self.assertEqual(result['sources'][1]['status'],'budget_exhausted')

    def test_jsonld_company_and_expired_status(self):
        html='<script type="application/ld+json">'+json.dumps({'@type':'JobPosting','title':'AI Developer','description':'Build AI applications','hiringOrganization':{'name':'Synthetic'},'url':'https://example.com/jobs/1','validThrough':'2000-01-01','jobLocation':{'address':{'addressLocality':'Remote'}}})+'</script>'
        result=jsonld_jobs(html,'https://example.com/careers')
        self.assertEqual(result[0]['status'],'closed'); self.assertEqual(result[0]['company'],'Synthetic')

    def test_ascii_token_boundaries_do_not_match_maintain(self):
        self.assertFalse(matches('Maintain our systems',['AI']))
        self.assertTrue(matches('AI应用开发',['AI']))
        self.assertTrue(matches('机器学习平台开发',['AI']))

    def test_multi_word_term_needs_every_segment(self):
        self.assertFalse(matches('大模型算法工程师', ['AI 产品经理']))
        self.assertTrue(matches('资深 AI 产品经理', ['AI 产品经理']))
        self.assertTrue(matches('AI产品经理（大模型）', ['AI 产品经理']))
        self.assertTrue(matches('大模型产品经理', ['AI 产品经理']))
        self.assertFalse(matches('产品经理（电商）', ['AI 产品经理']))
        self.assertTrue(matches('大模型算法工程师', ['AI']))

    def test_chinese_role_segments_match_english_titles(self):
        self.assertTrue(matches('Agent Engineer', ['Agent 开发']))
        self.assertTrue(matches('Retrieval Engineer', ['RAG 工程师']))
        self.assertTrue(matches('Machine Learning Engineer', ['AI 应用开发']))
        self.assertTrue(matches('LLM Application Engineer', ['AI 应用开发']))
        self.assertTrue(matches('Senior AI Product Manager', ['AI 产品经理']))
        self.assertTrue(matches('AI Product Owner', ['AI 产品经理']))
        self.assertTrue(matches('Applied AI Developer', ['AI 应用研发']))
        self.assertFalse(matches('大模型算法工程师', ['AI 产品经理']))
        self.assertFalse(matches('Marketing Manager', ['AI 产品经理']))
        self.assertFalse(matches('Product Manager', ['AI 产品经理']))
        self.assertFalse(matches('Sales Engineer', ['Agent 开发']))

    def test_cross_domain_recommendation_links_not_read(self):
        links=platform_links('<a href="https://evil.example/job_detail/f.html">AI</a><a href="https://www.zhipin.com/job_detail/a.html">AI</a>','https://www.zhipin.com/','boss')
        self.assertEqual(links,['https://www.zhipin.com/job_detail/a.html'])

    def test_chinese_direction_expansion_is_visible_and_local(self):
        self.assertTrue(matches('Machine Learning 应用开发', ['AI 应用开发']))
        self.assertTrue(matches('Retrieval 工程师', ['RAG 工程师']))
        self.assertIn('machine learning', expanded_terms(['AI 应用开发'])['AI 应用开发'])
        self.assertEqual(search_terms({'keywords': [], 'keyword':'Python'}), ['Python'])

    def test_deep_remote_html_is_rejected(self):
        with self.assertRaises(SourceError):
            Document('<div>' * 200 + 'AI')

    def test_browser_allows_only_explicit_read_search_post(self):
        from hunt.sources_browser import BrowserReader
        class Route:
            def __init__(self, url, method):
                self.request=SimpleNamespace(url=url,method=method)
                self.action=None
            def abort(self): self.action='aborted'
            def continue_(self): self.action='allowed'
        browser=BrowserReader('liepin')
        with patch('hunt.sources_browser.resolve_public', return_value=['1.1.1.1']):
            read=Route('https://api-c.liepin.com/api/com.liepin.searchfront4c.pc-search-job','POST')
            browser._read_route(read)
            submit=Route('https://api-c.liepin.com/api/apply','POST')
            browser._read_route(submit)
            other=Route('https://example.org/','GET')
            browser._read_route(other)
        self.assertEqual(read.action,'allowed')
        self.assertEqual(submit.action,'aborted')
        self.assertEqual(other.action,'aborted')

    def test_browser_mode_reports_the_requests_its_guard_cut(self):
        class Reader:
            def __init__(self, kind, **kw): self.denied_requests = []
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def read(self, url):
                self.denied_requests += [dict(method='POST', url='https://api-c.liepin.com/api/com.liepin.im.init', why='method')] * 3
                self.denied_requests.append(dict(method='GET', url='https://hm.baidu.com/hm.js', why='host'))
                return b'<html><body>no cards</body></html>'
        with patch('hunt.sources_browser.BrowserReader', Reader):
            result = discover(dict(sources=['liepin'], source_modes={'liepin': 'browser'}, keywords=['AI']), transport=lambda *a, **k: self.fail('no plain fetch'))
        report = result['sources'][0]
        self.assertEqual(report['mode'], 'browser')
        self.assertEqual(report['blocked_requests'], [
            dict(method='POST', url='https://api-c.liepin.com/api/com.liepin.im.init', why='method', count=3),
            dict(method='GET', url='https://hm.baidu.com/hm.js', why='host', count=1)])
        plain = discover(dict(sources=['liepin'], keywords=['AI']), transport=lambda *a, **k: b'<html><body>x</body></html>')
        self.assertNotIn('blocked_requests', plain['sources'][0])

    def test_browser_report_names_the_driver_and_notes_the_playwright_fallback(self):
        from hunt.sources_browser import FALLBACK_NOTE
        for driver in ('playwright', 'patchright'):
            class Reader:
                def __init__(self, *a, **k): self.driver, self.denied_requests = driver, []
                def __enter__(self): return self
                def __exit__(self, *a): pass
                def read(self, url): return b'<html><body>no cards</body></html>'
            with patch('hunt.sources_browser.BrowserReader', Reader):
                report = discover(dict(sources=['liepin'], source_modes={'liepin': 'browser'}, keywords=['AI']),
                                  transport=lambda *a, **k: self.fail('no plain fetch'))['sources'][0]
            self.assertEqual(report['browser_driver'], driver)
            self.assertEqual(report.get('browser_note'), FALLBACK_NOTE if driver == 'playwright' else None)
        plain = discover(dict(sources=['liepin'], keywords=['AI']), transport=lambda *a, **k: b'<html><body>x</body></html>')
        self.assertNotIn('browser_driver', plain['sources'][0])

    def test_browser_guard_names_why_it_cut_each_request(self):
        from hunt.sources_browser import BrowserReader
        def route(url, method):
            return SimpleNamespace(request=SimpleNamespace(url=url, method=method), abort=lambda: 'aborted', continue_=lambda: 'allowed')
        browser = BrowserReader('liepin')
        with patch('hunt.sources_browser.resolve_public', side_effect=lambda host, **kw: ['1.1.1.1'] if host != 'bad.liepin.com' else (_ for _ in ()).throw(ValueError('private'))):
            for url, method in (('https://api-c.liepin.com/api/x', 'POST'), ('https://hm.baidu.com/hm.js', 'GET'),
                                ('https://bad.liepin.com/a.js', 'GET'), ('https://www.liepin.com/', 'GET')):
                browser._read_route(route(url, method))
        self.assertEqual([(d['url'], d['why']) for d in browser.denied_requests],
                         [('https://api-c.liepin.com/api/x', 'method'), ('https://hm.baidu.com/hm.js', 'host'), ('https://bad.liepin.com/a.js', 'address')])

    def test_browser_rejects_private_dns(self):
        from hunt.sources_browser import BrowserReader
        route=SimpleNamespace(request=SimpleNamespace(url='https://www.liepin.com/',method='GET'),abort=lambda: 'aborted',continue_=lambda:self.fail('private DNS allowed'))
        with patch('hunt.sources_browser.resolve_public', side_effect=ValueError('private address')):
            self.assertEqual(BrowserReader('liepin')._read_route(route),'aborted')

    def test_stop_callback_prevents_more_network_requests(self):
        calls=[]
        def transport(url, **kwargs): calls.append(url); return raw({'jobs':[]})
        result=discover({'sources':['ashby','greenhouse'],'keywords':['AI']}, transport=transport,should_continue=lambda: not calls)
        self.assertEqual(len(calls),1)
        self.assertEqual(result['sources'][1]['status'],'cancelled')

    def test_jd_preserves_lines_and_comparison(self):
        self.assertEqual(jd_text('Python < Java\n3年以上经验'), 'Python < Java\n3年以上经验')
        self.assertEqual(jd_text('<p>Python 开发</p><p>3年以上经验</p>'), 'Python 开发\n3年以上经验')

    def test_unconfigured_websearch_is_explicit(self):
        result=discover({'sources':[],'search_provider':{'provider':'brave'},'keywords':['AI']},transport=lambda *a,**k: self.fail('Should not fetch'))
        self.assertEqual(result['sources'][0]['status'],'not_configured')


class NoDefaultTermsTests(unittest.TestCase):
    def test_no_ai_default_terms(self):
        self.assertEqual(search_terms({}), [])
        self.assertEqual(search_terms({'keywords': [], 'keyword': ''}), [])
        with self.assertRaises(ValueError) as caught:
            discover(dict(), transport=lambda *a, **k: self.fail('must not fetch without terms'))
        self.assertIn('方向', str(caught.exception))

    def test_scan_cli_needs_a_keyword_or_chosen_directions(self):
        import contextlib, io, sys, tempfile
        from pathlib import Path
        from hunt.app import scan
        from hunt.core import Store
        with patch.object(sys, 'argv', ['scan']), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            scan.main()
        with tempfile.TemporaryDirectory() as tmp:
            Store(Path(tmp)).action(dict(action='directions_set', directions=['accountant']))
            seen = {}
            def fake(config, **kwargs):
                seen.update(config)
                return dict(jobs=[], queries=[], sources=[])
            with patch.object(sys, 'argv', ['scan', '--data', tmp]), patch.object(scan, 'discover', fake), \
                    contextlib.redirect_stdout(io.StringIO()):
                scan.main()
        self.assertTrue(seen['keywords'])
        self.assertFalse({'AI', 'Agent', 'Web3'} & set(seen['keywords']))

    def test_non_tech_alias_groups(self):
        self.assertTrue(matches('Senior Accountant', ['财务 会计']))
        for term, title in (('销售', 'Key Account Manager'), ('运营', 'Operations Specialist'), ('财务', 'Finance Analyst'),
                            ('人力资源', 'HR Business Partner'), ('设计师', 'Graphic Designer'), ('供应链', 'Procurement Specialist')):
            self.assertTrue(matches(title, [term]), term)
        self.assertFalse(matches('UI Designer', ['芯片设计']))  # only '设计师' style terms pull in design titles
        self.assertIn('ai', ' '.join(expanded_terms(['AI'])['AI']).lower())  # the old groups stay

    def test_product_lead_titles_and_maas_count_as_ai_product_roles(self):
        self.assertTrue(matches('智能体-移动端产品负责人-WorkBuddy', ['Agent 产品经理']))
        self.assertTrue(matches('腾讯营销-投放 Agent 产品专家-北京/深圳', ['Agent 产品经理']))
        self.assertTrue(matches('腾讯云-MaaS海外高级产品经理', ['AI 产品经理']))
        self.assertFalse(matches('仓库产品专员', ['AI 产品经理']))

    def test_unspaced_term_with_an_alias_word_needs_both_parts(self):
        # '大模型产品经理' is 大模型 + 产品经理, not a synonym of every AI title.
        for title in ('AI全栈工程师', '大模型算法工程师', '游戏AI研发工程师'):
            self.assertFalse(matches(title, ['大模型产品经理']), title)
        for title in ('大模型应用产品经理', 'AI 产品经理', 'Senior LLM Product Manager', '混元大模型平台产品经理'):
            self.assertTrue(matches(title, ['大模型产品经理']), title)
        self.assertTrue(matches('机器学习平台工程师', ['大模型']))  # a bare alias word keeps its whole group


if __name__=='__main__': unittest.main()
