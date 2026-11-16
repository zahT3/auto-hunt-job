"""Résumé structure: rule pre-fill against hand-labelled fixtures, validation, stale marking, migration and the Store actions."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from hunt.base import Error
from hunt.app.store import Store
from hunt.profile import structure as S

FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'structure'
EXAMPLES = Path(__file__).resolve().parent.parent / 'examples'


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding='utf-8'))


class Case(unittest.TestCase):
    def setUp(self):
        self.facts = load('facts.json')
        self.text = {f['id']: f['text'] for f in self.facts}

    def piece(self, entry, name):
        span = entry['fields'][name]['span']
        return self.text[entry['head']['id']][span[0]:span[1]] if span else None


class BuildTests(Case):
    def test_prefill_matches_hand_labelled_sections_entries_and_fields(self):
        expected = load('expected.json')
        built = S.build(self.facts)
        self.assertEqual(built['status'], 'prefilled')
        self.assertIsNone(built['confirmed_at'])
        self.assertEqual([self.text[u['id']] for u in built['unassigned']], expected['unassigned'])
        self.assertEqual([(s['key'], self.text[s['title_fact']['id']]) for s in built['sections']],
                         [(s['key'], s['title']) for s in expected['sections']])
        for section, want_section in zip(built['sections'], expected['sections']):
            self.assertEqual(len(section['entries']), len(want_section['entries']), section['key'])
            for entry, want in zip(section['entries'], want_section['entries']):
                self.assertEqual(self.text[entry['head']['id']] if entry['head'] else None, want['head'])
                self.assertEqual([self.text[b['id']] for b in entry['bullets']], want['bullets'])
                if section['key'] not in S.ENTRY_KEYS:
                    self.assertEqual(entry['fields'], {})
                    continue
                for name in S.FIELDS:
                    self.assertEqual(self.piece(entry, name), want[name], (want['head'], name))
                uncertain = [n for n, f in entry['fields'].items() if f['confidence'] == 'uncertain']
                self.assertEqual(uncertain, want['uncertain'], want['head'])

    def test_every_confirmed_fact_is_placed_exactly_once(self):
        built = S.build(self.facts)
        held = [item['id'] for _, item in S._refs(built)]
        self.assertEqual(sorted(held), sorted(f['id'] for f in self.facts))

    def test_unconfirmed_facts_are_left_out(self):
        facts = copy.deepcopy(self.facts)
        facts[5]['status'] = 'unconfirmed'
        held = {item['id'] for _, item in S._refs(S.build(facts))}
        self.assertNotIn(facts[5]['id'], held)

    def test_section_without_dated_line_is_one_entry_with_every_field_uncertain(self):
        facts = [dict(id='a', text='工作经历', status='confirmed', version=1), dict(id='b', text='负责接口开发', status='confirmed', version=1),
                 dict(id='c', text='示例科技有限公司 后端工程师', status='confirmed', version=1)]
        built = S.build(facts)
        (entry,) = built['sections'][0]['entries']
        self.assertEqual(entry['head']['id'], 'b')
        self.assertEqual([b['id'] for b in entry['bullets']], ['c'])
        self.assertTrue(all(f['confidence'] == 'uncertain' for f in entry['fields'].values()))
        self.assertEqual(S.open_items(built)['uncertain'], 4)

    def test_heading_prefix_line_is_title_and_head_and_a_plain_label_line_is_not_a_heading(self):
        facts = [dict(id='a', text='工作经历：2021.07—2024.06，示例科技，软件开发工程师。', status='confirmed', version=1),
                 dict(id='b', text='项目：知识检索系统', status='confirmed', version=1),
                 dict(id='c', text='工作经验：3年', status='confirmed', version=1)]
        built = S.build(facts)
        (section,) = built['sections']
        self.assertEqual(section['title_fact']['id'], 'a')
        self.assertEqual(section['entries'][0]['head']['id'], 'a')
        self.assertEqual([b['id'] for b in section['entries'][0]['bullets']], ['b', 'c'])
        self.assertEqual(self.piece_of(facts[0], section['entries'][0], 'end'), '2024.06')
        S.validate(built, facts)

    def piece_of(self, fact, entry, name):
        a, b = entry['fields'][name]['span']
        return fact['text'][a:b]

    def test_ongoing_range_and_two_ranges(self):
        one = S.build([dict(id='a', text='工作经历', status='confirmed', version=1), dict(id='b', text='2021年7月至今 示例科技 工程师', status='confirmed', version=1)])
        entry = one['sections'][0]['entries'][0]
        self.assertEqual(entry['fields']['end']['span'], [7, 9])
        two = S.build([dict(id='a', text='工作经历', status='confirmed', version=1), dict(id='b', text='2018.01-2019.01 / 2020.01-2021.01 示例科技 工程师', status='confirmed', version=1)])
        self.assertEqual(two['sections'][0]['entries'][0]['fields']['start']['confidence'], 'uncertain')

    def test_fragments_offer_original_pieces_only(self):
        text = '2021年7月至今 示例科技有限公司 后端开发工程师'
        for item in S.fragments(text):
            a, b = item['span']
            self.assertEqual(text[a:b], item['text'])
        pieces = {item['text'] for item in S.fragments(text)}
        self.assertTrue({'2021年7月', '至今', '示例科技有限公司', '后端开发工程师'} <= pieces)

    def test_the_synthetic_example_resume_prefills_and_validates(self):
        from hunt.profile.intake import analyze_resume
        facts = analyze_resume('resume.synthetic.txt', (EXAMPLES / 'resume.synthetic.txt').read_bytes(), synthetic=True)['candidate']['facts']
        for f in facts: f['status'] = 'confirmed'
        built = S.build(facts)
        S.validate(built, facts)
        self.assertEqual([s['key'] for s in built['sections']], ['education', 'work', 'internship'])
        by_id = {f['id']: f['text'] for f in facts}
        work = built['sections'][1]['entries'][0]
        a, b = work['fields']['company']['span']
        self.assertEqual(by_id[work['head']['id']][a:b], '示例科技')
        education = built['sections'][0]['entries'][0]
        self.assertTrue(all(f['confidence'] == 'uncertain' for f in education['fields'].values()))


class ValidateTests(Case):
    def setUp(self):
        super().setUp()
        self.good = load('structure.json')

    def broken(self, change):
        value = copy.deepcopy(self.good)
        change(value)
        with self.assertRaises(S.StructureError):
            S.validate(value, self.facts)

    def test_fixture_structure_is_valid_and_normalized(self):
        self.assertEqual(S.validate(self.good, self.facts), self.good)
        self.assertEqual(S.open_items(self.good), dict(uncertain=0, stale=0, unassigned=2))

    def test_duplicate_reference_is_rejected(self):
        self.broken(lambda v: v['unassigned'].append(copy.deepcopy(v['sections'][1]['entries'][0]['bullets'][0])))
        self.broken(lambda v: v['sections'][1]['entries'][0]['bullets'].append(copy.deepcopy(v['sections'][1]['entries'][0]['bullets'][0])))
        self.broken(lambda v: v['sections'][1]['entries'][0]['bullets'].append(copy.deepcopy(v['sections'][1]['title_fact'])))

    def test_missing_or_unconfirmed_fact_is_rejected(self):
        self.broken(lambda v: v['unassigned'].append({'id': 'intake-nope', 'version': 1}))
        facts = copy.deepcopy(self.facts)
        facts[0]['status'] = 'unconfirmed'
        with self.assertRaises(S.StructureError):
            S.validate(self.good, facts)

    def test_wrong_version_is_rejected_unless_the_entry_is_stale(self):
        facts = copy.deepcopy(self.facts)
        bullet = self.good['sections'][1]['entries'][0]['bullets'][0]['id']
        next(f for f in facts if f['id'] == bullet)['version'] = 2
        with self.assertRaises(S.StructureError):
            S.validate(self.good, facts)
        stale = S.mark_stale(self.good, facts)
        S.validate(stale, facts)

    def test_span_outside_the_head_text_or_overlapping_is_rejected(self):
        entry = lambda v: v['sections'][1]['entries'][0]
        self.broken(lambda v: entry(v)['fields']['company'].update(span=[0, 400]))
        self.broken(lambda v: entry(v)['fields']['company'].update(span=[5, 5]))
        self.broken(lambda v: entry(v)['fields']['company'].update(span=[-1, 3]))
        self.broken(lambda v: entry(v)['fields']['title'].update(span=copy.copy(entry(v)['fields']['company']['span'])))
        self.broken(lambda v: entry(v)['fields']['company'].update(span=[0.5, 3]))

    def test_other_malformed_shapes_are_rejected(self):
        self.broken(lambda v: v['sections'][0].update(key='hobby'))
        self.broken(lambda v: v['sections'][1]['entries'][0].update(status='done'))
        self.broken(lambda v: v.update(status='saved'))
        self.broken(lambda v: v['sections'][1]['entries'][0]['fields']['company'].update(confidence='sure'))
        self.broken(lambda v: v['sections'][1]['entries'][0]['fields'].pop('end'))
        self.broken(lambda v: v['sections'][3]['entries'][0].update(fields={'company': {'span': None, 'confidence': 'ok'}}))
        self.broken(lambda v: v['sections'][1].update(id=v['sections'][0]['id']))
        with self.assertRaises(S.StructureError):
            S.validate('x', self.facts)

    def test_unknown_keys_are_dropped(self):
        value = copy.deepcopy(self.good)
        value['sections'][0]['entries'][0]['note'] = '自己写的文字'
        self.assertNotIn('note', S.validate(value, self.facts)['sections'][0]['entries'][0])


class StaleTests(Case):
    def setUp(self):
        super().setUp()
        self.good = load('structure.json')
        self.work = self.good['sections'][1]['entries']

    def test_unchanged_facts_change_nothing(self):
        self.assertEqual(S.mark_stale(self.good, self.facts), self.good)

    def test_changed_bullet_version_marks_the_entry_stale_and_fields_uncertain(self):
        facts = copy.deepcopy(self.facts)
        next(f for f in facts if f['id'] == self.work[0]['bullets'][0]['id'])['version'] = 2
        result = S.mark_stale(self.good, facts)
        entry = result['sections'][1]['entries'][0]
        self.assertEqual(entry['status'], 'stale')
        self.assertTrue(all(f['confidence'] == 'uncertain' for f in entry['fields'].values()))
        self.assertTrue(all(f['span'] for f in entry['fields'].values()))  # the head is unchanged, so its spans stay
        self.assertEqual(result['sections'][1]['entries'][1]['status'], 'ok')
        self.assertEqual(S.open_items(result)['stale'], 1)

    def test_changed_head_version_drops_spans(self):
        facts = copy.deepcopy(self.facts)
        next(f for f in facts if f['id'] == self.work[1]['head']['id'])['version'] = 2
        entry = S.mark_stale(self.good, facts)['sections'][1]['entries'][1]
        self.assertEqual(entry['status'], 'stale')
        self.assertTrue(all(f['span'] is None and f['confidence'] == 'uncertain' for f in entry['fields'].values()))

    def test_unconfirmed_or_deleted_fact_is_removed_and_the_entry_marked(self):
        facts = copy.deepcopy(self.facts)
        gone = self.work[0]['bullets'][1]['id']
        next(f for f in facts if f['id'] == gone)['status'] = 'unconfirmed'
        facts = [f for f in facts if f['id'] != self.work[1]['head']['id']]
        result = S.mark_stale(self.good, facts)
        entries = result['sections'][1]['entries']
        self.assertEqual(len(entries[0]['bullets']), 1)
        self.assertEqual(entries[0]['status'], 'stale')
        self.assertIsNone(entries[1]['head'])
        self.assertEqual(entries[1]['status'], 'stale')
        self.assertNotIn(gone, {item['id'] for _, item in S._refs(result)})
        S.validate(result, facts)

    def test_new_confirmed_fact_goes_to_unassigned(self):
        facts = copy.deepcopy(self.facts) + [dict(id='intake-new', text='新增的一行', status='confirmed', version=1)]
        result = S.mark_stale(self.good, facts)
        self.assertEqual(result['unassigned'][-1], {'id': 'intake-new', 'version': 1})
        S.validate(result, facts)

    def test_the_stale_fixture_is_what_mark_stale_produces(self):
        self.assertEqual(S.mark_stale(self.good, load('facts-changed.json')), load('structure-stale.json'))
        self.assertEqual(S.open_items(load('structure-stale.json'))['stale'], 2)


class MigrateTests(Case):
    def test_first_use_with_confirmed_facts_and_no_structure_is_prefilled_not_confirmed(self):
        result = S.migrate(self.facts, None)
        self.assertEqual((result['status'], result['version'], result['confirmed_at']), ('prefilled', 0, None))
        self.assertIsNone(S.migrate([], None))
        self.assertIsNone(S.migrate([dict(self.facts[0], status='unconfirmed')], None))

    def test_migration_never_changes_facts(self):
        before = copy.deepcopy(self.facts)
        S.migrate(self.facts, None)
        self.assertEqual(self.facts, before)

    def test_confirmed_structure_survives_fact_changes_as_stale(self):
        facts = copy.deepcopy(self.facts)
        facts[7]['version'] = 2
        result = S.migrate(facts, load('structure.json'))
        self.assertEqual((result['status'], result['version']), ('confirmed', 1))
        self.assertEqual(S.open_items(result)['stale'], 1)

    def test_prefilled_structure_is_rebuilt_when_the_facts_moved(self):
        stored = S.build(self.facts, 3)
        facts = copy.deepcopy(self.facts)
        facts[7]['text'] += '（补充）'
        facts[7]['version'] = 2
        result = S.migrate(facts, stored)
        self.assertEqual((result['status'], result['version']), ('prefilled', 3))
        self.assertEqual(S.open_items(result)['stale'], 0)
        self.assertEqual(S.migrate(self.facts, stored), stored)

    def test_a_replacement_resume_gets_a_fresh_structure_with_a_higher_version_base(self):
        other = [dict(id='x1', text='工作经历', status='confirmed', version=1), dict(id='x2', text='2020.01-2021.01 某某公司 工程师', status='confirmed', version=1)]
        result = S.migrate(other, load('structure.json'))
        self.assertEqual((result['status'], result['version']), ('prefilled', 1))
        self.assertEqual(len(result['sections']), 1)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'app')

    def confirm_example_resume(self):
        content = (EXAMPLES / 'resume.synthetic.txt').read_bytes()
        import base64
        state = self.store.upload_resume(dict(filename='resume.synthetic.txt', content_base64=base64.b64encode(content).decode(), synthetic=True))
        draft = state['candidate_draft']
        self.store.action(dict(action='resume_confirm', draft_id=draft['id'], confirmed_fact_ids=[f['id'] for f in draft['candidate']['facts']]))

    def test_no_confirmed_fact_means_no_structure(self):
        # the built-in synthetic candidate has confirmed facts; a candidate with none has nothing to structure
        candidate = copy.deepcopy(self.store.state()['candidate'])
        for f in candidate['facts']: f['status'] = 'unconfirmed'
        self.store.import_candidate(candidate)
        self.assertIsNone(self.store.structure_get()['structure'])

    def test_legacy_candidate_gets_a_prefilled_structure_on_first_use_and_it_is_stored(self):
        first = self.store.action(dict(action='structure_get'))['result']
        self.assertEqual((first['structure']['status'], first['structure']['version']), ('prefilled', 0))
        self.assertEqual(len(first['facts']), len(first['structure']['unassigned']))
        with self.store.tx() as c:
            self.assertEqual(self.store.structure_stored(c), first['structure'])
        self.assertEqual(self.store.structure_get()['structure'], first['structure'])

    def test_walk_through_prefill_correct_confirm(self):
        self.confirm_example_resume()
        got = self.store.action(dict(action='structure_get'))['result']
        structure = got['structure']
        self.assertEqual(structure['status'], 'prefilled')
        self.assertGreater(got['open']['uncertain'], 0)
        self.assertTrue(got['fragments'])
        with self.assertRaises(Error):  # uncertain fields are still open
            self.store.structure_save(dict(structure=structure, base_version=0, confirm=True))
        for section in structure['sections']:
            for entry in section['entries']:
                for field in entry['fields'].values(): field['confidence'] = 'ok'
        saved = self.store.action(dict(action='structure_save', structure=structure, base_version=0, confirm=True))['result']
        self.assertEqual((saved['structure']['status'], saved['structure']['version']), ('confirmed', 1))
        self.assertTrue(saved['structure']['confirmed_at'])
        again = self.store.structure_get()
        self.assertEqual(again['structure'], saved['structure'])
        self.assertEqual(again['open'], dict(uncertain=0, stale=0, unassigned=4))

    def test_save_rejects_stale_base_version_unbalanced_confirm_flag_and_forged_facts(self):
        self.confirm_example_resume()
        structure = self.store.structure_get()['structure']
        with self.assertRaises(Error): self.store.structure_save(dict(structure=structure, base_version=5, confirm=False))
        with self.assertRaises(Error): self.store.structure_save(dict(structure=structure, base_version=0))
        forged = copy.deepcopy(structure)
        forged['unassigned'].append({'id': 'intake-forged', 'version': 1})
        with self.assertRaises(Error): self.store.structure_save(dict(structure=forged, base_version=0, confirm=False))
        saved = self.store.structure_save(dict(structure=structure, base_version=0, confirm=False))
        self.assertEqual((saved['structure']['status'], saved['structure']['version']), ('prefilled', 0))

    def test_confirmed_structure_goes_stale_when_a_fact_is_edited(self):
        self.confirm_example_resume()
        structure = self.store.structure_get()['structure']
        for section in structure['sections']:
            for entry in section['entries']:
                for field in entry['fields'].values(): field['confidence'] = 'ok'
        self.store.structure_save(dict(structure=structure, base_version=0, confirm=True))
        with self.store.tx() as c:
            candidate = self.store.meta(c, 'candidate')
            bullet = structure['sections'][1]['entries'][0]['bullets'][0]['id']
            next(f for f in candidate['facts'] if f['id'] == bullet)['version'] += 1
            self.store.setmeta(c, 'candidate', candidate)
        got = self.store.structure_get()
        self.assertEqual(got['open']['stale'], 1)
        self.assertEqual(got['structure']['version'], 1)
        with self.assertRaises(Error):
            self.store.structure_save(dict(structure=got['structure'], base_version=1, confirm=True))


if __name__ == '__main__':
    unittest.main()
