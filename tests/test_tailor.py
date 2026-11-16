"""Rule path, apply_edits, check_result and trace of hunt/profile/tailor.py, on a synthetic résumé fixture."""
import copy
import json
import unittest
from pathlib import Path

from hunt.profile import tailor

FIX = Path(__file__).parent / 'fixtures' / 'tailor'


def load(name):
    return json.loads((FIX / (name + '.json')).read_text(encoding='utf-8'))


def fid(key):
    return 'intake-' + key


def ref(key, version=1):
    return dict(id=fid(key), version=version)


def texts(rendered, section=None):
    return [l['text'] for s in rendered['sections'] if section in (None, s['id']) for l in s['lines']]


def edit(op, keys, before, after, eid='x1', requirement=None, status='accepted'):
    return dict(id=eid, op=op, fact_ids=[ref(k) for k in keys], requirement=requirement, before=before, after=after,
                why='t', by='ai', status=status)


class Base(unittest.TestCase):
    def setUp(self):
        self.facts, self.structure, self.match = load('facts'), load('structure'), load('match')
        self.text = {f['id']: f['text'] for f in self.facts}

    def t(self, key):
        return self.text[fid(key)]


class RulePath(Base):
    def setUp(self):
        super().setUp()
        self.out = tailor.propose(self.facts, self.structure, self.match)

    def by_op(self, op):
        return [e for e in self.out['edits'] if e['op'] == op]

    def test_alias_only_for_whitelisted_synonyms(self):
        aliases = {e['fact_ids'][0]['id']: e for e in self.by_op('alias')}
        self.assertEqual(set(aliases), {fid('f4'), fid('f6')})
        self.assertEqual(aliases[fid('f6')]['after'], '负责在 Kubernetes 集群上部署微服务，使用 Docker 打包')
        self.assertEqual(aliases[fid('f4')]['after'], '负责订单服务的 PostgreSQL 数据库优化，查询耗时下降 40%')
        self.assertEqual(aliases[fid('f6')]['requirement']['ref'], 'k0')

    def test_block_reorder_keeps_the_set_and_moves_relevant_first(self):
        block = [e for e in self.by_op('reorder') if len(e['fact_ids']) > 1]
        self.assertEqual(len(block), 1)
        self.assertEqual([r['id'] for r in block[0]['fact_ids']], [fid('f4'), fid('f6'), fid('f5')])
        self.assertEqual(block[0]['before'].split('\n'), [self.t('f4'), self.t('f5'), self.t('f6')])

    def test_skill_line_names_the_jobs_items_first(self):
        line = [e for e in self.by_op('reorder') if len(e['fact_ids']) == 1][0]
        self.assertEqual(line['after'], '技能：SQL、Python、Docker、Excel')

    def test_stale_entry_is_never_touched(self):
        touched = {r['id'] for e in self.out['edits'] for r in e['fact_ids']}
        self.assertFalse(touched & {fid('f7'), fid('f8'), fid('f9')})

    def test_gaps_are_taken_from_the_match(self):
        gaps = {(g['type'], g['requirement']) for g in self.out['gaps']}
        self.assertEqual(gaps, {('absent', 'Kafka'), ('related', 'TypeScript'), ('hard_unknown', '3年以上')})

    def test_no_hide_without_a_line_limit(self):
        self.assertEqual(self.by_op('hide'), [])

    def test_hide_oldest_irrelevant_bullet_when_over_the_limit(self):
        out = tailor.propose(self.facts, self.structure, self.match, line_limit=14)
        hides = [e for e in out['edits'] if e['op'] == 'hide']
        self.assertEqual([e['fact_ids'][0]['id'] for e in hides], [fid('f5')])
        self.assertIsNone(hides[0]['after'])

    def test_rules_edits_are_accepted_and_by_rules(self):
        self.assertTrue(all(e['by'] == 'rules' and e['status'] == 'accepted' for e in self.out['edits']))


class Build(Base):
    def test_applied_rule_path_traces_and_passes_checks(self):
        doc = tailor.build('job1', 3, self.facts, self.structure, self.match, jd_digest='d')
        self.assertEqual(doc['id'], 'tl-job1-v3')
        self.assertEqual(doc['checks']['trace'], 'pass')
        self.assertEqual(doc['checks']['result'], 'pass')
        self.assertEqual(doc['rejected_by_gate'], [])
        self.assertEqual(doc['structure'], dict(version=4))
        applied = tailor.apply_edits(self.facts, self.structure, doc['edits'])
        self.assertEqual(tailor.trace(self.facts, applied['rendered'], doc['edits'])['status'], 'pass')

    def test_rendered_text(self):
        doc = tailor.build('job1', 1, self.facts, self.structure, self.match)
        rendered = tailor.apply_edits(self.facts, self.structure, doc['edits'])['rendered']
        self.assertEqual(texts(rendered, 's1'), [
            '工作经历', self.t('f3'),
            '负责订单服务的 PostgreSQL 数据库优化，查询耗时下降 40%', '负责在 Kubernetes 集群上部署微服务，使用 Docker 打包', self.t('f5'),
            self.t('f7'), self.t('f8'), self.t('f9')])  # stale entry: original text, original order
        self.assertEqual(texts(rendered, 's2'), ['专业技能', '技能：SQL、Python、Docker、Excel'])

    def test_unassigned_and_unconfirmed_facts_stay_out(self):
        doc = tailor.build('job1', 1, self.facts, self.structure, self.match)
        rendered = tailor.apply_edits(self.facts, self.structure, doc['edits'])['rendered']
        self.assertNotIn(self.t('f15'), texts(rendered))
        self.assertNotIn(self.t('f16'), texts(rendered))

    def test_no_edits_renders_the_structure_in_order(self):
        rendered = tailor.apply_edits(self.facts, self.structure, [])['rendered']
        self.assertEqual(texts(rendered, 's1')[:5], ['工作经历', self.t('f3'), self.t('f4'), self.t('f5'), self.t('f6')])


class Gates(Base):
    def reject(self, e):
        out = tailor.apply_edits(self.facts, self.structure, [e])
        self.assertEqual(out['applied'], [], e)
        return out['rejected_by_gate'][0]['reason']

    def test_operation_outside_the_set(self):
        self.assertEqual(self.reject(edit('add', ['f4'], self.t('f4'), 'x')), 'op_not_allowed')

    def test_identity_lines_cannot_be_rephrased(self):
        self.assertEqual(self.reject(edit('rephrase', ['f14'], self.t('f14'), '主修算法')), 'identity_line')  # education section
        self.assertEqual(self.reject(edit('rephrase', ['f1'], self.t('f1'), '邮箱：a@b.cn')), 'identity_line')
        self.assertEqual(self.reject(edit('rephrase', ['f3'], self.t('f3'), '某公司')), 'unknown_target')  # entry head

    def test_before_must_match_the_fact_verbatim(self):
        self.assertEqual(self.reject(edit('rephrase', ['f5'], '参与文档站点维护', '维护文档站点')), 'before_mismatch')

    def test_reorder_must_keep_the_same_set(self):
        short = edit('reorder', ['f6', 'f4'], self.t('f4') + '\n' + self.t('f5') + '\n' + self.t('f6'), self.t('f6') + '\n' + self.t('f4'))
        self.assertEqual(self.reject(short), 'reorder_set_mismatch')
        items = edit('reorder', ['f11'], self.t('f11'), '技能：SQL、Python、Docker、Kafka')
        self.assertEqual(self.reject(items), 'reorder_set_mismatch')

    def test_heads_titles_and_stale_entries_cannot_be_targeted(self):
        self.assertEqual(self.reject(edit('hide', ['f3'], self.t('f3'), None)), 'unknown_target')
        self.assertEqual(self.reject(edit('hide', ['f2'], self.t('f2'), None)), 'unknown_target')
        self.assertEqual(self.reject(edit('hide', ['f8'], self.t('f8'), None)), 'unknown_target')
        self.assertEqual(self.reject(edit('hide', ['f15'], self.t('f15'), None)), 'unknown_target')

    def test_unconfirmed_missing_and_changed_facts(self):
        self.assertEqual(self.reject(edit('hide', ['f16'], self.t('f16'), None)), 'not_confirmed')
        e = edit('hide', ['f5'], self.t('f5'), None)
        e['fact_ids'] = [ref('f5', 2)]
        self.assertEqual(self.reject(e), 'stale_fact')

    def test_alias_outside_the_whitelist(self):
        e = edit('alias', ['f6'], self.t('f6'), self.t('f6').replace('k8s', 'Kubernetes').replace('Docker', 'Podman'),
                 requirement=dict(type='keyword', value='Kubernetes'))
        self.assertEqual(self.reject(e), 'alias_not_whitelisted')
        near = edit('alias', ['f5'], self.t('f5'), '参与内部文档站点维护', requirement=dict(type='keyword', value='TypeScript'))
        self.assertEqual(self.reject(near), 'alias_not_whitelisted')

    def test_two_edits_on_one_fact_conflict(self):
        a = edit('hide', ['f5'], self.t('f5'), None, eid='a')
        b = edit('rephrase', ['f5'], self.t('f5'), '维护文档站点', eid='b')
        out = tailor.apply_edits(self.facts, self.structure, [a, b])
        self.assertEqual([r['reason'] for r in out['rejected_by_gate']], ['conflict'])

    def test_only_accepted_edits_apply(self):
        pending = edit('hide', ['f5'], self.t('f5'), None, status='pending')
        out = tailor.apply_edits(self.facts, self.structure, [pending])
        self.assertIn(self.t('f5'), texts(out['rendered']))
        out = tailor.apply_edits(self.facts, self.structure, [pending], statuses=('accepted', 'pending'))
        self.assertNotIn(self.t('f5'), texts(out['rendered']))

    def test_rephrase_and_merge_are_applied_and_traced(self):
        e = edit('rephrase', ['f4', 'f5'], self.t('f4') + '\n' + self.t('f5'), '优化订单服务的 Postgres 查询，耗时下降 40%\n维护内部文档站点')
        out = tailor.apply_edits(self.facts, self.structure, [e])
        self.assertEqual(out['applied'], ['x1'])
        self.assertEqual(texts(out['rendered'], 's1')[2:4], ['优化订单服务的 Postgres 查询，耗时下降 40%', '维护内部文档站点'])
        self.assertEqual(tailor.trace(self.facts, out['rendered'], [e])['status'], 'pass')
        self.assertTrue(tailor.check_result(self.facts, self.structure, out['rendered'], [e])['ok'])


class AfterChecks(Base):
    def run_rephrase(self, key, after):
        e = edit('rephrase', [key], self.t(key), after)
        out = tailor.apply_edits(self.facts, self.structure, [e])
        self.assertEqual(out['applied'], ['x1'])
        return tailor.check_result(self.facts, self.structure, out['rendered'], [e])

    def codes(self, result):
        return {p['code'] for p in result['problems']}

    def test_new_number_and_chinese_quantifier(self):
        self.assertEqual(self.codes(self.run_rephrase('f5', '维护 3 个内部文档站点')), {'new_number'})
        self.assertEqual(self.codes(self.run_rephrase('f5', '维护内部文档站点，提升三倍')), {'new_number'})
        self.assertTrue(self.run_rephrase('f4', '优化订单服务的 Postgres 数据库，耗时下降 40%')['ok'])

    def test_growth_over_one_and_a_half(self):
        self.assertEqual(self.codes(self.run_rephrase('f5', '参与内部文档站点维护，包括页面更新、内容整理和日常巡检工作')), {'growth'})

    def test_head_line_changed(self):
        facts = copy.deepcopy(self.facts)
        rendered = tailor.apply_edits(facts, self.structure, [])['rendered']
        rendered['sections'][1]['lines'][1]['text'] = '星河科技有限公司 技术总监 2021.07-2023.03'
        self.assertEqual(self.codes(tailor.check_result(facts, self.structure, rendered)), {'identity'})

    def test_block_count(self):
        rendered = tailor.apply_edits(self.facts, self.structure, [])['rendered']
        rendered['sections'].pop()
        self.assertEqual(self.codes(tailor.check_result(self.facts, self.structure, rendered)), {'block_count'})


class Trace(Base):
    def test_invented_line_fails(self):
        rendered = tailor.apply_edits(self.facts, self.structure, [])['rendered']
        rendered['sections'][1]['lines'][2]['text'] = '主导公司核心系统重构'
        out = tailor.trace(self.facts, rendered, [])
        self.assertEqual(out['status'], 'fail')
        self.assertEqual(out['problems'][0]['code'], 'unsupported_line')

    def test_line_without_fact_fails(self):
        rendered = tailor.apply_edits(self.facts, self.structure, [])['rendered']
        rendered['sections'][1]['lines'][2]['fact_ids'] = []
        self.assertEqual(tailor.trace(self.facts, rendered, [])['problems'][0]['code'], 'no_fact')

    def test_fact_changed_after_rendering_fails(self):
        doc = tailor.build('j', 1, self.facts, self.structure, self.match)
        rendered = tailor.apply_edits(self.facts, self.structure, doc['edits'])['rendered']
        facts = copy.deepcopy(self.facts)
        next(f for f in facts if f['id'] == fid('f5'))['version'] = 2
        self.assertEqual(tailor.trace(facts, rendered, doc['edits'])['status'], 'fail')

    def test_unaccepted_edit_cannot_back_a_line(self):
        doc = tailor.build('j', 1, self.facts, self.structure, self.match)
        rendered = tailor.apply_edits(self.facts, self.structure, doc['edits'])['rendered']
        edits = [dict(e, status='pending') for e in doc['edits']]
        self.assertEqual(tailor.trace(self.facts, rendered, edits)['status'], 'fail')

    def test_trace_lines_carry_fact_ids_and_edit_ids(self):
        doc = tailor.build('j', 1, self.facts, self.structure, self.match)
        rendered = tailor.apply_edits(self.facts, self.structure, doc['edits'])['rendered']
        lines = tailor.trace(self.facts, rendered, doc['edits'])['lines']
        alias = [l for l in lines if 'Kubernetes' in l['text']][0]
        self.assertEqual(alias['fact_ids'], [ref('f6')])
        self.assertEqual(len(alias['edit_ids']), 1)


class Status(Base):
    def test_refresh_status_marks_changed_and_unconfirmed(self):
        edits = [edit('hide', ['f5'], self.t('f5'), None, eid='a'), edit('hide', ['f4'], self.t('f4'), None, eid='b'),
                 edit('hide', ['f6'], self.t('f6'), None, eid='c', status='rejected')]
        facts = copy.deepcopy(self.facts)
        next(f for f in facts if f['id'] == fid('f5'))['version'] = 2
        next(f for f in facts if f['id'] == fid('f6'))['status'] = 'unconfirmed'
        self.assertEqual({e['id']: e['status'] for e in tailor.refresh_status(facts, edits)}, dict(a='stale', b='accepted', c='rejected'))

    def test_synonym_whitelist(self):
        self.assertTrue(tailor.equivalent('k8s', 'Kubernetes'))
        self.assertTrue(tailor.equivalent('LLM', '大语言模型'))
        for a, b in (('容器编排', 'Kubernetes'), ('JavaScript', 'TypeScript'), ('深度学习', '机器学习')):
            self.assertFalse(tailor.equivalent(a, b))


if __name__ == '__main__':
    unittest.main()
