import json
import tempfile
import unittest
from pathlib import Path
from hunt.sources import public_url, SourceError
from hunt.domestic import embedded_json, moka_dom
from hunt.entries import inspect, check_job, official_job_link
from hunt.discovery import discover
from hunt.network import FetchError
from hunt.official_browser import read_request
from hunt.core import Store


class OfficialTests(unittest.TestCase):
    def job(self):
        return dict(title='Agent Engineer', url='https://jobs.ashbyhq.com/acme/one',
                    application_url='https://jobs.ashbyhq.com/acme/one/application', raw={})

    def response(self, body, status=200, url='https://jobs.ashbyhq.com/acme/one/application'):
        return dict(body=body.encode(), status=status, url=url)

    def test_literal_json_is_decoded_without_executing_javascript(self):
        data = dict(jobs=[dict(id='x', descriptionHtml='<p>Use "Agents" and it\'s tools.</p>')])
        literal = json.dumps(data).replace('\\', '\\\\').replace("'", "\\'")
        self.assertEqual(embedded_json("evil();JSON.parse('"+literal+"');dangerous()"), data)
        with self.assertRaises(SourceError): embedded_json('JSON.parse(window.secret)')

    def test_moka_receiver_fragment_preserves_identity_ordinary_anchor_does_not(self):
        base = 'https://app.mokahr.com/social-recruitment/acme/1'
        self.assertNotEqual(public_url(base+'#/job/aaa'), public_url(base+'#/job/bbb'))
        self.assertEqual(public_url('https://jobs.lever.co/acme#tracking'), 'https://jobs.lever.co/acme')
        self.assertEqual(public_url(base+'#untrusted'), base)

    def test_store_keeps_moka_routes_on_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp)); url='https://app.mokahr.com/apply/acme/1#/job/abc'
            j, _ = store.import_job(dict(title='Agent', jd='Build agents', url=url))
            self.assertEqual(j['url'], url)

    def test_http_success_is_not_proof_of_a_form(self):
        job=self.job()
        self.assertEqual(inspect(job, job['application_url'], self.response('<div id="root"></div>'))['status'], 'needs_browser')
        self.assertEqual(inspect(job, job['application_url'], self.response('<h1>Agent Engineer</h1><p>Apply soon</p>'))['status'], 'job_page_seen')

    def test_wrong_job_generic_form_and_soft_404_are_not_usable_receivers(self):
        job=self.job(); url=job['application_url']
        self.assertEqual(inspect(job,url,self.response('<h1>Other Engineer</h1><form><input type="file"></form>'))['status'],'identity_mismatch')
        self.assertEqual(inspect(job,url,self.response('<h1>Page not found</h1>'))['status'],'not_found')
        self.assertEqual(inspect(job,url,self.response('Gone',410))['status'],'not_found')
        self.assertEqual(inspect(job,url,self.response('Forbidden',403))['status'],'blocked')
        self.assertEqual(inspect(job,url,self.response('Login',url='https://acme.example/login'))['status'],'login_required')

    def test_moka_login_modal_is_a_login_gate_not_a_wrong_job(self):
        job=self.job();url='https://app.mokahr.com/apply/acme/1#/job/one/apply'
        result=inspect(job,url,self.response('<div>Agent Engineer</div><div>邮箱登录 手机号登录 请先登录</div>',url=url))
        self.assertEqual(result['status'],'login_required')

    def test_only_unique_observed_same_role_anchor_can_be_used_for_repair(self):
        html='<a href="/careers/agent"><p>Agent Engineer</p><p>Remote</p></a><a href="/careers">All roles</a>'
        self.assertEqual(official_job_link(html,'https://acme.example/careers','Agent Engineer'),'https://acme.example/careers/agent')
        self.assertIsNone(official_job_link(html+'<a href="/other">Agent Engineer</a>','https://acme.example/careers','Agent Engineer'))

    def test_repair_retains_failed_primary_and_requires_same_role_form(self):
        job=self.job(); route=job['raw'].setdefault('application_route',{})
        route['official_job_url']='https://acme.example/careers/agent'
        def read(url,**kw):
            return self.response('<h1>Agent Engineer</h1><form><input type="file"></form>',url=url) if url==route['official_job_url'] else self.response('<h1>Page not found</h1>')
        check_job(job,read)
        self.assertEqual(job['application_url'],route['official_job_url'])
        self.assertEqual(route['repair']['previous_check']['status'],'not_found')
        self.assertEqual(route['entry_check']['status'],'form_seen')
        self.assertIn('ashbyhq',route['original_application_url'])

    def test_same_title_with_different_source_id_cannot_repair_a_receiver(self):
        job=self.job();job['platform_id']='acme:role-123'
        job['raw']['application_route']=dict(official_job_url='https://acme.example/careers/agent')
        original=job['application_url']
        def read(url,**kw):
            return self.response('<h1>Agent Engineer</h1><form data-job-id="role-456"><input type="file"></form>') if url=='https://acme.example/careers/agent' else self.response('<h1>Page not found</h1>')
        check_job(job,read)
        self.assertEqual(job['application_url'],original)
        self.assertEqual(job['raw']['application_route']['alternate_check']['status'],'identity_unconfirmed')

    def test_alternate_careers_page_cannot_repair_a_receiver(self):
        job=self.job(); job['raw']['application_route']=dict(official_job_url='https://acme.example/careers')
        original=job['application_url']
        check_job(job,lambda *a,**k:self.response('<h1>Careers</h1><form><input type="file"></form>'))
        self.assertEqual(job['application_url'],original)

    def test_network_error_does_not_mean_closed_or_not_found(self):
        job=self.job()
        def read(*a,**k): raise FetchError('DNS timeout')
        check_job(job,read)
        self.assertEqual(job['raw']['application_route']['entry_check']['status'],'check_failed')

    def test_cancel_is_not_swallowed_by_entry_checker(self):
        def read(*a,**k): raise SourceError('cancelled','stop')
        with self.assertRaises(SourceError): check_job(self.job(),read)

    def test_dify_uses_observed_public_feed_and_email_without_writes(self):
        calls=[]
        def read(url,**kw):
            calls.append((url,kw))
            if 'supabase' not in url:return b'''<a href="mailto:joinus@dify.ai">Apply</a><script>fetch('https://acme.supabase.co/functions/v1/public-jobs?lang=en')</script>'''
            return json.dumps(dict(jobs=[dict(id='one',title='Agent Developer',content='<p>Build agents with Python</p>',location='China')])).encode()
        result=discover(dict(sources=['website'],company_boards=[dict(type='website',url='https://join.dify.ai/roles')],keywords=['Agent'],check_entries=True),transport=read)
        job=result['jobs'][0]; route=job['raw']['application_route']
        self.assertEqual(route['entry_check']['status'],'email_only');self.assertEqual(route['email'],'joinus@dify.ai')
        self.assertEqual(len(calls),2);self.assertTrue(all(k.get('method','GET')=='GET' for _,k in calls))

    def test_recent_definite_entry_check_survives_lower_confidence_refresh(self):
        from hunt.careers import preserve_entry_check
        from hunt.sources import now
        url='https://jobs.lever.co/acme/one'
        old=dict(application_route=dict(entry_check=dict(url=url,status='not_found',checked_at=now())))
        incoming=dict(application_route=dict(entry_check=dict(url=url,status='needs_browser',checked_at=now())))
        self.assertEqual(preserve_entry_check(old,incoming,url)['application_route']['entry_check']['status'],'not_found')

    def test_moka_title_without_real_description_is_rejected(self):
        with self.assertRaises(SourceError):moka_dom('<div class="title-x">Agent Engineer</div><div><span>职位描述</span><p>暂无</p></div>','https://app.mokahr.com/apply/acme/1#/job/abc','acme','Acme')

    def test_renderer_allows_only_explicit_read_posts(self):
        self.assertTrue(read_request('POST','https://app.mokahr.com/api/outer/ats-apply/website/job'))
        for url in ['https://app.mokahr.com/api/apply','https://app.mokahr.com/api/outer/ats-apply/website/job/submit','https://evil.example/api/outer/ats-apply/website/job']:
            self.assertFalse(read_request('POST',url))
        self.assertFalse(read_request('DELETE','https://app.mokahr.com/api/outer/ats-apply/website/job'))

    def test_email_check_requires_no_request_even_when_budget_is_spent(self):
        job=self.job();job['raw']['application_route']=dict(entry_type='email',email='jobs@acme.example')
        def read(*a,**k): self.fail('Email-only entry must not contact a mail service or fetch a form')
        check_job(job,read)
        self.assertEqual(job['raw']['application_route']['entry_check']['status'],'email_only')

    def test_entry_budget_is_independent_and_explicit(self):
        def read(url,**kw):
            if 'posting-api' in url:return json.dumps(dict(jobs=[dict(id=str(i),title='Agent Engineer',descriptionPlain='Build agents',jobUrl=f'https://jobs.ashbyhq.com/acme/{i}',applyUrl=f'https://jobs.ashbyhq.com/acme/{i}/application') for i in range(2)])).encode()
            return self.response('<h1>Agent Engineer</h1><form><input type="file"></form>',url=url)
        r=discover(dict(sources=['ashby'],company_boards=[dict(type='ashby',slug='acme')],keywords=['Agent'],check_entries=True,entry_requests=1),transport=read)
        self.assertEqual(r['entry_requests'],1)
        self.assertEqual(r['jobs'][1]['raw']['application_route']['entry_check']['status'],'budget_exhausted')


if __name__ == '__main__':unittest.main()
