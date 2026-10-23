import copy
import json
import tempfile
import unittest
from pathlib import Path

from hunt.materials import accepted_facts, match, prepare, synthetic_candidate
from hunt.export import write_package


class MaterialTests(unittest.TestCase):
    def setUp(self):
        self.candidate = synthetic_candidate()
        self.job = {'title': '数据工具开发', 'requirements': ['熟练使用 Python、SQL，主导生产环境系统建设，3 年经验'],
                    'location': '深圳', 'min_years': 3}

    def test_keyword_is_not_full_requirement_support(self):
        result = match(self.candidate, self.job, {'cities': ['上海']})
        self.assertEqual(result['requirements'][0]['status'], 'needs_confirmation')
        self.assertIn('demo-python', result['requirements'][0]['fact_ids'])
        self.assertEqual([r['status'] for r in result['hard'][:2]], ['not_met', 'not_met'])
        self.assertFalse(result['summary']['eligible'])

    def test_only_full_exact_requirement_supported(self):
        fact = self.candidate['facts'][2]
        self.assertEqual(match(self.candidate, {'requirements': [fact['text']]})['requirements'][0]['status'], 'supported')
        self.assertEqual(match(self.candidate, {'requirements': ['熟练使用 Kafka']})['requirements'][0]['status'], 'missing_evidence')

    def test_private_unconfirmed_and_unreferenced_never_exported(self):
        for change in [{'disclosure': 'private'}, {'status': 'pending'}, {'source': {}}, {'version': None}]:
            candidate = copy.deepcopy(self.candidate)
            candidate['facts'][2].update(change)
            package = prepare(candidate, self.job)
            self.assertNotIn(candidate['facts'][2]['text'], package['resume'])
            self.assertNotIn('demo-python', package['source_map'])

    def test_duplicate_fact_id_is_not_accepted(self):
        self.candidate['facts'].append(copy.deepcopy(self.candidate['facts'][2]))
        self.assertNotIn('demo-python', [f['id'] for f in accepted_facts(self.candidate)])

    def test_numeric_and_contribution_claims_exactly_conserved(self):
        original = '参与消息削峰练习；准确率 100%，样本 120 条；未使用 Kafka，未上线。'
        self.candidate['facts'].append(dict(id='numbers', text=original, source={'reference': 'synthetic://numbers'}, status='confirmed', version=1, disclosure='application', tags=['消息']))
        package = prepare(self.candidate, self.job)
        by_id = {f['id']: f for f in accepted_facts(self.candidate)}
        for claim in package['claims']:
            self.assertEqual(claim['text'], by_id[claim['fact_ids'][0]]['text'])
        self.assertIn(original, package['resume'])
        self.assertNotIn('99%+', package['resume'])
        self.assertNotIn('主导消息', package['resume'])
        self.assertEqual(package['candidate_version'], 1)
        self.assertTrue(package['synthetic'])

    def test_field_id_cannot_prove_an_invented_value(self):
        self.candidate['fields']['name']['value'] = '伪造的姓名'
        self.candidate['fields']['salary'] = {'value': 999999, 'fact_ids': ['demo-years']}
        package = prepare(self.candidate, {**self.job, 'questions': [{'text': '期望薪资？', 'field': 'salary'}]})
        self.assertNotIn('伪造的姓名', package['resume'])
        self.assertNotIn('name', package['fields'])
        self.assertEqual(package['answers'][0]['answer'], '')
        self.assertEqual(package['answers'][0]['status'], 'needs_confirmation')

    def test_known_field_answer_and_year_evidence_preserved(self):
        package = prepare(self.candidate, {'questions': [{'text': '邮箱', 'field': 'email'}]})
        self.assertEqual(package['answers'][0]['answer'], 'candidate@example.invalid')
        self.assertIn('demo-years', package['source_map'])

    def test_unknowns_are_not_silently_eligible(self):
        result = match({'facts': [], 'fields': {}}, {'requirements': ['Python'], 'experience': '3年以上'})
        self.assertIsNone(result['summary']['eligible'])
        self.assertTrue(any(r['text'] == '相关经验年限' and r['status'] == 'missing_evidence' for r in result['hard']))
        self.assertTrue(any(r['text'] == '岗位薪资' for r in result['hard']))

    def test_experience_range_lower_bound(self):
        result = match(self.candidate, {'experience': '1-3年'})
        self.assertEqual(next(r for r in result['hard'] if r['text'] == '相关经验年限')['status'], 'supported')
        below = match(self.candidate, {'experience': '3年以下'})
        self.assertFalse(any(r['text'] == '相关经验年限' for r in below['hard']))

    def test_explicit_jd_experience_shortfall_is_hard_failure(self):
        result = match(self.candidate, {'requirements': ['至少 3 年相关开发经验，熟练使用 Python']})
        self.assertEqual(result['requirements'][0]['status'], 'needs_confirmation')
        self.assertEqual(next(r for r in result['hard'] if r['text'] == '相关经验年限')['status'], 'not_met')

    def test_parenthetical_sector_choices_do_not_waive_year_minimum(self):
        text = '8 年以上财务工作经验，其中 3 年以上零售 / 连锁 / 快消行业财务经验（门店财务、区域财务或零售运营财务为佳）'
        result = match(self.candidate, {'requirements_text': text})
        row = next(r for r in result['hard'] if r['text'] == '相关经验年限')
        self.assertEqual(row['status'], 'not_met')
        self.assertIn('最低 8.0 年', row['reason'])
        alternative = match(self.candidate, {'requirements_text': '至少3年开发经验或优秀应届生。'})
        self.assertFalse(any(r['text'] == '相关经验年限' for r in alternative['hard']))

    def test_structural_headings_are_not_requirements(self):
        job = {'requirements_text': '任职要求\n必备条件\n熟悉 Kubernetes。\n加分项\n经验：\n拥有公开作品。'}
        self.assertEqual([r['text'] for r in match(self.candidate, job)['requirements']], ['熟悉 Kubernetes。', '拥有公开作品。'])
        self.assertIn('加分项', job['requirements_text'])

    def test_salary_hard_limit_and_unknown_location(self):
        for salary, expected in [(9000, 'not_met'), (12000, 'supported'), ({'min': 9000, 'max': 12000}, 'needs_confirmation'), ('面议', 'needs_confirmation')]:
            result = match(self.candidate, {'salary': salary, 'location': '地点未知'}, {'salary_min': 10000, 'cities': ['深圳']})
            self.assertEqual(next(r for r in result['hard'] if r['text'] == '岗位薪资')['status'], expected)
            self.assertEqual(next(r for r in result['hard'] if r['text'] == '工作地点')['status'], 'needs_confirmation')

    def test_generated_sources_cannot_reenter_fact_base(self):
        self.candidate['facts'][2]['source']['kind'] = 'generated'
        self.assertNotIn('demo-python', [f['id'] for f in accepted_facts(self.candidate)])

    def test_blockers_distinct_from_qualification_unknowns(self):
        package = prepare(self.candidate, self.job)
        self.assertGreater(len(package['gaps']), 0)
        self.assertEqual(package['blockers'], [])
        job = {**self.job, 'questions': [{'text': '入职时间', 'field': 'start_date', 'required': True}, {'text': '补充说明', 'required': False}]}
        package = prepare(self.candidate, job)
        self.assertEqual([r['text'] for r in package['blockers']], ['入职时间'])
        self.candidate['fields']['email']['value'] = ''
        self.assertIn('联系邮箱', [r['text'] for r in prepare(self.candidate, self.job)['blockers']])

    def test_explicit_exclusion_keyword(self):
        result = match(self.candidate, {'title': '博彩平台工具开发'}, {'exclude_keywords': ['博彩']})
        self.assertTrue(any(r['text'] == '排除关键词：博彩' and r['status'] == 'not_met' for r in result['hard']))

    def test_pdf_chinese_extraction_and_multiple_pages(self):
        from pypdf import PdfReader
        for index in range(65):
            self.candidate['facts'].append(dict(id='page-%d' % index, text='合成分页经历 %02d：参与本地工具实现，分析 120 条合成记录；未上线。' % index, source={'reference': 'synthetic://pages/%d' % index}, status='confirmed', version=1, disclosure='application', tags=[]))
        package = prepare(self.candidate, self.job)
        with tempfile.TemporaryDirectory() as directory:
            files = write_package(package, directory)
            reader = PdfReader(str(Path(directory) / files['pdf']))
            self.assertGreater(len(reader.pages), 1)
            extracted = '\n'.join(page.extract_text() for page in reader.pages)
            self.assertIn('林示例', extracted)
            self.assertIn('合成候选人', extracted)
            self.assertIn('120', extracted)
            self.assertLess(extracted.index('经历与能力'), extracted.index('合成分页经历 00'))
            self.assertLess(extracted.index('合成分页经历 00'), extracted.index('合成分页经历 64'))
            self.assertEqual((Path(directory) / files['text']).read_text(), package['resume'])
            sources = json.loads((Path(directory) / files['source_map']).read_text())
            self.assertEqual(sources['page-64']['text'], self.candidate['facts'][-1]['text'])
            self.assertEqual((Path(directory) / files['pdf']).stat().st_mode & 0o777, 0o600)
            embedded = []
            for page in reader.pages:
                for font in page['/Resources']['/Font'].values():
                    descriptor = font.get_object().get('/FontDescriptor')
                    if descriptor:
                        embedded.append(bool(descriptor.get_object().get('/FontFile2')))
            self.assertIn(True, embedded)


if __name__ == '__main__':
    unittest.main()
