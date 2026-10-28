"""Application-owned browser fixture; no recruitment-site or account requests."""
import tempfile
import unittest
from pathlib import Path
from hunt.sources import SourceError
from hunt.sources_browser import BrowserReader


class SearchBrowserTests(unittest.TestCase):
    def test_driver_is_patchright_when_installed_else_playwright(self):
        from unittest.mock import patch
        from hunt.sources_browser import _sync_playwright
        try:
            import patchright.sync_api as patched
        except ImportError:
            self.skipTest('Optional Patchright is not installed')
        import playwright.sync_api as plain
        self.assertIs(_sync_playwright(), patched.sync_playwright)
        with patch.dict('sys.modules', {'patchright.sync_api': None}):
            self.assertIs(_sync_playwright(), plain.sync_playwright)

    def test_delayed_blank_redirect_stops_once_instead_of_emitting_empty_html(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.skipTest('Optional Playwright is not installed')
        with tempfile.TemporaryDirectory() as tmp:
            reader = BrowserReader('boss', headless=True, profile_root=Path(tmp))
            try: reader.__enter__()
            except SourceError as error: self.skipTest(str(error))
            requests = []
            def fixture(route):
                requests.append(route.request.url)
                route.fulfill(status=200, content_type='text/html', body='''<h1>Fixture</h1>
                    <script>setTimeout(()=>location.href='about:blank',100)</script>''')
            reader._read_route = fixture
            try:
                with self.assertRaises(SourceError) as error:
                    reader.read('https://www.zhipin.com/web/geek/jobs')
                self.assertEqual(error.exception.status, 'blank_page')
                self.assertEqual(len(requests), 1)
            finally: reader.__exit__(None, None, None)


if __name__ == '__main__': unittest.main()
