"""猎聘 card mode: jobs from a rendered search page's cards, kept by title, never replacing a fully read job."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hunt.app.store import Store
from hunt.base import Error
from hunt.search.engine import discover, source_configs
from hunt.search.parse import liepin_cards

SEARCH = 'https://www.liepin.com/zhaopin/?key=AI'


def card(ident, title, company='示例科技', place='上海-徐汇区', salary='30-50k·14薪', href=None):
    """One result card shaped like 猎聘's rendered DOM (hashed class names beside the stable ones)."""
    href = href or 'https://www.liepin.com/job/%d.shtml?pgRef=c_pc_search_page&skId=ab&index=0' % ident
    return ('<div class="_40108OjE3M jobCardPcContainer"><div class="_40108hXUg3 jobDetailBox">'
            '<a data-nick="job-detail-job-info" href="%s"><div class="_40108ZRrnt jobTitleBox">'
            '<div class="ellipsis-1" title="招聘%s">%s</div><div><span>【</span><span class="ellipsis-1">%s</span><span>】</span></div></div>'
            '<span class="_40108qjbMk">%s</span><div><span>3-5年</span><span>本科</span></div></a>'
            '<div data-nick="job-detail-company-info"><span class="_40108KCzFk companyName ellipsis-1">%s</span>'
            '<div><span>互联网</span><span>100-499人</span></div></div></div>'
            '<div class="jobCardRightBox"><div class="recruiterName">王女士·HR</div><div>刚刚在线</div></div></div>'
            % (href, title, title, place, salary, company))


def page(*cards):
    return '<html><body><div class="job-list-box">%s</div></body></html>' % ''.join(cards)


class ParserTests(unittest.TestCase):
    def test_cards_become_summary_jobs_without_the_recruiter(self):
        html = page(card(1986324371, 'AI 产品经理'), card(1986324371, '重复卡片'), card(80138007, '猎头岗', href='https://www.liepin.com/a/80138007.shtml'),
                    card(1, '外链', href='https://evil.example/job/1.shtml'))
        jobs = liepin_cards(html, SEARCH)
        self.assertEqual([j['platform_id'] for j in jobs], ['1986324371'])
        job = jobs[0]
        self.assertEqual((job['channel'], job['title'], job['company'], job['location'], job['salary'], job['url']),
                         ('liepin', 'AI 产品经理', '示例科技', '上海-徐汇区', '30-50k·14薪', 'https://www.liepin.com/job/1986324371.shtml'))
        self.assertTrue(job['jd'].startswith('猎聘搜索结果卡片，不含完整职位描述。'))
        self.assertIn('100-499人', job['jd'])
        self.assertNotIn('王女士', job['jd'])
        self.assertEqual((job['raw']['extraction'], job['raw']['summary_only']), ('search_card', True))

    def test_verification_page_stops_instead_of_reading_nothing(self):
        with self.assertRaises(Exception) as error:
            liepin_cards('<html><body>请完成安全验证</body></html>', SEARCH)
        self.assertEqual(error.exception.status, 'captcha')


class Reader:
    """Stands in for BrowserReader: answers search pages from `pages`, records every URL it is asked for."""
    def __init__(self, pages):
        self.pages, self.reads, self.denied_requests = pages, [], []

    def __call__(self, kind, **kw): return self
    def __enter__(self): return self
    def __exit__(self, *a): pass

    def read(self, url):
        self.reads.append(url)
        if '/zhaopin/' not in url: raise AssertionError('card mode opened a detail page: ' + url)
        return page(*self.pages.get(url.split('currentPage=')[1].split('&')[0], [])).encode()


def run(reader, **config):
    with patch('hunt.search.sources_browser.BrowserReader', reader):
        return discover(dict(dict(sources=['liepin'], source_modes={'liepin': 'browser'}, liepin_cards=True, keywords=['AI'],
                                  max_pages=2, check_entries=True), **config),
                        transport=lambda *a, **k: (_ for _ in ()).throw(AssertionError('plain request to 猎聘')))


class DiscoveryTests(unittest.TestCase):
    def test_card_mode_reads_only_search_pages_keeps_by_title_and_skips_entry_checks(self):
        reader = Reader({'0': [card(1, 'AI 产品经理'), card(2, '会计'), card(3, '大模型算法工程师')],
                         '1': [card(3, '大模型算法工程师'), card(4, '人工智能训练师')]})
        result = run(reader)
        report = result['sources'][0]
        self.assertEqual([j['title'] for j in result['jobs']], ['AI 产品经理', '大模型算法工程师', '人工智能训练师'])
        self.assertEqual((report['status'], report['cards'], report['fetched'], report['filtered'], report['pages']), ('ok', True, 4, 1, 2))
        self.assertEqual(len(reader.reads), 2)
        self.assertNotIn('entry_check', result['jobs'][0]['raw'].get('application_route', {}))

    def test_card_mode_stops_at_the_job_limit(self):
        reader = Reader({'0': [card(n, 'AI 工程师 %d' % n) for n in range(1, 41)]})
        result = run(reader, max_jobs=5)
        self.assertEqual(len(result['jobs']), 5)
        self.assertTrue(result['sources'][0]['truncated'])

    def test_switch_only_reaches_liepin_and_defaults_off(self):
        self.assertEqual(source_configs(dict(sources=['liepin', 'boss'], source_modes={'liepin': 'browser'}, liepin_cards=True)),
                         [dict(id='liepin', kind='liepin', mode='browser', cards=True), dict(id='boss', kind='boss', mode='public')])
        self.assertNotIn('cards', source_configs(dict(sources=['liepin']))[0])


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'app')

    def job(self, jd, summary):
        raw = dict(source_kind='liepin', summary_only=True) if summary else dict(source_kind='liepin')
        return dict(channel='liepin', platform_id='1986324371', title='AI 产品经理', jd=jd, url='https://www.liepin.com/job/1986324371.shtml', raw=raw)

    def test_a_card_never_replaces_a_full_job_but_a_full_read_replaces_a_card(self):
        full, card_text = '岗位职责：负责大模型产品规划。任职要求：3年以上产品经验。', '猎聘搜索结果卡片，不含完整职位描述。\nAI 产品经理'
        self.store.import_job(self.job(full, summary=False))
        saved, duplicate = self.store.import_job(self.job(card_text, summary=True))
        self.assertTrue(duplicate)
        self.assertEqual(saved['jd'], full)
        other = self.job(card_text, summary=True); other['platform_id'] = '2'
        self.store.import_job(other)
        upgraded, _ = self.store.import_job(dict(self.job(full, summary=False), platform_id='2'))
        self.assertEqual(upgraded['jd'], full)
        self.assertNotIn('summary_only', upgraded['raw'])

    def test_config_switch_must_be_a_boolean(self):
        self.store.action(dict(action='config', config=dict(targets_confirmed=True, liepin_cards=True)))
        self.assertIs(self.store.state()['config']['liepin_cards'], True)
        with self.assertRaises(Error):
            self.store.action(dict(action='config', config=dict(targets_confirmed=True, liepin_cards='yes')))


if __name__ == '__main__':
    unittest.main()
