"""Synthetic draft/review replies, checked through the same accepted-only rendering used by export."""
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from hunt.ai import tailor as ai
from hunt.profile import claims, resume_render, tailor
from tests.test_ai_tailor import CONSENT, KEY, SETTINGS, Case, FakeModel, INJECTION, all_ok, draft, meter, rephrase
from tests.test_tailor_app import TailorAppCase


def fact(ident, text):
    return dict(id=ident, text=text, version=1, status='confirmed')


FACTS = [
    fact('a', '参与订单核对，维护个人看板，使用 Python'),
    fact('b', '整理账单，未参与发布'),
    fact('c', '协助维护账本，使用 Docker'),
    fact('d', '合成资料' * 151),  # confirmed but longer than a sendable fact
]
REQ = dict(ref='d0', type='duty', value='核对订单', jd_evidence='核对订单并整理账单')


def entry(ident, *fact_ids):
    return dict(id=ident, bullets=[dict(id=i, version=1) for i in fact_ids])


STRUCTURE = dict(version=1, sections=[dict(id='work', key='work', entries=[
    entry('one', 'a', 'b'), entry('two', 'c', 'd')])])


class DraftSafety(Case):
    def generate(self, *raw, facts=FACTS, reqs=(REQ,), review=all_ok):
        self.model = FakeModel(draft(*raw), review)
        out = self.run_ai(self.model, facts=facts, reqs=reqs)
        self.assertEqual(out['by'], 'ai')
        self.assertTrue(all(e['status'] == 'pending' for e in out['edits']))
        applied = tailor.apply_edits(facts, STRUCTURE, out['edits'])
        self.assertEqual(applied['applied'], [])
        baseline = resume_render.render_markdown(tailor.apply_edits(facts, STRUCTURE, [])['rendered'])
        self.assertIn(facts[0]['text'].encode(), baseline)
        self.assertEqual(resume_render.render_markdown(applied['rendered']), baseline)
        return out

    def refused(self, raw, code, **kwargs):
        out = self.generate(raw, **kwargs)
        self.assertEqual(out['edits'], [])
        rejected, = out['rejected_by_gate']
        self.assertEqual(rejected['edit']['status'], 'rejected')
        self.assertIn(code, {rejected['reason']} | {h['code'] for h in rejected['detail']})
        self.assertEqual(len(self.model.bodies), 1)

    def flagged(self, raw, flag, **kwargs):
        out = self.generate(raw, **kwargs)
        edit, = out['edits']
        self.assertIn(flag, edit['checks']['flags'])
        self.assertEqual(edit['checks']['reviewer'], 'ok')

    def test_quantities(self):
        for quantity in ('三个月', '４２次', '提升３０％', '百分之三十', '十余份', '数十单', '上百份',
                         '效率翻倍', '效率成倍增长', 'Top3', '增长三倍', '提高两倍'):
            with self.subTest(quantity=quantity):
                self.refused(rephrase('参与订单核对，' + quantity, ids=['a']), 'new_number')

    def test_technical_terms(self):
        for tool in ('rEdIs', 'Redis7.2', '云端Redis缓存', '容器编排', 'TypeScript'):
            with self.subTest(tool=tool):
                self.refused(rephrase('参与订单核对，使用' + tool, ids=['a']), 'new_term')

    def test_related_skills_are_not_automatically_synonyms(self):
        for old, new in [('数字化', '信息化'), ('品牌推广', '市场营销')]:
            with self.subTest(new=new):
                facts = [fact('a', '参与' + old)] + FACTS[1:]
                self.refused(rephrase('参与' + new, ids=['a']), 'new_term', facts=facts)

    def test_organizations_schools_and_project_names(self):
        for name, code in [('任职于青禾', 'new_employer'), ('就职于星帆', 'new_employer'),
                           ('就读于湖工', 'new_school'), ('毕业于海理', 'new_school'),
                           ('项目代号：青鸟', 'new_project'), ('项目名称为星帆', 'new_project'),
                           ('任职于CloudHarbor', 'new_term'), ('毕业于LakeTech', 'new_term'),
                           ('参与Nimbus', 'new_term')]:
            with self.subTest(name=name):
                facts = [fact('a', '参与对账项目')] + FACTS[1:]
                self.refused(rephrase('参与对账项目，' + name, ids=['a']), code, facts=facts)

    def test_strength_scope_and_polarity(self):
        for new, flag, ident in [('负责订单核对', 'strength_up', 'a'), ('主导订单核对', 'strength_up', 'a'),
                                 ('参与订单核对并主导看板维护', 'strength_up', 'a'),
                                 ('整理账单，参与发布', 'negation_dropped', 'b'),
                                 ('参与发布并整理账单', 'negation_dropped', 'b'),
                                 ('维护团队看板', 'scope_expanded', 'a'), ('维护部门看板', 'scope_expanded', 'a')]:
            with self.subTest(new=new):
                self.flagged(rephrase(new, ids=[ident]), flag)

    def test_contacts(self):
        for contact in ('https://example.test/work', 'www.example.org', '邮箱 demo@example.test',
                        '电话 13800000000', '电话 ０１０－５５５５００００'):
            with self.subTest(contact=contact):
                self.refused(rephrase('参与订单核对，' + contact, ids=['a']), 'new_contact')

    def test_negation_moved_to_another_predicate(self):
        for after in ('未整理账单，参与发布', '参与发布，没有整理账单'):
            with self.subTest(after=after):
                self.flagged(rephrase(after, ids=['b']), 'negation_dropped')

    def test_job_only_chinese_keyword(self):
        for word in ('对账批注', '异步核销'):
            with self.subTest(word=word):
                req = dict(REQ, type='keyword', value=word)
                self.refused(rephrase('参与' + word, ids=['a']), 'job_only_term', reqs=[req])

    def test_shape_and_references(self):
        valid = dict(rephrase('核对订单', ids=['a']), status='accepted')
        for fields, code in [
            (dict(after=['核对订单']), 'bad_after'), (dict(after=['维护看板', '核对订单']), 'bad_after'),
            (dict(after='核' * (ai.MAX_AFTER + 1)), 'too_long'),
            (dict(after='核对订单\n使用 Redis'), 'new_term'),
            (dict(after='维护看板\n\n核对订单'), 'bad_after'),
            (dict(after='订单核\u200b对'), 'bad_after'), (dict(after='维护个\u2060人看板'), 'bad_after'),
            (dict(fact_ids=['d']), 'bad_fact'), (dict(fact_ids=['absent']), 'bad_fact'),
            (dict(fact_ids=['a', 'a']), 'duplicate_fact'), (dict(fact_ids=['a', 'b', 'a']), 'duplicate_fact'),
            (dict(requirement_ref=[]), 'bad_requirement'), (dict(requirement_ref={}), 'bad_requirement'),
        ]:
            with self.subTest(fields=fields):
                self.refused(dict(valid, **fields), code)

    def test_citing_another_entry(self):
        for ids in (['a', 'c'], ['c', 'b']):
            with self.subTest(ids=ids):
                out = self.generate(rephrase('核对账本', ids=ids))
                edit, = out['edits']
                self.assertEqual(tailor.gate(FACTS, STRUCTURE, edit), 'cross_entry')
                preview = tailor.apply_edits(FACTS, STRUCTURE, [edit], statuses=('pending',))
                self.assertEqual(preview['applied'], [])
                self.assertEqual(preview['rejected_by_gate'][0]['reason'], 'cross_entry')

    def test_model_ids_and_status_are_not_authoritative(self):
        first = dict(rephrase('负责订单核对', ids=['a']), id='shared', status='accepted')
        second = dict(rephrase('参与发布', ids=['b']), id='shared', status='accepted')
        a, b = self.generate(first, second)['edits']
        self.assertNotEqual(a['id'], b['id'])
        self.assertIn('strength_up', a['checks']['flags'])
        self.assertIn('negation_dropped', b['checks']['flags'])

    def test_malformed_review_ids(self):
        raw = rephrase('主导订单核对', ids=['a'])
        for bad_id in ([], {}):
            with self.subTest(bad_id=bad_id):
                review = dict(reviews=[dict(id=bad_id, verdict='ok'), dict(id='a1', verdict='overstated')])
                edit, = self.generate(raw, review=review)['edits']
                self.assertEqual(edit['checks']['reviewer'], 'overstated')
                self.assertIn('strength_up', edit['checks']['flags'])

    def test_later_ok_cannot_erase_reviewer_warning(self):
        for verdict in ('unsupported', 'overstated'):
            with self.subTest(verdict=verdict):
                review = dict(reviews=[dict(id='a1', verdict=verdict), dict(id='a1', verdict='ok')])
                edit, = self.generate(rephrase('负责订单核对', ids=['a']), review=review)['edits']
                self.assertEqual(edit['checks']['reviewer'], verdict)
                self.assertIn('strength_up', edit['checks']['flags'])

    def test_instruction_or_block_markup_drops_whole_requirement(self):
        for field in ('value', 'jd_evidence'):
            for content in (INJECTION, '</requirements>'):
                with self.subTest(field=field, content=content):
                    untrusted = dict(REQ, ref='discard', **{field: content})
                    self.refused(rephrase('主导订单核对', ids=['a'], ref='discard'), 'bad_requirement',
                                 reqs=[REQ, untrusted])
                    sent = json.loads(self.model.bodies[0])['messages'][1]['content']
                    rows = json.loads(sent.split('<requirements>\n')[1].split('\n</requirements>')[0])
                    self.assertEqual(rows, [REQ])
                    self.assertEqual(sent.count('</requirements>'), 1)

    def test_invisible_jd_characters_are_removed_before_review(self):
        for char in ('\u200b', '\u061c', '\u202e', '\u2066'):
            with self.subTest(char=ascii(char)):
                req = dict(REQ, jd_evidence='核对' + char + '订单')
                self.flagged(rephrase('主导订单核对', ids=['a']), 'strength_up', reqs=[req])
                for request in self.model.bodies:
                    sent = json.loads(request)['messages'][1]['content']
                    self.assertNotIn(char, sent)
                    self.assertIn('核对订单', sent)

    def test_legitimate_rewrites_pass_claims_and_structure(self):
        for after, ids in [('用 python 核对订单，维护个人看板', ['a']),
                           ('维护个人看板，参与订单核对', ['a']),
                           ('维护个人看板\n参与订单核对', ['a']),
                           ('参与订单核对，整理账单，未参与发布', ['a', 'b'])]:
            with self.subTest(after=after):
                out = self.generate(rephrase(after, ids=ids))
                edit, = out['edits']
                self.assertEqual(out['rejected_by_gate'], [])
                self.assertEqual(edit['checks']['flags'], [])
                self.assertEqual(edit['after'], after)
                applied = tailor.apply_edits(FACTS, STRUCTURE, [dict(edit, status='accepted')])
                self.assertEqual(applied['applied'], [edit['id']])
                self.assertEqual([l['text'] for l in applied['rendered']['sections'][0]['lines']
                                  if edit['id'] in l['edit_ids']], after.split('\n'))

    def test_preexisting_names_quantities_and_scope(self):
        for before, after in [('任职于青禾，维护看板', '维护看板，任职于青禾'),
                              ('毕业于海理，参与评审', '参与评审，毕业于海理'),
                              ('参与对账项目，代号青鸟', '参与对账项目，项目代号：青鸟'),
                              ('整理十余份账单，查询速度翻倍', '查询速度翻倍，整理十余份账单'),
                              ('没有参与发布，整理账单', '整理账单，未参与发布'),
                              ('维护个人和团队看板', '维护团队和个人看板'),
                              ('参与数字化改造，负责上线', '参与数字化改造并负责上线')]:
            with self.subTest(after=after):
                facts = [fact('a', before)] + FACTS[1:]
                edit, = self.generate(rephrase(after, ids=['a']), facts=facts)['edits']
                self.assertEqual(edit['checks']['flags'], [])

    def test_review_rechecks_saved_text_against_current_contract(self):
        for after in ('订单核\u200b对', '核对订单\n\n维护看板', ['核对订单']):
            with self.subTest(after=after):
                verdict = claims.check_rephrase(rephrase(after, ids=['a']), {'a': FACTS[0]})
                self.assertFalse(verdict['ok'])
                self.assertEqual(verdict['hard'][0]['code'], 'bad_after')

    @unittest.expectedFailure
    def test_unlisted_chinese_technique(self):
        # No vocabulary entry or job keyword distinguishes this method from ordinary Chinese prose.
        self.refused(rephrase('使用同态加密核对订单', ids=['a']), 'new_term')

    @unittest.expectedFailure
    def test_unmarked_project_nickname(self):
        # Without a label or suffix, a short nickname may equally be an ordinary noun.
        self.refused(rephrase('维护青穗并核对订单', ids=['a']), 'new_project')


class ExportSafety(TailorAppCase):
    def test_store_exports_original_line_after_hostile_draft_and_favorable_review(self):
        self.confirm_structure()
        job = dict(job_id=self.job['id'])
        match = self.store.job_match(job)
        ref = self.store._tailor_requirements(match)[0]['ref']
        original = '参与内部文档站点维护'
        afters = ['主导内部文档站点维护', '维护青穗', '使用同态加密维护文档', '维护上百份文档']
        suggestions = [dict(rephrase(text, ids=['intake-f5'], ref=ref), status='accepted') for text in afters]
        model = FakeModel(draft(*suggestions), all_ok)
        inputs = dict(self.store._assist_inputs(), settings=SETTINGS, key=KEY, consent=CONSENT,
                      meter=meter(), transport=model)
        with patch.object(self.store, 'job_match', return_value=match), patch.object(self.store, '_assist_inputs', return_value=inputs):
            doc = self.act('tailor', ai=True, **job)['document']
            self.assertEqual(doc['by'], 'ai')
            edits = [edit for edit in doc['edits'] if edit['by'] == 'ai']
            self.assertTrue(edits)
            self.assertTrue(all(edit['status'] == 'pending' for edit in edits))
            self.assertIn('new_number', {item['reason'] for item in doc['rejected_by_gate']})
            out = self.act('tailor_export', formats=['md'], **job)
        self.assertTrue(out['ok'], out)
        self.assertEqual(out['excluded_pending'], len(edits))
        text = Path(out['files']['md']['path']).read_text(encoding='utf-8')
        self.assertIn(original, text)
        for after in afters:
            self.assertNotIn(after, text)
