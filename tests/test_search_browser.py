"""Application-owned browser fixture; no recruitment-site or account requests."""
import tempfile
import unittest
from pathlib import Path
from hunt.sources import SourceError
from hunt.sources_browser import BrowserReader


class SearchBrowserTests(unittest.TestCase):
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
