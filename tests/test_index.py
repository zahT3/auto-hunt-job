"""The job library (hunt.search.index): migration of an old library, full-text search, freshness and cross-source groups.

All data is synthetic; nothing is fetched.
"""
import contextlib
import http.client
import io
import json
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote

from hunt.app.cli import main
from hunt.app.server import make_server
from hunt.app.store import Store
from hunt.base import Error, dumps
from hunt.search import index

LEGACY = Path(__file__).parent / 'fixtures' / 'legacy-064dcda.sql'


def legacy_library(root):
    """A data directory written by the program at 064dcda: jobs(id, identity, data) and no schema_version."""
    root.mkdir(parents=True, exist_ok=True)
    with contextlib.closing(sqlite3.connect(str(root / 'state.sqlite3'))) as c:
        c.executescript(LEGACY.read_text(encoding='utf-8'))
    return root


class LegacyLibrary(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = legacy_library(Path(self.tmp.name) / 'app')
        with contextlib.closing(sqlite3.connect(str(self.root / 'state.sqlite3'))) as c:
            self.before = dict(c.execute('SELECT identity, data FROM jobs'))

    def tearDown(self):
        self.tmp.cleanup()

    def rows(self):
        with contextlib.closing(sqlite3.connect(str(self.root / 'state.sqlite3'))) as c:
            c.row_factory = sqlite3.Row
            return {r['identity']: dict(r) for r in c.execute('SELECT * FROM jobs')}

    def test_fixture_is_the_old_format(self):
        with contextlib.closing(sqlite3.connect(str(self.root / 'state.sqlite3'))) as c:
            self.assertEqual([r[1] for r in c.execute('PRAGMA table_info(jobs)')], ['id', 'identity', 'data'])
            self.assertIsNone(c.execute("SELECT 1 FROM meta WHERE key='schema_version'").fetchone())
        self.assertEqual(len(self.before), 5)

    def test_opening_upgrades_columns_and_keeps_the_json(self):
        store = Store(self.root)
        rows = self.rows()
        self.assertEqual({k: r['data'] for k, r in rows.items()}, self.before)
        with store.tx() as c:
            self.assertEqual(store.meta(c, 'schema_version'), index.SCHEMA_VERSION)
        feishu, card, ali, paste = rows['feishu:7300000000000000001'], rows['liepin:LP001'], rows['alibaba:ALI9'], rows['url:https://careers.example.com/jobs/42']
        self.assertEqual((feishu['company'], feishu['title'], feishu['city'], feishu['source'], feishu['source_id'], feishu['platform_id']),
                         ('字节跳动', 'AI产品经理-抖音电商', '深圳', 'feishu', 'feishu:jobs.bytedance.com', '7300000000000000001'))
        self.assertEqual(card['city'], '深圳')  # 深圳市南山区
        self.assertEqual(ali['city'], '杭州/北京')
        self.assertEqual(paste['city'], None)  # 地点未知
        self.assertEqual(feishu['first_seen'], '2026-10-27T04:00:00.000000+00:00')
        self.assertGreater(feishu['last_seen'], feishu['first_seen'])  # the later source_changed event
        self.assertEqual((ali['status'], feishu['status'], card['status']), ('closed', 'open', 'open'))
        self.assertEqual(len(store.state()['jobs']), 5)

    def test_upgrade_runs_once_and_search_reads_old_rows(self):
        Store(self.root)
        store = Store(self.root)
        with store.tx() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM jobs_fts').fetchone()[0], 5)
        with store.tx() as c:
            found = index.search(c, '大模型 MaaS')
        self.assertEqual([g['company'] for g in found['groups']], ['阿里巴巴'])

    def test_old_identities_still_deduplicate(self):
        store = Store(self.root)
        _, duplicate = store.import_job(dict(title='大模型产品专家', jd='负责 MaaS 平台。', company='阿里巴巴', channel='alibaba',
                                             platform_id='ALI9', location='杭州/北京'))
        self.assertTrue(duplicate)
        self.assertEqual(len(self.rows()), 5)

    def test_a_newer_library_is_refused(self):
        Store(self.root)
        with contextlib.closing(sqlite3.connect(str(self.root / 'state.sqlite3'))) as c:
            c.execute("UPDATE meta SET value='99' WHERE key='schema_version'"); c.commit()
        with self.assertRaisesRegex(Error, '更新版本'):
            Store(self.root)


def job(n, title, company, location, jd='', channel='feishu', source_id=None):
    return dict(id='job-%d' % n, title=title, company=company, location=location, jd=jd or title + ' 的岗位职责。', channel=channel,
                platform_id='p%d' % n, raw=dict(discovery=dict(source_id=source_id or channel)), availability='open')


class Search(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / 'app')

    def tearDown(self):
        self.tmp.cleanup()

    def add(self, *jobs, at=None):
        with self.store.tx() as c:
            for j in jobs: index.insert(c, j, j['channel'] + ':' + j['platform_id'], at=at)

    def test_words_of_any_length_must_all_match_title_or_jd(self):
        self.add(job(1, 'AI产品经理', '甲', '深圳'), job(2, '产品经理', '乙', '深圳', jd='负责 AI 助手。'),
                 job(3, '产品经理', '丙', '深圳'), job(4, 'ai 产品运营', '丁', '深圳'))
        self.assertEqual({g['company'] for g in self.store.search_jobs('AI 产品经理')['groups']}, {'甲', '乙'})
        self.assertEqual({g['company'] for g in self.store.search_jobs('产品')['groups']}, {'甲', '乙', '丙', '丁'})  # 2 characters: LIKE
        self.assertEqual({g['company'] for g in self.store.search_jobs('Ai')['groups']}, {'甲', '乙', '丁'})
        self.assertEqual(self.store.search_jobs('100%')['groups'], [])  # LIKE wildcards are literal
        first = self.store.search_jobs('AI 产品经理')['groups'][0]
        self.assertEqual((first['company'], first['title_match']), ('甲', True))  # title hits rank above JD-only hits

    def test_filters(self):
        self.add(job(1, 'AI 产品经理', '甲', '广东省深圳市南山区'), job(2, 'AI 产品经理', '乙', '北京/深圳', channel='liepin'),
                 job(3, 'AI 产品经理', '丙', '上海'))
        with self.store.tx() as c:
            c.execute("UPDATE jobs SET direction='ai-product-manager' WHERE id='job-3'")
        self.assertEqual({g['company'] for g in self.store.search_jobs('AI 产品经理', city='深圳市')['groups']}, {'甲', '乙'})
        self.assertEqual({g['company'] for g in self.store.search_jobs('AI 产品经理', city='Shenzhen')['groups']}, {'甲', '乙'})
        self.assertEqual([g['company'] for g in self.store.search_jobs('', source='liepin')['groups']], ['乙'])
        self.assertEqual([g['company'] for g in self.store.search_jobs('', direction='ai-product-manager')['groups']], ['丙'])
        with self.assertRaises(Error): self.store.search_jobs('', limit=0)
        with self.assertRaises(Error): self.store.search_jobs('', fresh=0)

    def test_remote_is_a_place_and_a_version_2_library_rederives_it(self):
        self.add(job(1, 'AI 产品经理', '甲', '深圳/远程'), job(2, 'AI 产品经理', '乙', 'Remote'), job(3, 'AI 产品经理', '丙', '深圳'))
        self.assertEqual({g['company'] for g in self.store.search_jobs('', city=['远程'])['groups']}, {'甲', '乙'})
        with self.store.tx() as c:  # as version 2 left it: 远程 was not a place yet
            c.execute("UPDATE jobs SET city='深圳' WHERE id='job-1'"); c.execute("UPDATE jobs SET city='remote' WHERE id='job-2'")
            c.execute("UPDATE meta SET value='2' WHERE key='schema_version'")
        store = Store(self.store.root)
        with store.tx() as c:
            self.assertEqual(dict(c.execute('SELECT id, city FROM jobs')), {'job-1': '深圳/远程', 'job-2': '远程', 'job-3': '深圳'})
            self.assertEqual(store.meta(c, 'schema_version'), 3)

    def test_city_takes_a_list_and_any_city_matches(self):
        self.add(job(1, 'AI 产品经理', '甲', '深圳'), job(2, 'AI 产品经理', '乙', '杭州'), job(3, 'AI 产品经理', '丙', '上海'),
                 job(4, 'AI 产品经理', '丁', '北京/杭州'))
        result = self.store.search_jobs('AI 产品经理', city=['深圳市', 'Hangzhou', '杭州', '大理', ' '])
        self.assertEqual({g['company'] for g in result['groups']}, {'甲', '乙', '丁'})
        self.assertEqual(result['query']['city'], ['深圳', '杭州', '大理'])  # an unlisted place stays as given
        self.assertEqual(self.store.search_jobs('', city='深圳')['query']['city'], ['深圳'])
        self.assertEqual(self.store.search_jobs('', city=[])['total_groups'], 4)  # an empty list does not filter
        with self.assertRaisesRegex(Error, '最多 10 个'): self.store.search_jobs('', city=['城%d' % n for n in range(11)])
        with self.assertRaises(Error): self.store.search_jobs('', city=[1])

    def test_fresh_keeps_open_jobs_seen_lately(self):
        self.add(job(1, 'AI 产品经理', '旧', '深圳'), at='2020-01-01T00:00:00.000000+00:00')
        self.add(job(2, 'AI 产品经理', '新', '深圳'), job(3, 'AI 产品经理', '下线', '深圳'))
        with self.store.tx() as c:
            c.execute("UPDATE jobs SET status='closed' WHERE id='job-3'")
        self.assertEqual([g['company'] for g in self.store.search_jobs('产品经理', fresh=7)['groups']], ['新'])
        everything = self.store.search_jobs('产品经理')['groups']
        self.assertEqual(len(everything), 3)
        self.assertEqual(everything[-1]['status'], 'closed')  # closed last

    def test_same_company_title_and_city_link_into_one_group_without_merging(self):
        self.add(job(1, 'AI产品经理-抖音电商', '字节跳动', '深圳', source_id='feishu:jobs.bytedance.com'),
                 job(2, 'AI 产品经理 - 抖音电商', '字节跳动有限公司', '深圳市', channel='liepin'),
                 job(3, 'AI产品经理-抖音电商', '字节跳动', '北京'),  # other city
                 job(4, 'AI产品经理-抖音电商', '待确认', '深圳', channel='boss'))  # unknown company never groups
        groups = self.store.search_jobs('抖音电商', source='liepin')['groups']
        self.assertEqual(len(groups), 1)
        self.assertEqual([(s['source'], s['matched']) for s in groups[0]['sources']], [('liepin', True), ('feishu', False)])
        everything = self.store.search_jobs('抖音电商')
        self.assertEqual((everything['total_groups'], everything['total_jobs']), (3, 4))
        with self.store.tx() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM jobs').fetchone()[0], 4)

    def test_two_jobs_under_one_key_on_the_same_source_stay_apart(self):
        self.add(job(1, 'AI产品经理-抖音电商', '字节跳动', '深圳'), job(2, 'AI产品经理-抖音电商', '字节跳动', '深圳'),
                 job(3, 'AI产品经理-抖音电商', '字节跳动', '深圳', channel='liepin'))
        groups = self.store.search_jobs('抖音电商')['groups']
        self.assertEqual(sorted(len(g['sources']) for g in groups), [1, 1, 1])
        self.assertEqual(len(self.store.search_jobs('抖音电商', source='liepin')['groups'][0]['sources']), 1)

    def test_a_save_keeps_columns_and_text_index_current(self):
        self.add(job(1, '数据分析师', '甲', '深圳'))
        with self.store.tx() as c:
            j = self.store.job(c, 'job-1')
            j.update(title='AI 产品经理', jd='负责 Agent 产品。', location='杭州', direction=dict(id='ai-product-manager'))
            self.store.save(c, j)
        found = self.store.search_jobs('产品经理', city='杭州', direction='ai-product-manager')['groups']
        self.assertEqual([g['title'] for g in found], ['AI 产品经理'])
        self.assertEqual(self.store.search_jobs('数据分析师')['groups'], [])

    def test_without_fts5_search_falls_back_to_like(self):
        self.add(job(1, 'AI 产品经理', '甲', '深圳'))
        with self.store.tx() as c:
            c.execute('DROP TABLE jobs_fts')
            result = index.search(c, 'AI 产品经理', city='深圳')
        self.assertEqual((result['full_text'], [g['company'] for g in result['groups']]), (False, ['甲']))


COMPANIES = ['字节跳动', '腾讯', '阿里巴巴', '美团', '小红书', '滴滴', '京东', '网易', '快手', '智谱 AI', 'MiniMax', '蔚来', '小米', '携程', '百度']
TITLES = ['AI 产品经理', 'AI产品经理-电商', '大模型产品经理', '产品经理', '后端开发工程师', '数据分析师', 'AI 算法工程师', '产品运营', '高级 AI 产品经理（Agent）', '前端工程师']
CITIES = ['深圳', '北京', '上海', '杭州', '广东省深圳市南山区', '北京/深圳', '成都']
FILLER = '负责需求分析、方案设计与跨团队推进，关注用户体验与业务指标。' * 12


def synthetic_library(store, count=1500):
    with store.tx() as c:
        for n in range(count):
            title, company, city = TITLES[n % len(TITLES)], COMPANIES[(n // 3) % len(COMPANIES)], CITIES[(n // 7) % len(CITIES)]
            jd = ('熟悉 LLM 与 AI 应用落地。' if n % 4 == 0 else '熟悉 SQL 与数据仓库。') + FILLER
            index.insert(c, job(n, title, company, city, jd=jd, channel=('feishu', 'liepin', 'boss')[n % 3]), 'syn:%d' % n)


class LibraryOf1500(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.data = Path(cls.tmp.name) / 'app'
        synthetic_library(Store(cls.data))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_cli_search_returns_within_a_second(self):
        out = io.StringIO()
        began = time.monotonic()
        with contextlib.redirect_stdout(out):
            code = main(['search', 'AI 产品经理', '--city', '深圳', '--json', '--data', str(self.data)])
        elapsed = time.monotonic() - began
        self.assertEqual(code, 0)
        self.assertLess(elapsed, 1.0)
        result = json.loads(out.getvalue())
        store = Store(self.data)
        with store.tx() as c:
            expected = {j['id'] for j in index.all_jobs(c) if '深圳' in index.cities(j['location'])
                        and all(w in (j['title'] + j['jd']).casefold() for w in ('ai', '产品经理'))}
        matched = {s['job_id'] for g in store.search_jobs('AI 产品经理', city='深圳', limit=500)['groups'] for s in g['sources'] if s['matched']}
        self.assertEqual(matched, expected)
        self.assertEqual(result['total_jobs'], len(expected))
        self.assertTrue(result['groups'] and all('深圳' in g['city'].split('/') for g in result['groups']))
        self.assertEqual(set(result['groups'][0]), {'group', 'title', 'company', 'city', 'status', 'title_match', 'direction',
                                                     'first_seen', 'last_seen', 'sources'})
        self.assertEqual(set(result['groups'][0]['sources'][0]), {'job_id', 'source', 'source_id', 'platform_id', 'direction',
                                                                   'first_seen', 'last_seen', 'status', 'url', 'application_url',
                                                                   'salary', 'location', 'matched'})

    def test_cli_city_repeats(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(['search', 'AI 产品经理', '--city', '深圳', '--city', '成都', '--limit', '500', '--json', '--data', str(self.data)])
        result = json.loads(out.getvalue())
        self.assertEqual((code, result['query']['city']), (0, ['深圳', '成都']))
        cities = [set(g['city'].split('/')) for g in result['groups']]
        self.assertTrue(any('成都' in c for c in cities) and any('深圳' in c for c in cities))
        self.assertTrue(all(c & {'深圳', '成都'} for c in cities))

    def test_cli_errors_are_json(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(['search', '--limit', '0', '--json', '--data', str(self.data)])
        self.assertEqual((code, json.loads(out.getvalue())['error']), (1, 'limit 必须是 1 至 500'))


class Freshness(unittest.TestCase):
    """Store.run with discovery replaced by fixture rounds; each round reports its sources as the engine does."""
    TERMS = ['AI 产品经理']

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / 'app')
        with self.store.tx() as c:
            self.store.setmeta(c, 'config', dict(self.store.meta(c, 'config'), keywords=self.TERMS))

    def tearDown(self):
        self.tmp.cleanup()

    def item(self, pid, title='AI 产品经理', source='feishu:jobs.example.cn'):
        return dict(title=title, jd=title + '：负责产品规划。', company='示例公司', location='深圳', channel='feishu', platform_id=pid,
                    url='https://jobs.example.cn/position/' + pid, status='open',
                    raw=dict(discovery=dict(source_id=source, queries=self.TERMS)))

    def round(self, items, status='ok', truncated=False, source='feishu:jobs.example.cn'):
        result = dict(jobs=items, queries=self.TERMS, sources=[dict(source_id=source, kind='feishu', status=status, truncated=truncated)])
        with patch('hunt.search.engine.discover', return_value=result):
            return self.store.run()

    def listing(self):
        with self.store.tx() as c:
            return {r[0]: (r[1], r[2]) for r in c.execute('SELECT platform_id, status, missed FROM jobs')}

    def test_two_clean_rounds_without_a_job_close_it(self):
        first = self.round([self.item('A'), self.item('B'), self.item('C', title='Go 后端工程师')])
        self.assertEqual(first['freshness']['seen'], 3)
        self.round([self.item('A')])
        self.assertEqual(self.listing()['B'], ('open', 1))
        self.round([self.item('A')], status='fetch_error')  # an erroring round says nothing
        self.round([self.item('A')], truncated=True)  # nor does a truncated one
        self.assertEqual(self.listing()['B'], ('open', 1))
        last = self.round([self.item('A')])
        self.assertEqual(last['freshness']['closed'], 1)
        listing = self.listing()
        self.assertEqual(listing['B'], ('closed', 2))
        self.assertEqual(listing['A'], ('open', 0))
        self.assertEqual(listing['C'], ('open', 0))  # this round's terms do not match its title
        self.assertEqual([g['status'] for g in self.store.search_jobs('AI 产品经理', fresh=30)['groups']], ['open'])
        self.round([self.item('A'), self.item('B')])
        self.assertEqual(self.listing()['B'], ('open', 0))  # it came back

    def test_other_sources_do_not_count(self):
        self.round([self.item('A'), self.item('B')])
        self.round([], source='feishu:other.example.cn')
        self.round([], source='feishu:other.example.cn')
        self.assertEqual(self.listing()['B'], ('open', 0))


class WebSearch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / 'app')
        with self.store.tx() as c:
            index.insert(c, job(1, 'AI 产品经理', '甲', '深圳'), 'feishu:p1')
        self.server = make_server(self.store, port=0)
        self.port = self.server.server_port
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.tmp.cleanup()

    def get(self, path, host=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        connection.request('GET', path, headers={'Host': host or '127.0.0.1:%d' % self.port})
        response = connection.getresponse()
        body = json.loads(response.read())
        connection.close()
        return response.status, body

    def test_get_search_is_read_only_and_same_origin(self):
        status, body = self.get('/api/search?q=' + quote('AI 产品经理') + '&city=' + quote('深圳') + '&limit=5')
        self.assertEqual((status, [g['company'] for g in body['groups']], body['query']['limit']), (200, ['甲'], 5))
        self.assertEqual(self.get('/api/search?limit=x')[0], 400)
        self.assertEqual(self.get('/api/search?fresh=0')[0], 400)
        self.assertEqual(self.get('/api/search', host='evil.example')[0], 403)

    def test_get_search_takes_repeated_city(self):
        with self.store.tx() as c:
            index.insert(c, job(2, 'AI 产品经理', '乙', '杭州'), 'feishu:p2')
            index.insert(c, job(3, 'AI 产品经理', '丙', '上海'), 'feishu:p3')
        status, body = self.get('/api/search?q=' + quote('产品经理') + '&city=' + quote('深圳') + '&city=' + quote('杭州') + '&city=')
        self.assertEqual((status, {g['company'] for g in body['groups']}, body['query']['city']), (200, {'甲', '乙'}, ['深圳', '杭州']))
        self.assertEqual(self.get('/api/search?' + '&'.join('city=c%d' % n for n in range(11)))[0], 400)


if __name__ == '__main__':
    unittest.main()
