"""Failure regressions using local fixtures only; no recruiting-site traffic."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

from hunt.core import Store
from hunt.entries import inspect
from hunt.moka_session import MokaVerifier
from hunt.official_browser import PublicRenderer
from hunt.sources import SourceError


URL = 'https://app.mokahr.com/apply/acme/123#/job/role-one/apply'
JOB = dict(title='Agent Engineer', url=URL, application_url=URL, platform_id='acme:role-one')
READ_PATH = '/api/outer/ats-apply/website/applicant-limit-check'
SCHEMA_PATH = '/api/get_apply_form/acme'


class NetworkFixture:
    """Intercept every request; only guard_abort reaches a deny-only guard."""
    def __init__(self, page):
        self.mode = 'ok'
        self.path = READ_PATH
        self.held = []
        self.requests = []
        self.unexpected = []
        page.route('**/*', self.route)

    def route(self, route):
        request = route.request
        p = urlsplit(request.url)
        self.requests.append((request.method, p.path))
        if p.hostname != 'app.mokahr.com':
            self.unexpected.append(request.url); return route.abort()
        if p.path == '/apply/acme/123':
            method = 'GET' if self.path == SCHEMA_PATH else 'POST'
            body = '''<h1>Agent Engineer</h1><p>上传简历</p><input type=file>
                <button>预览并提交</button><button>退出登录</button><script>
                fetch(PATH, {method: METHOD}).catch(()=>{});
                </script>'''.replace('PATH', json.dumps(self.path)).replace('METHOD', json.dumps(method))
            return route.fulfill(status=200, content_type='text/html; charset=utf-8', body=body)
        if p.path == self.path:
            if self.mode == 'abort': return route.abort('connectionfailed')
            if self.mode == 'pending': self.held.append(route); return
            if self.mode == 'guard_abort': return route.fallback()
            return route.fulfill(status=500 if self.mode == 'http500' else 200,
                                 content_type='application/json', body='{"code":0,"data":{}}')
        if p.path != '/favicon.ico': self.unexpected.append(request.url)
        route.abort()

    def release(self):
        for route in self.held:
            try: route.abort()
            except Exception: pass
        self.held.clear()


class MokaReadFailureBrowserTests(unittest.TestCase):
    def require_playwright(self):
        try: import playwright.sync_api  # noqa: F401
        except ImportError: self.skipTest('Optional Playwright is not installed')

    def test_isolated_form_reads_fail_closed_and_reset_after_navigation(self):
        self.require_playwright()
        with tempfile.TemporaryDirectory() as tmp:
            browser = MokaVerifier(Path(tmp), JOB, headless=True)
            fixture = None
            try:
                try: browser.__enter__()
                except SourceError as error: self.skipTest(str(error))
                fixture = NetworkFixture(browser.page)
                # The guard-abort case reproduces the original DNS/routing
                # failure without making a DNS query or outbound connection.
                with patch('hunt.moka_session.resolve_public', side_effect=OSError('fixture-only network failure')):
                    for mode in ('abort', 'pending', 'http500', 'guard_abort'):
                        with self.subTest(mode=mode):
                            fixture.mode = mode
                            result = browser.open()
                            self.assertEqual(result['status'], 'form_incomplete')
                            self.assertFalse(result['authenticated'])
                            self.assertTrue(browser.reads.incomplete)
                            self.assertNotIn('text', result)
                            fixture.release()
                fixture.mode = 'ok'
                result = browser.open()
                self.assertEqual(result['status'], 'form_seen')
                self.assertTrue(result['authenticated'])
                self.assertFalse(browser.reads.incomplete)
                self.assertFalse(fixture.unexpected)
                self.assertIn(('POST', READ_PATH), fixture.requests)
            finally:
                if fixture: fixture.release()
                browser.__exit__(None, None, None)

    def test_public_renderer_propagates_incomplete_reads_and_recovers(self):
        self.require_playwright()
        renderer = PublicRenderer(maximum=5)
        fixture = None
        try:
            try: renderer._start()
            except SourceError as error: self.skipTest(str(error))
            fixture = NetworkFixture(renderer.page)
            for mode in ('abort', 'pending', 'http500', 'guard_abort'):
                with self.subTest(mode=mode):
                    fixture.mode = mode
                    # Exercise GET schema tracking as well as the intentionally
                    # blocked POST used by the public (anonymous) renderer.
                    fixture.path = READ_PATH if mode == 'guard_abort' else SCHEMA_PATH
                    response = renderer.read(URL)
                    self.assertTrue(response['incomplete_reads'])
                    result = inspect(JOB, URL, response)
                    self.assertEqual(result['status'], 'form_incomplete')
                    self.assertFalse(result['authenticated'])
                    fixture.release()
            fixture.mode = 'ok'; fixture.path = SCHEMA_PATH
            response = renderer.read(URL)
            self.assertFalse(response['incomplete_reads'])
            result = inspect(JOB, URL, response)
            self.assertEqual(result['status'], 'form_seen')
            self.assertFalse(result['authenticated'])
            self.assertIn(READ_PATH, renderer.blocked_posts)
            self.assertFalse(fixture.unexpected)
        finally:
            if fixture: fixture.release()
            renderer.__exit__(None, None, None)


class MokaRunRaceTests(unittest.TestCase):
    def test_old_cleanup_cannot_remove_restarted_run_signals(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp))
            job, _ = store.import_job(dict(JOB, jd='Build agents using synthetic fixtures.'))
            started, release, old_cleanup = threading.Event(), threading.Event(), threading.Event()
            workers = []

            class Browser:
                def __init__(self, *args, **kwargs): pass
                def __enter__(self): return self
                def __exit__(self, *args): pass

                def run(self, finish, cancel, progress):
                    workers.append(threading.current_thread())
                    if len(workers) > 1:
                        progress('awaiting_login', 'Fixture is waiting')
                        started.set()
                        if not release.wait(5): raise RuntimeError('fixture release timed out')
                    return dict(status='form_seen', method='isolated_session', url=URL)

            class HookLock:
                """Start run 2 after terminal state publication, before cleanup."""
                def __init__(self): self.lock = threading.Lock(); self.restarted = False
                def __enter__(self): self.lock.acquire(); return self

                def __exit__(self, *args):
                    self.lock.release()
                    if not self.restarted and store.entry_verifications.get(job['id'], {}).get('status') == 'complete':
                        self.restarted = True
                        store.start_entry_verification(job['id'])
                    elif self.restarted and workers and threading.current_thread() is workers[0]:
                        old_cleanup.set()

            store.entry_lock = HookLock()
            with patch('hunt.moka_session.MokaVerifier', Browser):
                try:
                    store.start_entry_verification(job['id'])
                    self.assertTrue(started.wait(3), 'Second run did not start')
                    self.assertTrue(old_cleanup.wait(3), 'First run did not clean up')
                    self.assertEqual(store.entry_verifications[job['id']]['status'], 'awaiting_login')
                    self.assertIn(job['id'], store.entry_signals)
                    finish, cancel = store.entry_signals[job['id']]
                    store.action(dict(action='entry_finish', job_id=job['id']))
                    self.assertTrue(finish.is_set())
                    store.action(dict(action='entry_cancel', job_id=job['id']))
                    self.assertTrue(cancel.is_set())
                finally:
                    release.set()
                    for worker in list(workers): worker.join(3)
            self.assertTrue(all(not worker.is_alive() for worker in workers))
            self.assertEqual(len(workers), 2)
            self.assertNotIn(job['id'], store.entry_signals)
            self.assertEqual(store.state()['jobs'][0]['attempts'], [])


if __name__ == '__main__': unittest.main()
