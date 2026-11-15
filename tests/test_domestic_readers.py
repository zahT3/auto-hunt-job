import json
import unittest
from unittest import mock

from hunt.search.parse import SourceError
from hunt.search.sources import domestic

REPORT = lambda: dict(pages=0, fetched=0, truncated=False, search_url=None)


def js_literal(data):
    """What a bundler emits for JSON.parse('...'): \\uXXXX for most non-ASCII, but \\xHH for U+0080-U+00FF."""
    text = json.dumps(data, ensure_ascii=True)
    return "var x=JSON.parse('" + text.replace('\\u00b7', '\\xb7').replace("'", "\\'") + "');"


class EmbeddedJson(unittest.TestCase):
    def test_js_hex_escape_is_decoded(self):
        script = js_literal(dict(jobs=[dict(id='a', title='x·y')]))
        self.assertIn('\\xb7', script)
        self.assertEqual(domestic.embedded_json(script)['jobs'][0]['title'], 'x·y')

    def test_no_job_literal_still_raises(self):
        with self.assertRaises(SourceError):
            domestic.embedded_json("JSON.parse('{\"other\":1}')")


class DeepSeek(unittest.TestCase):
    def test_reads_jobs_from_the_main_script(self):
        base = 'https://app.mokahr.com/social-recruitment/high-flyer/1#/job/'
        row = dict(id='j1', title='AI 产品经理', descriptionHtml='<p>负责 · 产品</p>', locations=['北京'],
                   detailUrl=base + 'j1', submitUrl=base + 'j1/apply')
        script = js_literal(dict(crawledAt='2026-11-13T00:00:00Z', jobs=[row]))
        page = b'<html><script defer src="/static/main.abc.js"></script></html>'
        read = lambda url, **k: script.encode() if url.endswith('.js') else page
        jobs = list(domestic.read_jobs(dict(url='https://talent.deepseek.com/'), read, ['产品经理'], 5, 3, REPORT()))
        self.assertEqual([j['title'] for j in jobs], ['AI 产品经理'])


class Okx(unittest.TestCase):
    PAGE = '<html><script src="https://www.okx.com/cdn/assets/okfe/assistance/assets/openings-AbC_1-x.js"></script></html>'
    OLD = '<html><script src="https://www.okx.com/cdn/assets/okfe/assistance/openings/abc.js"></script></html>'

    def run_reader(self, page):
        seen = []
        def read(url, **k):
            seen.append(url)
            return page.encode() if url.endswith('/openings') else b'const Z=`https://boards.greenhouse.io/okx/jobs/`'
        def board(entry, read, terms, limit, pages, child):
            self.assertEqual(entry['board'], 'okx')
            yield dict(title='Product Manager', raw={})
        with mock.patch.object(domestic, 'read_board', board), mock.patch.object(domestic, 'attach_route', lambda job, ref: job):
            jobs = list(domestic.read_jobs(dict(url='https://www.okx.com/zh-hant/join-us/openings'), read, ['product manager'], 5, 3, REPORT()))
        return jobs, seen

    def test_current_script_path(self):
        jobs, seen = self.run_reader(self.PAGE)
        self.assertEqual(len(jobs), 1)
        self.assertTrue(seen[-1].endswith('/assets/openings-AbC_1-x.js'))

    def test_previous_script_path_still_works(self):
        self.assertEqual(len(self.run_reader(self.OLD)[0]), 1)

    def test_missing_script_reports_changed_reference(self):
        with self.assertRaises(SourceError) as cm:
            self.run_reader('<html></html>')
        self.assertEqual(cm.exception.status, 'parse_error')


if __name__ == '__main__':
    unittest.main()
