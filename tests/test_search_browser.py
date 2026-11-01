"""Application-owned browser fixture; no recruitment-site or account requests."""
import tempfile
import unittest
from pathlib import Path
from hunt.sources import SourceError
from hunt.sources_browser import BrowserReader


class SearchBrowserTests(unittest.TestCase):
    def test_login_without_data_uses_the_workbench_profile(self):
        from unittest.mock import patch
        import hunt.sources_browser as sb
        seen = []
        class Reader:
            def __init__(self, kind, profile_root, channel): seen.append((kind, profile_root, channel))
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def login(self): pass
        for argv, root in ((['--login', 'liepin'], sb.DEFAULT_DATA / 'browser-search'),
                           (['--login', 'liepin', '--data', '/tmp/x'], Path('/tmp/x/browser-search')),
                           (['--login', 'boss', '--profile-root', '/tmp/p'], Path('/tmp/p'))):
            with patch.object(sb, 'BrowserReader', Reader), patch('sys.argv', ['sources_browser'] + argv):
                sb.main()
            self.assertEqual(seen[-1][1], root, argv)
        self.assertEqual(sb.DEFAULT_DATA, Path(sb.__file__).resolve().parent.parent / 'private' / 'app')

    def test_driver_is_patchright_when_installed(self):
        from hunt.sources_browser import _driver
        try:
            import patchright.sync_api as patched
        except ImportError:
            self.skipTest('Optional Patchright is not installed')
        self.assertEqual(_driver(), ('patchright', patched.sync_playwright))

    def test_driver_falls_back_to_playwright_without_patchright(self):
        from unittest.mock import patch
        from hunt.sources_browser import _driver, _sync_playwright
        try:
            import playwright.sync_api as plain
        except ImportError:
            self.skipTest('Optional Playwright is not installed')
        with patch.dict('sys.modules', {'patchright': None, 'patchright.sync_api': None}):
            self.assertEqual(_driver(), ('playwright', plain.sync_playwright))
            self.assertIs(_sync_playwright(), plain.sync_playwright)

    def test_patchright_is_an_optional_platform_dependency(self):
        root = Path(__file__).resolve().parent.parent
        executor = (root / 'requirements-executor.txt').read_text()
        platform = (root / 'requirements-platform.txt').read_text().splitlines()
        self.assertNotIn('patchright', executor)
        self.assertIn('playwright==', executor)
        self.assertEqual(platform[0], '-r requirements-executor.txt')
        self.assertTrue(any(line.startswith('patchright==') for line in platform))

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
