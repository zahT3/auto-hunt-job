import contextlib
import copy
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from hunt import benchmark
from hunt.__main__ import DEFAULT_DATA, main, parser
from hunt.core import Store


COLLECTED = '2026-10-28T10:00:00+08:00'


def truth_list():
    names = ['星河', '远山', '海风']
    titles = [['AI 产品经理', '数据产品经理', '算法工程师', '设计师'],
              ['后端工程师', '前端工程师', '测试工程师'], ['运营', '售前', '数据分析师']]
    return dict(direction_id='ai-product-manager', collected_at=COLLECTED, companies=[
        dict(name=name, careers_url='https://careers.example/' + str(i), jobs=[
            dict(title=title, url='https://careers.example/%d/%d' % (i, n)) for n, title in enumerate(rows)])
        for i, (name, rows) in enumerate(zip(names, titles))])


def job(title, company='星河', **fields):
    return dict(dict(title=title, company=company, collected_at=COLLECTED), **fields)


class MatchingTests(unittest.TestCase):
    def setUp(self):
        self.truth = truth_list()

    def test_title_normalizes_width_case_nested_brackets_and_punctuation(self):
        for title in ['ＡＩ 产品经理（北京）', 'AI产品经理', 'ai-产品_经理/·,，.。:：|',
                      'AI【远程（北京）】产品[高级]经理', 'AI（北京【远程】）产品经理', 'AI\t产品\n经理']:
            with self.subTest(title=title):
                self.assertEqual(benchmark.normalize_title(title), 'ai产品经理')
        self.assertEqual(benchmark.normalize_title('Straße'), 'strasse')
        self.assertEqual(benchmark.normalize_title(None), '')

    def test_company_normalizes_suffixes_and_nested_brackets(self):
        for name in [' 星 河 有限公司 ', '星河股份有限公司', '星河（北京【总部】）集团', '星河集团有限公司']:
            with self.subTest(name=name):
                self.assertEqual(benchmark.normalize_company(name), '星河')
        self.assertEqual(benchmark.normalize_company('ＡＣＭＥ（上海）'), 'acme')
        self.assertEqual(benchmark.normalize_company('星河有限公司研究院'), '星河有限公司研究院')

    def test_ten_answers_eight_jobs_find_seven_with_company_breakdown(self):
        jobs = [job('ＡＩ 产品经理（北京）', '星河（北京）股份有限公司'), job('AI产品经理'),
                job('数据产品经理'), job('算法工程师'), job('后端工程师', '远山'),
                job('前端工程师', '远山'), job('运营', '海风'), job('售前', '海风')]
        result = benchmark.match_truth(self.truth, jobs)
        self.assertEqual(result['direction_id'], self.truth['direction_id'])
        self.assertEqual(result['collected_at'], COLLECTED)
        self.assertEqual(result['overall'], dict(truth=10, found=7, recall=0.7, jobs=8, extra=0,
            duplicates=1, duplicate_rate=0.125, closed=0, closed_rate=0.0, other_companies=0))
        self.assertEqual(result['companies'], [
            dict(name='星河', truth=4, found=3, recall=0.75, extra=0, duplicates=1, missing=['设计师']),
            dict(name='远山', truth=3, found=2, recall=0.667, extra=0, duplicates=0, missing=['测试工程师']),
            dict(name='海风', truth=3, found=2, recall=0.667, extra=0, duplicates=0, missing=['数据分析师'])])

    def test_url_matches_a_different_title_and_normalizes_host_slash_fragment(self):
        result = benchmark.match_truth(self.truth, [job('已改名的岗位', url='HTTPS://CAREERS.EXAMPLE/0/0/#detail')])
        self.assertEqual(result['overall']['found'], 1)
        self.assertNotIn('AI 产品经理', result['companies'][0]['missing'])

    def test_url_query_and_scheme_are_preserved(self):
        self.truth['companies'][0]['jobs'][0]['url'] += '?id=1&source=A'
        jobs = [job('未知岗位甲', url='https://careers.example/0/0?id=2&source=A'),
                job('未知岗位乙', url='http://careers.example/0/0?id=1&source=A'),
                job('未知岗位丙', url='https://careers.example/0/0/?id=1&source=A#detail')]
        result = benchmark.match_truth(self.truth, jobs)
        self.assertEqual((result['overall']['found'], result['overall']['extra']), (1, 2))

    def test_url_takes_precedence_over_title_even_after_the_url_was_matched(self):
        jobs = [job('数据产品经理', url='https://careers.example/0/0'),
                job('数据产品经理', url='https://careers.example/0/0/')]
        result = benchmark.match_truth(self.truth, jobs)
        self.assertEqual((result['overall']['found'], result['overall']['duplicates']), (1, 1))
        self.assertIn('数据产品经理', result['companies'][0]['missing'])
        self.assertNotIn('AI 产品经理', result['companies'][0]['missing'])

    def test_url_lookup_spans_truth_companies_after_company_membership_check(self):
        result = benchmark.match_truth(self.truth, [job('跨站标题', url='https://careers.example/1/0')])
        self.assertEqual(result['companies'][0]['found'], 0)
        self.assertEqual(result['companies'][1]['found'], 1)

    def test_same_title_answers_can_each_be_found_once(self):
        self.truth['companies'][0]['jobs'][1]['title'] = 'AI 产品经理'
        result = benchmark.match_truth(self.truth, [job('AI产品经理') for _ in range(3)])
        self.assertEqual((result['overall']['found'], result['overall']['duplicates']), (2, 1))

    def test_unmatched_jobs_deduplicate_by_title_or_url_within_company(self):
        jobs = [job('额外岗位', url='https://careers.example/extra'),
                job('额外-岗位（上海）', url='https://careers.example/other'),
                job('另一标题', url='HTTPS://CAREERS.EXAMPLE/extra/#x'),
                job('额外岗位', '远山', url='https://careers.example/extra')]
        result = benchmark.match_truth(self.truth, jobs)
        self.assertEqual((result['overall']['extra'], result['overall']['duplicates']), (2, 2))
        self.assertEqual(result['companies'][0]['duplicates'], 2)
        self.assertEqual(result['companies'][1]['extra'], 1)

    def test_matched_job_is_not_an_unmatched_extra_for_deduplication(self):
        jobs = [job('新标题', url='https://careers.example/0/0'), job('新标题')]
        result = benchmark.match_truth(self.truth, jobs)
        self.assertEqual((result['overall']['found'], result['overall']['extra'], result['overall']['duplicates']), (1, 1, 0))

    def test_other_companies_do_not_affect_counts_even_with_matching_url(self):
        jobs = [job('其他岗位', '其他公司', url='https://careers.example/0/0', availability='closed'),
                job('AI 产品经理', None), job('AI 产品经理')]
        result = benchmark.match_truth(self.truth, jobs)['overall']
        self.assertEqual((result['jobs'], result['found'], result['recall'], result['extra'], result['other_companies']), (1, 1, 0.1, 0, 2))
        self.assertEqual(result['closed'], 0)

    def test_closed_includes_duplicates_and_extras(self):
        jobs = [job('AI产品经理', availability='closed'), job('AI产品经理', availability='closed'),
                job('多出岗位', availability='closed'), job('数据产品经理')]
        result = benchmark.match_truth(self.truth, jobs)['overall']
        self.assertEqual((result['closed'], result['closed_rate'], result['jobs']), (3, 0.75, 4))

    def test_empty_jobs_and_empty_truth_use_their_own_denominators(self):
        result = benchmark.match_truth(self.truth, [])
        self.assertEqual(result['overall']['recall'], 0.0)
        self.assertIsNone(result['overall']['duplicate_rate'])
        self.assertIsNone(result['overall']['closed_rate'])
        self.assertEqual(result['companies'][0]['missing'], [j['title'] for j in self.truth['companies'][0]['jobs']])
        for company in self.truth['companies']:
            company['jobs'] = []
        result = benchmark.match_truth(self.truth, [])
        self.assertTrue(all(result['overall'][key] is None for key in ('recall', 'duplicate_rate', 'closed_rate')))
        self.assertTrue(all(row['recall'] is None for row in result['companies']))
        self.truth['companies'] = []
        result = benchmark.match_truth(self.truth, [job('任意岗位')])
        self.assertEqual(result['companies'], [])
        self.assertEqual(result['overall']['other_companies'], 1)

    def test_optional_urls_and_malformed_stored_url_can_fall_back_to_title(self):
        self.truth['companies'][0]['jobs'][0].pop('url')
        self.truth['companies'][0]['jobs'][1]['url'] = None
        result = benchmark.match_truth(self.truth, [job('AI产品经理', url='not-a-url'), job('数据产品经理', url=None)])
        self.assertEqual(result['overall']['found'], 2)

    def test_matching_does_not_mutate_inputs(self):
        jobs = [job('AI 产品经理')]
        before = copy.deepcopy((self.truth, jobs))
        benchmark.match_truth(self.truth, iter(jobs))
        self.assertEqual((self.truth, jobs), before)


class BenchmarkFileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.truth_path = self.root / 'truth.json'
        self.data = self.root / 'data'
        self.truth = truth_list()
        self.write_truth(self.truth)

    def write_truth(self, truth):
        self.truth_path.write_text(json.dumps(truth, ensure_ascii=False), encoding='utf-8')

    def run_jobs(self, jobs, **kwargs):
        with patch('hunt.benchmark.Store') as store:
            store.return_value.state.return_value = dict(jobs=jobs)
            result = benchmark.run(self.truth_path, self.data, **kwargs)
        store.assert_called_once_with(self.data.resolve())
        return result

    def test_load_truth_allows_absent_or_null_job_urls_and_empty_lists(self):
        self.truth['companies'][0]['jobs'][0].pop('url')
        self.truth['companies'][0]['jobs'][1]['url'] = None
        self.truth['companies'][1]['jobs'] = []
        self.write_truth(self.truth)
        self.assertEqual(benchmark.load_truth(self.truth_path), self.truth)
        self.truth['companies'] = []
        self.write_truth(self.truth)
        self.assertEqual(benchmark.load_truth(self.truth_path), self.truth)

    def test_bad_top_level_fields(self):
        for value in [None, [], 5, '对象']:
            with self.subTest(value=value):
                self.write_truth(value)
                with self.assertRaisesRegex(ValueError, '标准答案必须'):
                    benchmark.load_truth(self.truth_path)
        cases = [('direction_id', ['', ' ', None, 1, [], {}]),
                 ('collected_at', ['', None, 1, [], {}, '昨天', '2026-10-28', '2026-10-28T10:00:00', '2026-02-30T00:00:00Z']),
                 ('companies', [None, '', 1, {}])]
        for field, values in cases:
            for missing, value in [(True, None)] + [(False, v) for v in values]:
                with self.subTest(field=field, missing=missing, value=value):
                    truth = truth_list()
                    if missing: truth.pop(field)
                    else: truth[field] = value
                    self.write_truth(truth)
                    with self.assertRaisesRegex(ValueError, field):
                        benchmark.load_truth(self.truth_path)

    def test_bad_company_fields_include_company_number(self):
        for value in [None, [], 1, '公司']:
            with self.subTest(value=value):
                truth = truth_list()
                truth['companies'][1] = value
                self.write_truth(truth)
                with self.assertRaisesRegex(ValueError, '第 2 家公司'):
                    benchmark.load_truth(self.truth_path)
        cases = [('name', ['', ' \t', None, 2, [], {}]), ('jobs', [None, '', 1, {}]),
                 ('careers_url', [None, 3, '', 'ftp://careers.example', 'https://', '/careers', 'https://[bad'])]
        for field, values in cases:
            for missing, value in [(True, None)] + [(False, v) for v in values]:
                with self.subTest(field=field, missing=missing, value=value):
                    truth = truth_list()
                    if missing: truth['companies'][1].pop(field)
                    else: truth['companies'][1][field] = value
                    self.write_truth(truth)
                    with self.assertRaisesRegex(ValueError, '第 2 家公司.*' + field):
                        benchmark.load_truth(self.truth_path)

    def test_bad_job_fields_include_company_and_job_numbers(self):
        for value in [None, [], 1, '岗位']:
            with self.subTest(value=value):
                truth = truth_list()
                truth['companies'][1]['jobs'][1] = value
                self.write_truth(truth)
                with self.assertRaisesRegex(ValueError, '第 2 家公司第 2 条岗位'):
                    benchmark.load_truth(self.truth_path)
        cases = [('title', ['', ' \n', None, 1, [], {}]),
                 ('url', [True, 1, [], {}, '', 'ftp://careers.example', 'careers.example', '/job/1',
                          'https://', 'https:///one', 'https://[bad', 'https://host:bad', 'https://host:99999',
                          'https://bad host/1', 'https://host/\n1'])]
        for field, values in cases:
            for missing, value in ([(True, None)] if field == 'title' else []) + [(False, v) for v in values]:
                with self.subTest(field=field, missing=missing, value=value):
                    truth = truth_list()
                    if missing: truth['companies'][1]['jobs'][1].pop(field)
                    else: truth['companies'][1]['jobs'][1][field] = value
                    self.write_truth(truth)
                    with self.assertRaisesRegex(ValueError, '第 2 家公司第 2 条岗位.*' + field):
                        benchmark.load_truth(self.truth_path)

    def test_unreadable_or_malformed_truth_is_a_chinese_value_error(self):
        for content in [b'{bad json', b'\xff\xfe']:
            self.truth_path.write_bytes(content)
            with self.assertRaisesRegex(ValueError, '无法读取标准答案 JSON'):
                benchmark.load_truth(self.truth_path)
        with self.assertRaisesRegex(ValueError, '无法读取标准答案 JSON'):
            benchmark.load_truth(self.root / 'missing.json')
        with patch.object(Path, 'read_text', side_effect=PermissionError('拒绝读取')):
            with self.assertRaisesRegex(ValueError, '无法读取标准答案 JSON'):
                benchmark.load_truth(self.truth_path)

    def test_direction_filter_excludes_unassigned_and_other_directions(self):
        jobs = [job('AI产品经理', direction=dict(id='ai-product-manager', by='user')),
                job('数据产品经理', direction=dict(id='other')), job('算法工程师'),
                job('后端工程师', '远山', direction=dict(id=None)), job('运营', '海风', direction=None),
                job('售前', '海风', direction='invalid')]
        result = self.run_jobs(jobs, direction='ai-product-manager')
        self.assertEqual((result['overall']['jobs'], result['overall']['found']), (1, 1))
        self.assertEqual(result['filters'], dict(direction='ai-product-manager', since=None))
        self.assertEqual(self.run_jobs(jobs)['overall']['jobs'], 6)

    def test_since_compares_instants_and_includes_the_boundary(self):
        since = '2026-10-28T10:00:00+08:00'
        jobs = [job('AI产品经理', collected_at='2026-10-28T02:00:00Z'),
                job('数据产品经理', collected_at='2026-10-28T03:00:00+01:00'),
                job('算法工程师', collected_at='2026-10-28T09:59:59+08:00'),
                job('后端工程师', '远山', collected_at='2026-10-28T02:00:00.001+00:00')]
        result = self.run_jobs(jobs, since=since)
        self.assertEqual((result['overall']['jobs'], result['overall']['found']), (3, 3))
        self.assertEqual(result['filters']['since'], since)
        self.assertIn('算法工程师', result['companies'][0]['missing'])

    def test_bad_since_is_rejected_before_store_access(self):
        for since in ['', '昨天', '2026-10-28', '2026-10-28T10:00:00', 42]:
            with self.subTest(since=since), patch('hunt.benchmark.Store') as store:
                with self.assertRaisesRegex(ValueError, '--since.*带时区'):
                    benchmark.run(self.truth_path, self.data, since=since)
                store.assert_not_called()

    def test_bad_job_times_fail_only_when_needed_for_the_filter(self):
        for value in [None, '', '昨天', 42, '2026-10-28T10:00:00']:
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, '第 1 条岗位 collected_at.*带时区'):
                    self.run_jobs([job('AI产品经理', collected_at=value)], since=COLLECTED)
        self.assertEqual(self.run_jobs([job('AI产品经理', collected_at=None)])['overall']['found'], 1)
        result = self.run_jobs([job('AI产品经理', direction=dict(id='other'), collected_at=None)],
                               direction='ai-product-manager', since=COLLECTED)
        self.assertEqual(result['overall']['jobs'], 0)

    def test_default_report_uses_shanghai_date_and_records_provenance(self):
        fixed = datetime(2026, 10, 28, 0, 30, tzinfo=timezone(timedelta(hours=8)))
        with patch('hunt.benchmark.datetime', wraps=datetime) as clock:
            clock.now.return_value = fixed
            result = self.run_jobs([])
            clock.now.assert_called_once_with(benchmark.SHANGHAI)
        output = self.root / 'report-2026-10-28.json'
        self.assertEqual(json.loads(output.read_text()), result)
        self.assertEqual(result['generated_at'], '2026-10-28T00:30:00+08:00')
        self.assertEqual(result['truth_file'], str(self.truth_path.resolve()))
        self.assertEqual(result['data_dir'], str(self.data.resolve()))
        self.assertEqual(result['filters'], dict(direction=None, since=None))

    def test_output_parent_is_created_and_truth_cannot_be_overwritten(self):
        output = self.root / 'reports' / 'nested' / 'result.json'
        result = self.run_jobs([], output=output)
        self.assertEqual(json.loads(output.read_text()), result)
        before = self.truth_path.read_bytes()
        with patch('hunt.benchmark.Store') as store:
            with self.assertRaisesRegex(ValueError, '不能覆盖标准答案'):
                benchmark.run(self.truth_path, self.data, output=self.truth_path)
            store.assert_not_called()
        self.assertEqual(self.truth_path.read_bytes(), before)

    def test_write_failures_are_chinese_value_errors(self):
        for output in [self.root, self.truth_path / 'report.json']:
            with self.subTest(output=output):
                with self.assertRaisesRegex(ValueError, '无法写入基准报告'):
                    self.run_jobs([], output=output)

    def invoke(self, arguments):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(arguments)
        return code, out.getvalue(), err.getvalue()

    def test_cli_real_store_json_report_and_combined_filters(self):
        store = Store(self.data)
        for i, (title, company, status, direction, timestamp) in enumerate([
                ('AI产品经理', '星河', 'closed', 'ai-product-manager', COLLECTED),
                ('AI产品经理', '星河', 'open', 'ai-product-manager', COLLECTED),
                ('数据产品经理', '星河', 'open', 'ai-product-manager', COLLECTED),
                ('其他岗位', '其他公司', 'closed', 'ai-product-manager', COLLECTED),
                ('算法工程师', '星河', 'open', 'other', COLLECTED),
                ('设计师', '星河', 'open', 'ai-product-manager', '2026-10-27T00:00:00Z')]):
            imported, _ = store.import_job(dict(title=title, company=company, jd='合成岗位描述 %d' % i,
                url='https://collected.example/jobs/%d' % i, status=status, collected_at=timestamp))
            with store.tx() as c:
                store.save(c, dict(imported, direction=dict(id=direction, by='user')))
        before = store.state()['jobs']
        output = self.root / 'reports' / 'cli.json'
        with patch('hunt.network.fetch', side_effect=AssertionError('禁止联网')), \
                patch('hunt.llm.chat_json', side_effect=AssertionError('禁止模型调用')):
            code, out, err = self.invoke(['benchmark', '--truth', str(self.truth_path), '--data', str(self.data),
                '--direction', 'ai-product-manager', '--since', COLLECTED, '--output', str(output), '--json'])
        self.assertEqual((code, err), (0, ''))
        result = json.loads(out)
        self.assertEqual(json.loads(output.read_text()), result)
        self.assertEqual((result['overall']['jobs'], result['overall']['found'], result['overall']['duplicates']), (3, 2, 1))
        self.assertEqual((result['overall']['closed'], result['overall']['closed_rate'], result['overall']['other_companies']), (1, 0.333, 1))
        self.assertEqual(store.state()['jobs'], before)

    def test_cli_chinese_summary_includes_each_company_and_empty_ratios(self):
        Store(self.data).import_job(dict(title='AI 产品经理', company='星河', jd='合成描述'))
        code, out, err = self.invoke(['benchmark', '--truth', str(self.truth_path), '--data', str(self.data)])
        self.assertEqual((code, err), (0, ''))
        self.assertIn('召回 1/10（10.0%）· 多出 0 · 重复 0（0.0%）· 已下线 0', out)
        self.assertEqual([line.split('：')[0] for line in out.splitlines()[1:]], ['星河', '远山', '海风'])
        self.truth['companies'] = []
        self.write_truth(self.truth)
        code, out, err = self.invoke(['benchmark', '--truth', str(self.truth_path), '--data', str(self.data)])
        self.assertEqual((code, err), (0, ''))
        self.assertIn('召回 0/0（不适用）', out)
        self.assertIn('重复 0（不适用）', out)

    def test_cli_errors_return_one_without_tracebacks(self):
        for arguments, expected in [(['--truth', str(self.root / 'missing.json')], '无法读取标准答案'),
                (['--truth', str(self.truth_path), '--since', '昨天'], '--since'),
                (['--truth', str(self.truth_path), '--output', str(self.root)], '无法写入基准报告')]:
            for as_json in [False, True]:
                with self.subTest(arguments=arguments, as_json=as_json):
                    code, out, err = self.invoke(['benchmark', '--data', str(self.data)] + arguments + (['--json'] if as_json else []))
                    self.assertEqual(code, 1)
                    self.assertNotIn('Traceback', out + err)
                    if as_json:
                        self.assertIn(expected, json.loads(out)['error'])
                        self.assertEqual(err, '')
                    else:
                        self.assertEqual(out, '')
                        self.assertIn('错误：', err)
                        self.assertIn(expected, err)

    def test_cli_defaults_to_existing_data_path(self):
        args = parser().parse_args(['benchmark', '--truth', str(self.truth_path)])
        self.assertEqual(args.data, DEFAULT_DATA)


if __name__ == '__main__':
    unittest.main()
