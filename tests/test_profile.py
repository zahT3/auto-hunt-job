import unittest
from hunt.intake import analyze_resume
from hunt.profile import build_profile, confirm_candidate
from hunt.materials import accepted_facts


class ProfileTests(unittest.TestCase):
    def profile(self, text):
        return analyze_resume('test.txt', text.encode(), synthetic=True)

    def test_all_derived_hints_have_source_and_queries_are_generic(self):
        result = self.profile('姓名：林示例\n邮箱：private@example.invalid\n工作经验：3年\n学历：本科\nPython RAG Agent Solidity 测试网原型，未上线')
        profile = result['profile']
        ids = {f['id'] for f in result['candidate']['facts']}
        for item in profile['skills'] + profile['directions'] + profile['education'] + profile['experience'] + profile['query_evidence']:
            self.assertTrue(item['fact_ids'])
            self.assertTrue(set(item['fact_ids']) <= ids)
        self.assertEqual(profile['years_experience']['value'], 3)
        self.assertIn('Agent 开发', profile['suggested_queries'])
        self.assertIn('Web3 开发', profile['suggested_queries'])
        self.assertNotIn('private', ' '.join(profile['suggested_queries']))
        self.assertFalse(profile['external_search_authorized'])
        self.assertFalse(accepted_facts(result['candidate']))

    def test_no_years_inferred_from_age_dates_internship_or_projects(self):
        result = self.profile('年龄30岁\n2018年本科毕业\n2020至2024实习\nPython 项目经验5年')
        self.assertIsNone(result['profile']['years_experience'])
        self.assertNotIn('years_experience', result['candidate']['fields'])

    def test_conflicting_explicit_years_left_unknown(self):
        result = self.profile('工作经验：3年\n工作经验：5年')
        self.assertIsNone(result['profile']['years_experience'])
        self.assertTrue(result['warnings'])

    def test_negated_skill_does_not_become_search_hint(self):
        result = self.profile('没有 Solidity 经验。不会 Python。无 Agent 经验。熟悉 SQL。')
        self.assertEqual([s['name'] for s in result['profile']['skills']], ['SQL'])

    def test_confirmation_is_separate_from_application_disclosure(self):
        candidate = self.profile('工作经验：3年\nPython 原型')['candidate']
        selected = [f['id'] for f in candidate['facts']]
        confirmed = confirm_candidate(candidate, selected)
        self.assertTrue(all(f['status'] == 'confirmed' for f in confirmed['facts']))
        self.assertFalse(accepted_facts(confirmed))
        self.assertTrue(all(f['status'] == 'unconfirmed' for f in candidate['facts']))
        disclosed = confirm_candidate(candidate, selected, application_fact_ids=selected[:1])
        self.assertEqual(len(accepted_facts(disclosed)), 1)
        with self.assertRaises(ValueError):
            confirm_candidate(candidate, ['missing'])
        with self.assertRaises(ValueError):
            confirm_candidate(candidate, selected[:1], application_fact_ids=selected[1:])


    def test_recommend_uses_confirmed_local_facts_without_disclosure(self):
        from hunt.profile import recommend
        candidate = self.profile('工作经验：3年\n使用Python和RAG制作原型')['candidate']
        job = {'title': 'AI 应用开发', 'description': 'Python RAG Docker'}
        self.assertEqual(recommend(candidate, job)['priority'], 0)
        confirmed = confirm_candidate(candidate, [f['id'] for f in candidate['facts']])
        result = recommend(confirmed, job)
        self.assertEqual([s['name'] for s in result['skill_matches']], ['Python', 'RAG'])
        self.assertEqual(result['missing_skills'], ['Docker'])
        self.assertGreater(result['priority'], 0)
        self.assertFalse(accepted_facts(confirmed))

    def test_rejected_fact_does_not_influence_profile(self):
        candidate = self.profile('Python Solidity')['candidate']
        candidate['facts'][0]['status'] = 'rejected'
        self.assertFalse(build_profile(candidate)['skills'])


    def test_confirmed_only_hides_unselected_experience_fields_and_queries(self):
        candidate = self.profile('工作经验：3年\nSolidity Web3\nPython 原型')['candidate']
        python_id = candidate['facts'][2]['id']
        confirmed = confirm_candidate(candidate, [python_id])
        preview = build_profile(confirmed)
        active = build_profile(confirmed, confirmed_only=True)
        self.assertEqual(preview['years_experience']['value'], 3)
        self.assertIn('Web3 开发', preview['suggested_queries'])
        self.assertIsNone(active['years_experience'])
        self.assertFalse(active['experience'])
        self.assertNotIn('Web3 开发', active['suggested_queries'])
        self.assertEqual([s['name'] for s in active['skills']], ['Python'])
        self.assertEqual(active['skills'][0]['status'], 'confirmed')
        self.assertTrue(active['unknowns'])

    def test_field_requires_every_reference_and_actual_supported_value(self):
        candidate = self.profile('工作经验：3年\nPython')['candidate']
        years_id, python_id = [f['id'] for f in candidate['facts']]
        confirmed = confirm_candidate(candidate, [years_id])
        confirmed['fields']['years_experience']['fact_ids'].append(python_id)
        self.assertIsNone(build_profile(confirmed, confirmed_only=True)['years_experience'])
        confirmed['fields']['years_experience'] = {'value': 50, 'fact_ids': [years_id]}
        self.assertIsNone(build_profile(confirmed, confirmed_only=True)['years_experience'])
        confirmed['fields']['years_experience'] = {'value': 3, 'fact_ids': [years_id]}
        self.assertEqual(build_profile(confirmed, confirmed_only=True)['years_experience']['value'], 3)
        self.assertTrue(all(f['disclosure'] == 'private' for f in confirmed['facts']))

    def test_malformed_or_duplicate_facts_do_not_create_recommendations(self):
        import copy
        from hunt.profile import recommend
        candidate = self.profile('Python')['candidate']
        candidate = confirm_candidate(candidate, [candidate['facts'][0]['id']])
        mutations = [
            lambda f: f.update(source=None),
            lambda f: f.update(source={'reference': '   '}),
            lambda f: f.update(source={'reference': 'generated://draft', 'kind': 'generated'}),
            lambda f: f.update(status=['confirmed']),
            lambda f: f.update(text={'text': 'Python'}),
            lambda f: f.update(id=['id']),
            lambda f: f.update(version=True),
        ]
        for mutate in mutations:
            malformed = copy.deepcopy(candidate)
            mutate(malformed['facts'][0])
            malformed['facts'].extend([None, 'Python', 123])
            with self.subTest(mutate=mutate):
                self.assertFalse(build_profile(malformed, confirmed_only=True)['skills'])
                self.assertEqual(recommend(malformed, {'title': 'Python'})['priority'], 0)
        duplicate = copy.deepcopy(candidate)
        duplicate['facts'].append(copy.deepcopy(duplicate['facts'][0]))
        self.assertFalse(build_profile(duplicate, confirmed_only=True)['skills'])
        self.assertEqual(recommend(duplicate, {'title': 'Python'})['priority'], 0)

    def test_skill_tags_are_allowlisted_source_mentions_not_field_values(self):
        candidate = self.profile('使用Python和RAG制作原型\n没有 Solidity 经验')['candidate']
        self.assertEqual(candidate['facts'][0]['tags'], ['python', 'rag'])
        self.assertEqual(candidate['facts'][1]['tags'], [])
        candidate['fields']['untrusted_skill'] = {'value': 'Solidity', 'fact_ids': [candidate['facts'][0]['id']]}
        self.assertNotIn('Solidity', [s['name'] for s in build_profile(candidate)['skills']])
        self.assertNotIn('untrusted_skill', build_profile(candidate)['fields'])


if __name__ == '__main__':
    unittest.main()
