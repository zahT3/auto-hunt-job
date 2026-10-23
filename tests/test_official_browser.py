"""Application-owned fixture: no network, no account, no recruiting platform."""
import unittest
from hunt.official_browser import PublicRenderer
from hunt.sources import SourceError


class OfficialBrowserTests(unittest.TestCase):
    def test_renderer_blocks_upload_and_submit_posts_without_a_personal_profile(self):
        try:
            import playwright.sync_api
        except ImportError:
            self.skipTest('Optional Playwright is not installed')
        renderer = PublicRenderer(maximum=1)
        try:
            try: renderer._start()
            except SourceError as error: self.skipTest(str(error))
            renderer.page.route('https://fixture.example/**', lambda route: route.fulfill(status=200, content_type='text/html', body='''
                <h1>Agent Engineer</h1><form><input type="file"></form>
                <script>
                fetch('https://app.mokahr.com/api/apply',{method:'POST',body:'fixture'}).catch(()=>{});
                fetch('https://app.mokahr.com/api/upload',{method:'POST',body:'fixture'}).catch(()=>{});
                </script>'''))
            result = renderer.read('https://fixture.example/role')
            self.assertIn(b'Agent Engineer', result['body'])
            self.assertEqual(renderer.blocked_posts, {'/api/apply','/api/upload'})
            self.assertEqual(renderer.used,1)
            with self.assertRaises(SourceError) as error: renderer.read('https://fixture.example/again')
            self.assertEqual(error.exception.status,'budget_exhausted')
        finally: renderer.__exit__(None,None,None)


if __name__ == '__main__': unittest.main()
