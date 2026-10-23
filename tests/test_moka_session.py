import copy
import tempfile
import unittest
from pathlib import Path
from hunt.moka_session import allowed_request, classify, entry_identity, MokaVerifier, READ_POSTS
from hunt.sources import SourceError
from hunt.core import Store, Error

URL = 'https://app.mokahr.com/apply/acme/123#/job/role-one/apply'
JOB = dict(title='Agent Engineer',url=URL,application_url=URL,platform_id='acme:role-one')
OBS = dict(text='Agent Engineer 上传简历 预览并提交', headings=['Agent Engineer'], resume_input=True, submit_control=True, account_marker=True)


class MokaSessionTests(unittest.TestCase):
    def test_login_modal_overrides_visible_form_and_stale_auth_marker(self):
        result=classify(JOB, URL, dict(OBS,login_gate=True), session=True)
        self.assertEqual(result['status'],'login_required'); self.assertFalse(result['authenticated'])

    def test_same_title_different_role_or_board_never_matches(self):
        for url in [URL.replace('role-one','role-two'),URL.replace('/123#','/234#'),URL.replace('/acme/','/other/')]:
            self.assertEqual(classify(JOB,url,OBS,session=True)['status'],'identity_mismatch')

    def test_form_needs_title_resume_control_and_successful_reads(self):
        for obs in [dict(OBS,resume_input=False),dict(OBS,submit_control=False)]:
            self.assertEqual(classify(JOB,URL,obs)['status'],'job_page_seen')
        self.assertEqual(classify(JOB,URL,dict(OBS,headings=['Other']))['status'],'identity_mismatch')
        self.assertEqual(classify(JOB,URL,OBS,blocked_reads=True)['status'],'form_incomplete')
        self.assertEqual(classify(JOB,URL,dict(OBS,load_error=True))['status'],'form_incomplete')

    def test_form_seen_does_not_infer_authenticated_account(self):
        result=classify(JOB,URL,OBS)
        self.assertEqual(result['status'],'form_seen'); self.assertFalse(result['authenticated'])
        self.assertTrue(classify(JOB,URL,OBS,session=True)['authenticated'])
        self.assertFalse(classify(JOB,URL,dict(OBS,account_marker=False),session=True)['authenticated'])
        self.assertEqual(classify(JOB,URL,dict(OBS,headings=['【优先】 Agent Engineer']))['status'],'form_seen')

    def test_auth_allowlist_only_in_login_phase(self):
        path='https://app.mokahr.com/personal-center/candidate/email-login'
        self.assertTrue(allowed_request('POST',path,'app.mokahr.com',True))
        self.assertFalse(allowed_request('POST',path,'app.mokahr.com'))
        self.assertFalse(allowed_request('POST',path.replace('app.','hire-r1.'),'app.mokahr.com',True))
        for suffix in ['/api/apply','/api/upload','/api/outer/ats-apply/personal-center/candidate/cancel-account','/api/outer/ats-apply/personal-center/verify-code-save-email']:
            for login in (True,False):self.assertFalse(allowed_request('POST','https://app.mokahr.com'+suffix,'app.mokahr.com',login))
        self.assertFalse(allowed_request('GET','https://app.mokahr.com/logout','app.mokahr.com',True))
        self.assertFalse(allowed_request('GET','https://evil.example/code.js','app.mokahr.com',True))

    def test_entry_requires_exact_https_board_and_role(self):
        for url in ['https://evil.example/apply/acme/123#/job/one/apply','https://app.mokahr.com/apply/acme/123','https://app.mokahr.com/apply/acme/123#/jobs']:
            with self.assertRaises((SourceError,ValueError)):entry_identity(url)

    def test_check_is_saved_without_material_permission_or_attempt_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)); job,_=store.import_job(dict(JOB,jd='Build agents'))
            original=copy.deepcopy(job)
            check=classify(job,URL,OBS,session=True)
            store.save_entry_check(job,check)
            state=store.state(); updated=state['jobs'][0]
            self.assertEqual(updated['approval'],original['approval'])
            self.assertEqual(updated['status'],original['status'])
            self.assertEqual(updated['attempts'],[])
            self.assertTrue(state['candidate']['synthetic'])
            job['application_url']=URL.replace('role-one','role-two')
            with self.assertRaises(Error):store.save_entry_check(job,check)


class MokaBrowserTests(unittest.TestCase):
    def test_human_login_window_blocks_application_writes_and_reads_visible_gates(self):
        try: import playwright.sync_api
        except ImportError:self.skipTest('Optional Playwright not installed')
        with tempfile.TemporaryDirectory() as tmp:
            browser=MokaVerifier(Path(tmp),JOB,headless=True)
            try:
                try:browser.__enter__()
                except SourceError as error:self.skipTest(str(error))
                browser.login_enabled=True
                browser.page.route(URL.split('#')[0],lambda route:route.fulfill(content_type='text/html; charset=utf-8',body='''
                <h1>Agent Engineer</h1><p>上传简历</p><input type=file><button>预览并提交</button>
                <div role=dialog>邮箱登录 手机号登录</div>
                <script>fetch('/api/apply',{method:'POST'}).catch(()=>{});fetch('/api/upload',{method:'POST'}).catch(()=>{});</script>'''))
                browser.page.goto(URL);browser.page.wait_for_timeout(200)
                result=browser.check()
                self.assertEqual(result['status'],'login_required')
                self.assertIn(('POST','/api/apply'),browser.blocked)
                self.assertIn(('POST','/api/upload'),browser.blocked)
                self.assertNotIn('text',result)
                browser.page.locator('[role=dialog]').evaluate('(n)=>n.style.display="none"')
                result=browser.check()
                self.assertEqual(result['status'],'form_seen')
                self.assertFalse(result['authenticated'])
            finally:browser.__exit__(None,None,None)

if __name__=='__main__': unittest.main()
