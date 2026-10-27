import contextlib
import importlib.util
import io
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import unittest.mock
from urllib.parse import urlsplit

from hunt import companies
from hunt.catalog import CATALOG
from hunt.__main__ import main
from hunt.core import Store
from hunt.sources import public_url

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('build_company_seeds', ROOT / 'scripts' / 'build_company_seeds.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
KEYWORD_KINDS = {'tencent', 'alibaba', 'meituan', 'feishu'}


def seed(ident, url, provider=None, tags=(), name=None):
    return dict(id=ident, name=name or ident, careers_url=url, provider=provider, tags=list(tags), source='career-ops-china')


class SeedFileTests(unittest.TestCase):
    def test_seed_file_valid(self):
        seeds = companies.load_seeds()
        self.assertGreaterEqual(len(seeds), 50)
        self.assertEqual(len({s['id'] for s in seeds}), len(seeds))
        for s in seeds:
            self.assertTrue(s['id'] and s['name'], s)
            self.assertTrue(public_url(s['careers_url']), s)
            self.assertIn(s['source'], ('catalog', 'career-ops-china', 'career-ops', 'curated', 'encountered'))
            self.assertIsInstance(s['tags'], list)
        self.assertEqual({s['id'] for s in seeds if s['source'] == 'catalog'}, {r['id'] for r in CATALOG})
        data = json.loads((ROOT / 'hunt' / 'data' / 'companies.cn.json').read_text(encoding='utf-8'))
        self.assertEqual(data['generated_from']['repo'], 'shuheng-mo/career-ops-china')
        self.assertRegex(data['generated_from']['commit'], '^[0-9a-f]{40}$')

    def test_provider_matches_detection(self):
        from hunt.providers import REGISTRY, route
        for s in companies.load_seeds():
            if s['provider'] is not None:
                self.assertIn(s['provider'], REGISTRY)
            if s['source'] != 'catalog' and s['provider'] is None:
                self.assertIsNone(route(dict(careers_url=s['careers_url'])), s)


class NontechSeedTests(unittest.TestCase):
    def test_original_53_records_are_unchanged(self):
        # Changed on purpose once (2026-10-27): six seeds moved to their Moka/Feishu tenants (builder.SEED_URLS).
        original = json.dumps(companies.load_seeds()[:53], ensure_ascii=False, sort_keys=True).encode()
        self.assertEqual(hashlib.sha256(original).hexdigest(),
                         '883e400ef54b8e384fddaf62cf20a49e556fecb51315dcecf86cb17f8a6805ca')

    def test_seed_url_fixes_route_to_supported_readers(self):
        from hunt.providers import route
        rows = {s['id']: s for s in companies.load_seeds()}
        for ident, url in builder.SEED_URLS.items():
            row = rows[ident]
            self.assertEqual(row['careers_url'], url)
            self.assertIn(row['provider'], ('mokahr', 'feishu'), ident)
            self.assertIsNone(row.get('status'), ident)
            self.assertEqual(route(dict(careers_url=url)).id, row['provider'])

    def test_at_least_40_nontech_employers_cover_families_and_industries(self):
        from hunt import directions
        families = {r['family'] for r in directions.load()}
        nontech = families - {'技术研发', '产品', '设计', '数据与算法'}
        rows = companies.load_seeds()[53:]
        self.assertGreaterEqual(len(rows), 40)
        self.assertTrue(all(set(r['tags']) & nontech for r in rows))
        tags = set().union(*(set(r['tags']) for r in rows))
        self.assertGreaterEqual(len(tags & nontech), 8)
        for industry in ('消费零售', '金融专业', '制造', '医疗健康', '教育培训', '物流', '能源', '汽车'):
            self.assertIn(industry, tags)

    def test_new_rows_match_nontech_constant_and_builder(self):
        rows = companies.load_seeds()[53:]
        self.assertEqual(rows, builder.NONTECH)
        self.assertEqual(builder.build([])[-len(rows):], rows)
        self.assertTrue(all(r['source'] == 'curated' for r in rows))
        self.assertEqual(len({r['id'] for r in companies.load_seeds()}), len(companies.load_seeds()))

    def test_new_tags_and_provider_detection(self):
        from hunt import directions
        from hunt.providers import route
        families = {r['family'] for r in directions.load()}
        for r in companies.load_seeds()[53:]:
            with self.subTest(company=r['id']):
                self.assertTrue(set(r['tags']) & families)
                self.assertFalse({'ai', 'agent', 'web3', '大模型'} & {tag.casefold() for tag in r['tags']})
                provider = route(dict(careers_url=r['careers_url']))
                self.assertEqual(r['provider'], provider.id if provider else None)


class SelectTests(unittest.TestCase):
    def test_select_includes_keyword_providers(self):
        chosen = companies.select(['产品经理'], 300)
        kinds = {c['kind'] for c in chosen}
        self.assertTrue(KEYWORD_KINDS <= kinds, kinds)
        hosts = {urlsplit(c['careers_url']).hostname for c in chosen if c['kind'] in KEYWORD_KINDS}
        self.assertIn('jobs.bytedance.com', hosts)
        self.assertEqual([c['company'] for c in chosen if c['kind'] == 'feishu'][:1], ['字节跳动'])

    def test_select_entries_are_discover_ready(self):
        from hunt.providers import route
        for c in companies.select(['AI'], 300):
            self.assertTrue(c['company'] and c['id'])
            if c['kind'] == 'website':
                self.assertTrue(c['url']); self.assertNotIn('careers_url', c)
            else:
                self.assertTrue(c['careers_url'])
            self.assertIsNotNone(route(c), c)

    def test_select_entries_run_through_discover(self):
        from hunt.discovery import discover
        from hunt.network import FetchError
        def down(url, **kwargs): raise FetchError('HTTP 500')
        chosen = companies.select(['AI'], 300)
        result = discover(dict(keywords=['AI'], sweep=True, check_entries=False, discovery_sources=chosen), transport=down)
        ids = [r['source_id'] for r in result['sources']]
        self.assertEqual(len(ids), len(chosen))
        self.assertEqual(len(set(ids)), len(ids))
        self.assertNotIn('not_configured', {r['status'] for r in result['sources']})

    def test_seed_status_marks_2026_10_26_failures(self):
        seeds = companies.load_seeds()
        flagged = {}
        for s in seeds:
            self.assertIn(s.get('status'), (None, 'dead', 'needs_adapter'), s)
            if s.get('status'): flagged.setdefault(s['status'], set()).add(s['id'])
        self.assertEqual(len(flagged['dead']), 9)
        self.assertEqual(len(flagged['needs_adapter']), 20)  # 智谱 and 零一万物 left the list once their Feishu tenants were found
        self.assertIn('baichuan-ai-com-careers', flagged['dead'])
        self.assertIn('huawei', flagged['needs_adapter'])
        self.assertFalse({s['id'] for s in seeds if s.get('provider')} & set().union(*flagged.values()))
        self.assertEqual(builder.build([]), [dict(s) for s in seeds if s['source'] != 'career-ops-china' or s['id'] in ('tencent', 'alibaba', 'meituan', 'bytedance')])

    def test_select_skips_dead_and_needs_adapter_unless_asked(self):
        seeds = [seed('ok', 'https://ok.example.test/'), dict(seed('dead', 'https://dead.example.test/'), status='dead'),
                 dict(seed('raw', 'https://raw.example.test/'), status='needs_adapter')]
        self.assertEqual([c['id'] for c in companies.select(['AI'], 10, seeds=seeds)], ['ok'])
        self.assertEqual([c['id'] for c in companies.select(['AI'], 10, seeds=seeds, include_flagged=True)], ['ok', 'dead', 'raw'])
        default = {c['id'] for c in companies.select(['AI'], 300)}
        self.assertNotIn('huawei', default)
        self.assertNotIn('baichuan-ai-com-careers', default)
        self.assertEqual(len(default), len(companies.load_seeds()) - 29)
        self.assertEqual(len(companies.select(['AI'], 300, include_flagged=True)), len(companies.load_seeds()))

    def test_select_keyword_providers_survive_small_limit(self):
        chosen = companies.select(['AI'], 4)
        self.assertEqual(len(chosen), 4)
        self.assertEqual({c['kind'] for c in chosen}, KEYWORD_KINDS)

    def test_select_respects_limit_and_dedup(self):
        extra = [seed('a', 'https://dup.example.test/careers', tags=['AI']), seed('b', 'https://dup.example.test/careers?x=1', tags=['AI'])]
        chosen = companies.select(['AI'], 300, extra)
        self.assertEqual(sum(urlsplit(c.get('url', '')).hostname == 'dup.example.test' for c in chosen), 1)
        self.assertEqual(len(companies.select(['AI'], 5)), 5)

    def test_select_ranks_by_tag_overlap_and_extra_last(self):
        seeds = [seed('x', 'https://x.example.test/', tags=['游戏']), seed('y', 'https://y.example.test/', tags=['AI', 'Agent']),
                 seed('k', 'https://careers.tencent.com/', provider='tencent')]
        extra = [seed('z', 'https://z.example.test/', tags=['AI'], name='Z')]
        order = [c['company'] for c in companies.select(['agent', 'AI'], 10, extra, seeds=seeds)]
        self.assertEqual(order, ['k', 'y', 'x', 'Z'])

    def test_select_marks_relevance_tiers_for_the_sweep(self):
        seeds = [seed('x', 'https://x.example.test/', tags=['游戏']), seed('y', 'https://y.example.test/', tags=['AI', 'Agent']),
                 seed('f', 'https://f.example.test/', tags=['销售与商务']), seed('k', 'https://careers.tencent.com/', provider='tencent', tags=['大厂']),
                 seed('t', 'https://t.jobs.feishu.cn/', provider='feishu', tags=['食品']), seed('u', 'https://u.jobs.feishu.cn/', provider='feishu', tags=['AI'])]
        extra = [seed('z', 'https://z.example.test/', tags=['AI'], name='Z')]
        tiers = {c['company']: c['tier'] for c in companies.select(['AI 产品经理'], 10, extra, seeds=seeds, families=['销售与商务'])}
        # A small unrelated tenant waits with the tail even though its provider searches by keyword.
        self.assertEqual(tiers, dict(k=0, u=0, t=2, y=1, f=1, x=2, Z=3))

    def test_select_extra_dedupes_against_seeds(self):
        seeds = [seed('x', 'https://x.example.test/jobs')]
        chosen = companies.select([], 10, [seed('x2', 'https://X.example.test/jobs/')], seeds=seeds)
        self.assertEqual(len(chosen), 1)


class FamilyPriorityTests(unittest.TestCase):
    def test_family_precedes_keyword_overlap_and_keeps_keyword_providers_first(self):
        rows = [seed('plain', 'https://plain.example.test/', tags=['销售', '质量']),
                seed('family', 'https://family.example.test/', tags=['销售与商务']),
                seed('keyword', 'https://careers.tencent.com/', provider='tencent')]
        chosen = companies.select(['销售', '质量'], 300, seeds=rows, families=['销售与商务'])
        self.assertEqual([r['id'] for r in chosen], ['keyword', 'family', 'plain'])

    def test_family_count_then_term_overlap_then_stable_file_order(self):
        rows = [seed('none', 'https://none.example.test/', tags=['质量']),
                seed('sales', 'https://sales.example.test/', tags=['销售与商务']),
                seed('both1', 'https://both1.example.test/', tags=['销售与商务', '供应链与生产制造']),
                seed('both2', 'https://both2.example.test/', tags=['销售与商务', '供应链与生产制造']),
                seed('both-term', 'https://term.example.test/', tags=['销售与商务', '供应链与生产制造', '质量'])]
        chosen = companies.select(['质量'], 300, seeds=rows, families=['销售与商务', '供应链与生产制造', '销售与商务'])
        self.assertEqual([r['id'] for r in chosen], ['both-term', 'both1', 'both2', 'sales', 'none'])

    def test_empty_families_preserve_existing_order(self):
        self.assertEqual(companies.select(['销售'], 300), companies.select(['销售'], 300, families=()))

    def test_flagged_seeds_and_extra_still_obey_existing_rules(self):
        rows = [dict(seed('bad', 'https://bad.example.test/', tags=['销售与商务']), status='dead'),
                seed('plain', 'https://plain.example.test/')]
        extra = [seed('extra', 'https://extra.example.test/', tags=['销售与商务'])]
        chosen = companies.select([], 300, extra, seeds=rows, families=['销售与商务'])
        self.assertEqual([r['id'] for r in chosen], ['plain', 'extra'])


class RememberTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'app')

    def job(self, **kw):
        return dict(dict(channel='website', company='Newco', url='https://careers.newco.example.test/jobs/1'), **kw)

    def test_remember_adds_once(self):
        with self.store.tx() as c:
            self.assertTrue(companies.remember(c, self.job()))
            self.assertFalse(companies.remember(c, self.job(url='https://careers.newco.example.test/jobs/2')))
            rows = self.store.meta(c, 'encountered_companies')
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]['name'], rows[0]['careers_url'], rows[0]['source']), ('Newco', 'https://careers.newco.example.test/', 'encountered'))

    def test_remember_skips_known_unofficial_and_missing(self):
        with self.store.tx() as c:
            for job in (self.job(company='腾讯', url='https://careers.tencent.com/jobdesc.html?postId=1'),
                        self.job(channel='boss', url='https://www.zhipin.com/job_detail/1.html'),
                        self.job(channel='import', url='https://x.example.test/1'),
                        self.job(company='待确认'), self.job(url=''), self.job(url='ftp://x.example.test/1'),
                        self.job(url='https://boards.greenhouse.io/acme/jobs/1')):
                self.assertFalse(companies.remember(c, job), job)
            self.assertEqual(self.store.meta(c, 'encountered_companies'), [])

    def test_remember_skips_inbox_channels(self):
        with self.store.tx() as c:
            for channel in ('inbox', 'inbox:boss-zhipin', 'inbox:other-site'):
                self.assertFalse(companies.remember(c, self.job(channel=channel)), channel)
            self.assertEqual(self.store.meta(c, 'encountered_companies'), [])

    def test_remember_skips_platform_ats_and_provider_hosts(self):
        hosts = ('www.zhipin.com', 'zhipin.com', 'www.liepin.com', 'www.lagou.com', 'sou.zhaopin.com', 'jobs.51job.com', 'www.linkedin.com',
                 'cn.indeed.com', 'maimai.cn', 'www.nowcoder.com', 'acme.myworkdayjobs.com', 'jobs.smartrecruiters.com',
                 'boards.greenhouse.io', 'jobs.lever.co', 'jobs.ashbyhq.com', 'app.mokahr.com', 'acme.jobs.feishu.cn',
                 'careers.tencent.com', 'talent.alibaba.com', 'zhaopin.meituan.com', 'jobs.bytedance.com')
        with self.store.tx() as c:
            for host in hosts:
                self.assertFalse(companies.remember(c, self.job(company='Co ' + host, url='https://%s/job/1' % host)), host)
            self.assertTrue(companies.remember(c, self.job(company='Fine', url='https://notzhipin.com.example.test/job/1')))

    def test_remember_failure_does_not_block_import(self):
        job = dict(title='工程师', jd='负责系统开发', company='Newco', channel='website', platform_id='1', url='https://careers.newco.example.test/jobs/1')
        with self.store.tx() as c:
            c.execute('UPDATE meta SET value=? WHERE key=?', ('{broken', 'encountered_companies'))
        self.store.import_job(dict(job))
        self.assertEqual(len(self.store.state()['jobs']), 1)
        with unittest.mock.patch.object(companies, 'DATA', ROOT / 'no-such-seeds.json'):
            self.store.import_job(dict(job, platform_id='2', url='https://careers.newco.example.test/jobs/2'))
        self.assertEqual(len(self.store.state()['jobs']), 2)

    def test_load_seeds_reads_file_once(self):
        companies.load_seeds()
        with unittest.mock.patch.object(Path, 'read_text', side_effect=AssertionError('re-read')):
            seeds = companies.load_seeds()
        seeds.pop()
        self.assertEqual(len(companies.load_seeds()), len(seeds) + 1)

    def test_remember_caps_list(self):
        with self.store.tx() as c:
            for n in range(companies.MAX_ENCOUNTERED + 5):
                companies.remember(c, self.job(company='C%d' % n, url='https://c%d.example.test/jobs/1' % n))
            self.assertEqual(len(self.store.meta(c, 'encountered_companies')), companies.MAX_ENCOUNTERED)

    def test_import_job_remembers_new_employer(self):
        self.store.import_job(dict(title='工程师', jd='负责系统开发', company='Newco', channel='website', platform_id='1',
                                   url='https://careers.newco.example.test/jobs/1'))
        with self.store.tx() as c:
            self.assertEqual([r['name'] for r in self.store.meta(c, 'encountered_companies')], ['Newco'])
        state = self.store.state()
        self.assertEqual(len(state['jobs']), 1)

    def test_encountered_feeds_select(self):
        self.store.import_job(dict(title='工程师', jd='负责系统开发', company='Newco', channel='website', platform_id='1',
                                   url='https://careers.newco.example.test/jobs/1'))
        with self.store.tx() as c:
            extra = companies.encountered(c)
        chosen = companies.select(['AI'], 300, extra)
        self.assertEqual(chosen[-1]['company'], 'Newco')
        self.assertEqual(chosen[-1]['kind'], 'website')


class RunWiringTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'app')
        self.seen = []

    def run_store(self, **config):
        self.store.action(dict(action='config', config=dict(dict(keywords=['AI'], check_entries=False), **config)))
        def fake(cfg, **kwargs):
            self.seen.append(cfg)
            return dict(jobs=[], sources=[], queries=['AI'], sweep=None, deadline_reached=False)
        with unittest.mock.patch('hunt.discovery.discover', side_effect=fake):
            self.store.run()
        return self.seen[-1]

    def test_sweep_without_sources_uses_selected_companies(self):
        self.store.import_job(dict(title='工程师', jd='负责系统开发', company='Newco', channel='website', platform_id='1',
                                   url='https://careers.newco.example.test/jobs/1'))
        with self.store.tx() as c:
            extra = companies.encountered(c)
        cfg = self.run_store(sweep=True)
        self.assertEqual(cfg['discovery_sources'], companies.select(['AI'], 300, extra))
        self.assertEqual(cfg['discovery_sources'][-1]['company'], 'Newco')
        self.assertNotIn('discovery_sources', self.store.state()['config'])

    def test_sweep_passes_distinct_orientation_families_in_direction_order(self):
        self.store.directions_set(dict(directions=['b2b-enterprise-sales', 'channel-sales', 'quality-engineer']))
        with unittest.mock.patch('hunt.companies.select', wraps=companies.select) as select:
            self.run_store(sweep=True)
        self.assertEqual(select.call_args.kwargs['families'], ['销售与商务', '供应链与生产制造'])

    def test_explicit_sources_win_and_non_sweep_unchanged(self):
        mine = [dict(kind='website', url='https://mine.example.test/', company='Mine')]
        self.assertEqual(self.run_store(sweep=True, discovery_sources=mine)['discovery_sources'], mine)
        self.assertNotIn('discovery_sources', self.run_store(sweep=False))


class YamlReaderTests(unittest.TestCase):
    SAMPLE = '''title_filter:
  negative:
    - "实习"
tracked_companies:

  # =====================================================
  # 一线互联网大厂
  # =====================================================

  - name: 甲公司
    careers_url: https://a.example.test/jobs?x=1&y=2
    scan_method: playwright
    notes: "有 # 号 和: 冒号"
    enabled: true

  - name: 乙（Beta）
    careers_url: 'https://b.example.test/careers'
    enabled: false  # 已并购

  # =====================================================
  # 远程友好 / 海外
  # =====================================================

  - name: 丙
    careers_url: https://c.example.test/

other_section:
  - name: 不是公司
    careers_url: https://nope.example.test/
'''

    def test_reader(self):
        rows = builder.read_tracked_companies(self.SAMPLE)
        self.assertEqual([r['name'] for r in rows], ['甲公司', '乙（Beta）', '丙'])
        self.assertEqual(rows[0]['careers_url'], 'https://a.example.test/jobs?x=1&y=2')
        self.assertEqual(rows[0]['notes'], '有 # 号 和: 冒号')
        self.assertEqual(rows[0]['section'], '一线互联网大厂')
        self.assertIs(rows[0]['enabled'], True)
        self.assertEqual(rows[1]['careers_url'], 'https://b.example.test/careers')
        self.assertIs(rows[1]['enabled'], False)
        self.assertEqual(rows[2]['section'], '远程友好 / 海外')
        self.assertIs(rows[2]['enabled'], True)

    def test_reader_stops_at_next_top_level_key(self):
        self.assertNotIn('不是公司', [r['name'] for r in builder.read_tracked_companies(self.SAMPLE)])

    def test_main_reports_rows_without_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'coc' / 'templates').mkdir(parents=True)
            (root / 'coc' / 'templates' / 'portals-china.example.yml').write_text(
                'tracked_companies:\n  - name: 有链接\n    careers_url: https://has.example.test/\n  - name: 无链接\n    notes: x\n', encoding='utf-8')
            (root / 'pins.txt').write_text('shuheng-mo/career-ops-china ' + 'a' * 40 + ' MIT\n', encoding='utf-8')
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = builder.main(['--upstream', str(root), '--out', str(root / 'out.json')])
            self.assertEqual(code, 0)
            self.assertIn('跳过 1 行', out.getvalue())
            names = [c['name'] for c in json.loads((root / 'out.json').read_text(encoding='utf-8'))['companies']]
            self.assertIn('有链接', names); self.assertNotIn('无链接', names)

    def test_missing_upstream_fails_clearly(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = builder.main(['--upstream', str(ROOT / 'no-such-dir')])
        self.assertEqual(code, 1)
        self.assertIn('portals-china.example.yml', err.getvalue())


class CLITests(unittest.TestCase):
    def invoke(self, arguments):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(arguments)
        return code, out.getvalue()

    def test_cli_companies_json(self):
        code, output = self.invoke(['companies', '--json', '--limit', '3'])
        self.assertEqual(code, 0)
        result = json.loads(output)
        self.assertEqual(len(result['companies']), 3)

    def test_cli_companies_text_with_terms(self):
        rows = [seed('keyword', 'https://careers.tencent.com/', provider='tencent')]
        rows += [seed('plain-%d' % i, 'https://c%d.example.test/' % i) for i in range(11)]
        with unittest.mock.patch.object(companies, 'load_seeds', return_value=rows):
            code, output = self.invoke(['companies', '--terms', 'AI', '产品经理', '--limit', '12'])
        self.assertEqual(code, 0)
        self.assertEqual(len(output.strip().splitlines()), 12)
        self.assertIn('website', output)


if __name__ == '__main__':
    unittest.main()
