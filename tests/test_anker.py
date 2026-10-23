import hashlib
import json
import socket
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

from hunt import network
from hunt.anker import Anker, ChannelError, WEBSITE, platform_id
from hunt.execution import BrowserExecutor, PlanError

PID = '7695699480502651178'
JOB_URL = 'https://career.anker.com.cn/larkJobDetail/?websiteId=' + WEBSITE + '&jobId=' + PID
APPLY_URL = 'https://anker-in.jobs.feishu.cn/index/resume/' + PID + '/apply'


def encoded(value):
    return json.dumps(value).encode()


class PublicSourceTests(unittest.TestCase):
    def test_list_id_and_detail_requirements(self):
        calls = []
        def transport(url, **kwargs):
            calls.append((url, kwargs))
            if 'getJobPosts/' in url:
                return encoded(dict(code=200, total=1, data=[{'id':PID+WEBSITE}]))
            return encoded(dict(code=200, data=dict(id=PID, title='合成测试岗位', description='职责', requirement='本科及以上', job_active_status=1,
                                                   create_time='1791794767155', address_list=[dict(city=dict(name={'zh_cn':'深圳'}))])))
        a = Anker(transport)
        item = a.discover(1)[0]
        self.assertEqual(item['platform_id'],PID)
        self.assertEqual(item['requirements_text'],'本科及以上')
        self.assertIn('本科及以上',item['jd'])
        self.assertEqual(item['location'],'深圳')
        self.assertIsNone(item['published_at'])
        self.assertIsNone(item['salary'])
        self.assertEqual(calls[0][1]['method'],'POST')
        self.assertIn('getJobPostDetail',calls[1][0])
        self.assertEqual(item['application_url'],APPLY_URL)
        self.assertEqual(a.last_discovery['total'],1)

    def test_keyword_filters_titles_with_ascii_boundaries_and_audit(self):
        rows=[dict(id=PID+WEBSITE,title='Human Resource Generalist',description='Establish and maintain processes'),
              dict(id='7678630293062011179'+WEBSITE,title='高级产品经理（AI 数据平台 / MLOps 方向）'),
              dict(id='7694552449936181531'+WEBSITE,title='零售财务经理',description='利用AI建立自动对账Agent')]
        calls=[]
        def transport(url, **kwargs):
            calls.append(url)
            if 'getJobPosts/' in url:
                self.assertEqual(json.loads(kwargs['data'])['keywords'],'AI')
                return encoded(dict(code=200,total=178,data=rows))
            return encoded(dict(code=200,data=dict(id='7678630293062011179',title=rows[1]['title'],description='合成测试职责',requirement='合成测试要求',job_active_status=1)))
        channel=Anker(transport)
        items=channel.discover(limit=5,keyword='AI')
        self.assertEqual([x['platform_id'] for x in items],['7678630293062011179'])
        audit=channel.last_discovery
        self.assertEqual(audit['fetched_count'],3)
        self.assertEqual(audit['retained_count'],1)
        self.assertEqual(audit['total'],178)
        self.assertEqual(len(audit['candidates']),3)
        self.assertEqual(len(audit['excluded']),2)
        self.assertEqual(len(calls),2)  # One list page, details only for title hit.
        self.assertEqual(audit['raw_records'],rows)

    def test_keyword_filtered_empty_is_distinct_from_no_source_result(self):
        channel=Anker(lambda *a,**k:encoded(dict(code=200,total=1,data=[dict(id=PID+WEBSITE,title='Retail maintain specialist')])))
        self.assertEqual(channel.discover(keyword='AI'),[])
        self.assertEqual(channel.last_discovery['status'],'filtered_empty')
        self.assertEqual(channel.last_discovery['fetched_count'],1)
        self.assertEqual(channel.last_discovery['retained_count'],0)
        self.assertIn('标题',channel.last_discovery['excluded'][0]['reason'])

    def test_business_failure_and_parse_failure_are_not_empty_result(self):
        for response in [b'not json',encoded({'code':403}),encoded({'code':200,'data':{}})]:
            with self.assertRaises(ChannelError):
                Anker(lambda *a,**k:response).discover()
        self.assertEqual(Anker(lambda *a,**k:encoded({'code':200,'data':[]})).discover(),[])
        with self.assertRaises(ChannelError):
            platform_id('../../secret')


class NetworkTests(unittest.TestCase):
    def test_rejects_local_credentials_and_non_https(self):
        for url in ['http://example.com','https://127.0.0.1','https://[::1]','https://169.254.169.254/latest/meta-data',
                    'https://10.0.0.1','https://[::ffff:127.0.0.1]','https://localhost','https://x.local',
                    'https://user:pass@example.com','https://example.com:444','https://example.com\\@127.0.0.1']:
            with self.subTest(url=url), self.assertRaises(network.FetchError):
                network.validate_url(url)

    def test_mixed_public_private_dns_is_rejected(self):
        answers = [(socket.AF_INET,socket.SOCK_STREAM,6,'',('8.8.8.8',443)),
                   (socket.AF_INET,socket.SOCK_STREAM,6,'',('10.0.0.8',443))]
        with patch.object(network.socket,'getaddrinfo',return_value=answers):
            with self.assertRaises(network.FetchError):
                network.resolve_public('example.com')

    def test_fake_dns_independently_resolves_public_and_rejects_private(self):
        answer = [(socket.AF_INET,socket.SOCK_STREAM,6,'',('198.18.0.3',443))]
        with patch.object(network.socket,'getaddrinfo',return_value=answer),patch.object(network,'_doh',return_value=['8.8.8.8']) as doh:
            self.assertEqual(network.resolve_public('example.com'),['8.8.8.8'])
            doh.assert_called_once()
        with patch.object(network.socket,'getaddrinfo',return_value=answer),patch.object(network,'_doh',return_value=['10.0.0.1']):
            with self.assertRaises(network.FetchError):network.resolve_public('example.com')

    def test_pins_public_ip_and_rechecks_redirect_before_connection(self):
        instances=[]
        class Response:
            status=302
            def getheader(self,name,default=None):
                return 'https://127.0.0.1/secret' if name=='Location' else default
        class Conn:
            sock=None
            def __init__(self,host,ip,timeout):instances.append((host,ip))
            def request(self,*args,**kwargs):pass
            def getresponse(self):return Response()
            def close(self):pass
        with patch.object(network,'resolve_public',return_value=['8.8.8.8']),patch.object(network,'_PinnedHTTPS',Conn):
            with self.assertRaises(network.FetchError):network.fetch('https://example.com/path')
        self.assertEqual(instances,[('example.com','8.8.8.8')])

    def test_size_limit(self):
        class Response:
            status=200
            def getheader(self,name,default=None):return str(network.MAX_BYTES+1) if name=='Content-Length' else default
        class Conn:
            sock=None
            def __init__(self,*args):pass
            def request(self,*args,**kwargs):pass
            def getresponse(self):return Response()
            def close(self):pass
        with patch.object(network,'resolve_public',return_value=['8.8.8.8']),patch.object(network,'_PinnedHTTPS',Conn):
            with self.assertRaises(network.FetchError):network.fetch('https://example.com')


def fixture(root):
    package_dir = root/'packages'/'fixture-package'
    package_dir.mkdir(parents=True)
    (package_dir/'resume.pdf').write_bytes(b'%PDF-1.4\nSynthetic fixture only')
    file_hash=hashlib.sha256((package_dir/'resume.pdf').read_bytes()).hexdigest()
    job=dict(id='local-fixture-id',channel='anker',platform_id=PID,title='合成测试岗位',url=JOB_URL)
    package=dict(id='fixture-package',synthetic=False,snapshot='fixture-snapshot',fields={'name':{'value':'合成姓名','fact_ids':['fixture-name']}},
                 source_map={'fixture-name':{'disclosure':'application'}},files={'resume_pdf':'resume.pdf'})
    plan=dict(version=1,channel='anker',platform_id=PID,snapshot=package['snapshot'],recipient=JOB_URL,application_url=APPLY_URL,
              identity_selector='h1',inputs=[dict(selector='#name',field='name')],uploads=[dict(selector='#resume',file='resume_pdf',sha256=file_hash)],
              submit_selector='#submit',receipt=dict(record_selector='#receipt',job_id_attribute='data-job-id',number_attribute='data-application-id'))
    plan_path=root/'plan.json';plan_path.write_text(json.dumps(plan))
    approval=dict(decision='approve',disclosure='application',snapshot=package['snapshot'],expires_at=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),
                  job_ids=[job['id']],limit=1,permissions=['input','upload','submit'],recipient=JOB_URL,
                  browser_plan_hash=hashlib.sha256(plan_path.read_bytes()).hexdigest())
    return BrowserExecutor(plan_path,root,headless=True),job,package,approval


class PlanTests(unittest.TestCase):
    def test_valid_plan_and_mutation_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);executor,job,package,approval=fixture(root)
            executor._validate(job,package,approval)
            executor.plan_path.write_text(executor.plan_path.read_text()+' ')
            result=executor.execute(job,package,approval,lambda:True)
            self.assertEqual(result['state'],'not_sent')
            self.assertFalse(result['submit_attempted'])
            self.assertIn('变化',result['reason'])

    def test_unknown_fact_expired_approval_and_synthetic_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            executor,job,package,approval=fixture(Path(tmp))
            package['fields']['name']['fact_ids']=['nonexistent']
            with self.assertRaises(PlanError):executor._validate(job,package,approval)
            package['synthetic']=True
            with self.assertRaises(PlanError):executor._validate(job,package,approval)
            package['synthetic']=False
            approval['expires_at']='2020-01-01T00:00:00+00:00'
            with self.assertRaises(PlanError):executor._validate(job,package,approval)


HTML = '''<!doctype html><html><meta charset="utf-8"><h1>合成测试岗位</h1><form onsubmit="event.preventDefault(); document.querySelector('#receipt').hidden=false">
<label>姓名<input id="name" required></label><input id="resume" type="file" required><button id="submit" type="submit">投递简历</button></form>
<div id="receipt" hidden data-job-id="''' + PID + '''" data-application-id="APP-FIXTURE-1234">申请记录（本地测试夹具）</div></html>'''


class BrowserFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
            cls.runtime=sync_playwright().start()
            cls.browser=cls.runtime.chromium.launch(headless=True)
        except Exception as exc:
            if hasattr(cls,'runtime'):cls.runtime.stop()
            raise unittest.SkipTest('Browser fixture unavailable: '+str(exc))

    @classmethod
    def tearDownClass(cls):
        cls.browser.close();cls.runtime.stop()

    def run_fixture(self,html,control=None,login=False):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        root=Path(tmp.name);executor,job,package,approval=fixture(root)
        plan,fields,uploads=executor._validate(job,package,approval)
        context=self.browser.new_context(service_workers='block')
        self.addCleanup(context.close)
        def route_request(route):
            if login and '/resume/' in route.request.url:
                route.fulfill(status=302,headers={'location':'https://anker-in.jobs.feishu.cn/index/login'},body='')
            else:route.fulfill(status=200,content_type='text/html; charset=utf-8',body=html)
        context.route('**/*',route_request)
        page=context.new_page()
        result=executor._run_page(page,plan,fields,uploads,job,approval,control or (lambda:True),root/'evidence')
        return result,page,root

    def test_actual_input_upload_submit_and_job_receipt_on_local_route_fixture(self):
        result,page,root=self.run_fixture(HTML)
        self.assertEqual(result['state'],'submitted')
        self.assertEqual(result['receipt']['number'],'APP-FIXTURE-1234')
        self.assertEqual(page.locator('#name').input_value(),'合成姓名')
        self.assertEqual(page.locator('#resume').evaluate('(el) => el.files[0].name'),'resume.pdf')
        events=(root/'evidence/events.jsonl').read_text()
        self.assertLess(events.index('submit_intent'),events.index('submit_clicked'))
        self.assertTrue(Path(result['receipt']['evidence']).is_file())

    def test_login_and_unknown_required_question_pause_before_input(self):
        result,page,root=self.run_fixture(HTML,login=True)
        self.assertEqual(result['state'],'not_sent');self.assertFalse(result['submit_attempted'])
        self.assertIn('登录',result['reason'])
        result,page,root=self.run_fixture(HTML.replace('<form ','<input id="salary" required><form '))
        self.assertEqual(result['state'],'not_sent')
        self.assertEqual(page.locator('#name').input_value(),'')

    def test_prefilled_unapproved_profile_and_dynamic_question_are_blocked(self):
        result,page,root=self.run_fixture(HTML.replace('<form ', '<input id="old-profile" value="not in approved package"><form '))
        self.assertEqual(result['state'],'not_sent')
        self.assertIn('旧资料',result['reason'])
        html=HTML.replace('id="name" required', 'id="name" required oninput="document.querySelector(\'#extra\').hidden=false;document.querySelector(\'#extra\').required=true"')
        html=html.replace('<form ', '<input id="extra" hidden><form ')
        result,page,root=self.run_fixture(html)
        self.assertEqual(result['state'],'unknown')
        self.assertFalse(result['submit_attempted'])
        self.assertIn('必填',result['reason'])

    def test_click_without_usable_receipt_stays_unknown(self):
        html=HTML.replace('APP-FIXTURE-1234','')
        result,page,root=self.run_fixture(html)
        self.assertEqual(result['state'],'unknown')
        self.assertTrue(result['submit_attempted'])

    def test_existing_application_record_never_becomes_a_new_receipt(self):
        result,page,root=self.run_fixture(HTML.replace('hidden data-job-id','data-job-id'))
        self.assertEqual(result['state'],'not_sent')
        self.assertFalse(result['submit_attempted'])
        self.assertIn('历史',result['reason'])

    def test_pause_after_input_prevents_upload_and_submit(self):
        calls=[0]
        def running():
            calls[0]+=1
            return calls[0] < 4
        result,page,root=self.run_fixture(HTML,control=running)
        self.assertEqual(result['state'],'unknown')
        self.assertFalse(result['submit_attempted'])
        self.assertEqual(page.locator('#resume').evaluate('(el) => el.files.length'),0)


if __name__ == '__main__': unittest.main()
