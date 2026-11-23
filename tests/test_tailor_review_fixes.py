"""Regressions from the 2026-11 review of per-job tailoring. Synthetic data only."""
import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from hunt.base import Error
from hunt.profile import claims, resume_render as rr, structure as S, tailor
from tests.test_tailor_app import TailorAppCase

FIX = Path(__file__).parent / 'fixtures' / 'tailor'


def load(name):
    return json.loads((FIX / (name + '.json')).read_text(encoding='utf-8'))


class SelfNoteTests(unittest.TestCase):
    def test_a_bullet_that_only_starts_with_a_negative_character_stays_in_its_entry(self):
        row = lambda i, t: dict(id=i, text=t, status='confirmed', version=1)
        facts = [row('a', '工作经历'), row('b', '示例科技有限公司 后端工程师 2021.03-2023.06'), row('c', '负责订单服务开发'),
                 row('d', '无人机航拍数据处理平台开发'), row('e', '无线通信模块联调'), row('f', '没有延期地交付全部迭代'),
                 row('g', '暂无管理经验。'), row('h', '使用 Docker 运行本地服务。')]
        built = S.build(facts)
        (entry,) = built['sections'][0]['entries']
        self.assertEqual([b['id'] for b in entry['bullets']], ['c', 'd', 'e', 'f'])
        self.assertEqual([u['id'] for u in built['unassigned']], ['g', 'h'])


class MarkdownTests(unittest.TestCase):
    RENDER = dict(sections=[
        dict(key='basic', title=None, lines=[dict(text='姓名：示例候选人', kind='text'), dict(text='邮箱：demo@example.com', kind='text')]),
        dict(key='work', title='工作经历', lines=[
            dict(text='示例科技有限公司 后端工程师 2021.03-2023.06', kind='head'), dict(text='# 1 号项目的订单服务开发', kind='bullet'),
            dict(text='- 以短横线开头的原文', kind='bullet'), dict(text='1. 以序号开头的条目头', kind='head'), dict(text='负责发布流程', kind='bullet')])])

    def test_text_lines_are_separate_paragraphs_and_bullets_stay_together(self):
        text = rr.render_markdown(self.RENDER).decode('utf-8')
        self.assertIn('姓名：示例候选人\n\n邮箱：demo@example.com\n', text)
        self.assertIn('2021.03-2023.06\n\n- \\# 1 号项目的订单服务开发\n- \\- 以短横线开头的原文\n\n1\\. 以序号开头的条目头\n\n- 负责发布流程\n', text)
        self.assertNotIn('2021\\.', text)

    def test_escaped_lines_read_back_as_written(self):
        check = rr.check_export(self.RENDER, 'r.md', rr.render_markdown(self.RENDER))
        self.assertEqual(check['missing_lines'], [])
        self.assertTrue(check['ok'], check)


class YearTests(unittest.TestCase):
    FACTS = {'a': dict(text='2021.03-2023.06 负责订单服务，日均 30 万单', version=1)}

    def verdict(self, after):
        return claims.check_rephrase(dict(after=after, fact_ids=['a']), self.FACTS)

    def test_a_year_the_fact_writes_with_a_dot_may_be_written_with_年(self):
        self.assertTrue(self.verdict('2021年起负责订单服务')['ok'])

    def test_other_years_and_other_units_are_still_new_numbers(self):
        for after in ('2020年起负责订单服务', '负责订单服务 30 年', '负责订单服务，日均 2021 万单'):
            with self.subTest(after=after):
                self.assertIn('new_number', {h['code'] for h in self.verdict(after)['hard']})

    def test_check_result_agrees(self):
        facts = [dict(id='t', text='工作经历', status='confirmed', version=1),
                 dict(id='a', text='2021.03 起负责订单服务', status='confirmed', version=1)]
        structure = dict(version=1, sections=[dict(id='s1', key='work', title_fact=dict(id='t', version=1), entries=[
            dict(id='n1', status='ok', head=None, fields={}, bullets=[dict(id='a', version=1)])])])
        line = lambda text: dict(structure_version=1, sections=[dict(id='s1', key='work', lines=[
            dict(text='工作经历', kind='title', fact_ids=[dict(id='t', version=1)], edit_ids=[], section='s1', entry=None),
            dict(text=text, kind='bullet', fact_ids=[dict(id='a', version=1)], edit_ids=['a1'], section='s1', entry='n1')])])
        self.assertTrue(tailor.check_result(facts, structure, line('2021年起负责订单服务'))['ok'])
        self.assertFalse(tailor.check_result(facts, structure, line('2020年起负责订单服务'))['ok'])


class EditableTests(unittest.TestCase):
    def setUp(self):
        self.facts, self.structure = load('facts'), load('structure')
        self.entries = [(s, e) for s in self.structure['sections'] for e in s['entries']]

    def test_only_bullets_that_are_not_identity_lines_are_editable(self):
        ids = {f['id'] for f in tailor.editable(self.facts, self.structure)}
        self.assertTrue(ids)
        heads = {e['head']['id'] for _, e in self.entries if e.get('head')}
        titles = {s['title_fact']['id'] for s in self.structure['sections'] if s.get('title_fact')}
        schooling = {b['id'] for s, e in self.entries if s['key'] in ('education', 'basic') for b in e['bullets']}
        self.assertFalse(ids & (heads | titles | schooling))
        self.assertTrue(ids <= {b['id'] for _, e in self.entries for b in e['bullets']})

    def test_gate_names_why_a_rewrite_of_an_entry_head_cannot_be_applied(self):
        head = next(e['head'] for _, e in self.entries if e.get('head'))
        text = next(f['text'] for f in self.facts if f['id'] == head['id'])
        edit = dict(id='a1', op='rephrase', fact_ids=[head], before=text, after=text + '。', status='pending')
        self.assertEqual(tailor.gate(self.facts, self.structure, edit), 'unknown_target')
        fact = tailor.editable(self.facts, self.structure)[0]
        ok = dict(id='a2', op='rephrase', fact_ids=[dict(id=fact['id'], version=fact.get('version', 1))], before=fact['text'],
                  after=fact['text'] + '。', status='pending')
        self.assertIsNone(tailor.gate(self.facts, self.structure, ok))


class ExportGateTests(TailorAppCase):
    def test_an_accepted_rewrite_that_fails_the_result_check_blocks_the_export(self):
        self.confirm_structure()
        made = self.act('tailor', job_id=self.job['id'])
        doc = made['document']
        current, facts, _ = self.store._tailor_gate()
        taken = {r['id'] for e in doc['edits'] if len(e['fact_ids']) == 1 for r in e['fact_ids']}  # lines whose text an edit already owns
        fact = next(f for f in tailor.editable(facts, current) if f['id'] not in taken)
        doc['edits'].append(dict(id='a1', op='rephrase', fact_ids=[dict(id=fact['id'], version=fact.get('version', 1))], requirement=None,
                                 before=fact['text'], after=fact['text'] + '，' + '持续稳定地推进相关工作' * 6, why='x', by='ai',
                                 status='accepted', checks=dict(hard='pass', flags=[], reviewer=None)))
        with self.store.tx() as c: self.store._tailor_save(c, doc)
        with self.assertRaises(Error) as ctx:
            self.act('tailor_export', job_id=self.job['id'], formats=['md'])
        self.assertIn('1.5 倍', str(ctx.exception))
        self.assertFalse((self.store.root / 'tailored').exists())


class DisclosureTests(TailorAppCase):
    def test_private_contact_facts_in_work_are_withheld_unless_opted_in(self):
        texts = ['工作经历', '示例科技有限公司 后端工程师 2021.03-2023.06', '参与服务开发',
                 'demo@example.com', '138 0000 4321', 'https://example.org/demo', '现居：示例城市',
                 '合成身份', '合成联系账号', 'published@example.com']
        facts = [dict(id=f'f{i}', text=text, version=1, status='confirmed', disclosure='private')
                 for i, text in enumerate(texts)]
        facts[7]['tags'] = ['identity']
        facts[8]['tags'] = ['contact']
        facts[9]['disclosure'] = 'application'
        with self.store.tx() as c:
            candidate = self.store.meta(c, 'candidate')
            self.store.setmeta(c, 'candidate', dict(candidate, facts=facts))
        self.confirm_structure()
        made = self.act('tailor', job_id=self.job['id'])
        self.assertEqual([s['key'] for s in made['rendered']['sections']], ['work'])
        self.assertEqual({w['text'] for w in made['basic_withheld']}, set(texts[3:9]))
        for include in (False, True):
            with self.subTest(include=include):
                out = self.act('tailor_export', job_id=self.job['id'], formats=['md'], include_private_basic=include)
                self.assertTrue(out['ok'], out)
                self.assertEqual(out['withheld_basic'], [] if include else made['basic_withheld'])
                md = Path(out['files']['md']['path']).read_text(encoding='utf-8')
                self.assertIn(texts[2], md)
                self.assertIn(texts[9], md)
                for private in texts[3:9]:
                    self.assertEqual(private in md, include, private)

    def test_a_private_second_reference_withholds_the_whole_rewritten_line(self):
        facts = [dict(id='a', text='开发服务'), dict(id='b', text='姓名：示例')]
        line = dict(kind='bullet', text='合并行', fact_ids=[dict(id='a'), dict(id='b')], edit_ids=['e'])
        rendered = dict(sections=[dict(key='work', lines=[line])])
        self.assertEqual(self.store._tailor_withheld(rendered, facts), [facts[1]])
        self.assertEqual(self.store._tailor_render(rendered, facts)['sections'], [])


class VersionAndConcurrencyTests(TailorAppCase):
    def setUp(self):
        super().setUp()
        self.confirm_structure()
        self.job_id = self.job['id']
        self.doc = self.act('tailor', job_id=self.job_id)['document']

    def test_review_of_displayed_old_version_leaves_latest_version_untouched(self):
        second = self.act('tailor', job_id=self.job_id)['document']
        with self.assertRaisesRegex(Error, '旧版本只读'):
            self.act('tailor_review', job_id=self.job_id, version=self.doc['version'], reject=[self.doc['edits'][0]['id']])
        self.assertEqual(self.act('tailor_get', job_id=self.job_id)['document']['edits'], second['edits'])
        out = self.act('tailor_export', job_id=self.job_id, version=self.doc['version'], formats=['md'])
        self.assertEqual(Path(out['dir']).name, 'v1')

    def test_reconfirmed_structure_requires_a_new_version_before_export(self):
        st = self.store.structure_get()['structure']
        entry = next(e for s in st['sections'] if s['key'] == 'work' for e in s['entries'] if e['bullets'])
        st['unassigned'].append(entry['bullets'].pop())
        self.store.structure_save(dict(structure=st, base_version=st['version'], confirm=True))
        out = self.act('tailor_export', job_id=self.job_id, version=1, formats=['md'])
        self.assertTrue(out['needs_structure'])
        self.assertEqual(out['code'], 'structure_changed')
        self.assertEqual(out['reason'], '简历结构在生成这一版之后改过，请重新生成')
        self.assertFalse((self.store.root / 'tailored').exists())
        self.act('tailor', job_id=self.job_id)
        self.assertTrue(self.act('tailor_export', job_id=self.job_id, version=2, formats=['md'])['ok'])

    def test_simultaneous_reviews_exports_and_generations_preserve_each_write(self):
        first, second = [e['id'] for e in self.doc['edits'][:2]]

        def simultaneous(actions):
            start = threading.Barrier(len(actions))

            def run(action):
                name, payload = action
                start.wait(timeout=5)
                return self.act(name, job_id=self.job_id, **payload)

            with ThreadPoolExecutor(max_workers=len(actions)) as pool:
                return list(pool.map(run, actions))

        simultaneous([('tailor_review', dict(version=1, reject=[eid])) for eid in (first, second)] +
                     [('tailor_export', dict(version=1, formats=['md']))] * 2)
        stored = self.act('tailor_get', job_id=self.job_id)['document']
        self.assertEqual([e['status'] for e in stored['edits'][:2]], ['rejected', 'rejected'])
        self.assertEqual(len(stored['exports']), 2)
        versions = simultaneous([('tailor', {}), ('tailor', {})])
        self.assertEqual(sorted(v['document']['version'] for v in versions), [2, 3])

    def test_export_updates_only_export_metadata_on_the_stored_document(self):
        export = rr.export_all

        def record_external_decision(*args, **kwargs):
            with self.store.tx() as c:
                doc = self.store._tailor_load(c, self.job_id, 1)
                doc['edits'][0]['status'] = 'rejected'
                self.store._tailor_save(c, doc)
            return export(*args, **kwargs)

        with patch.object(rr, 'export_all', side_effect=record_external_decision):
            self.act('tailor_export', job_id=self.job_id, version=1, formats=['md'])
        stored = self.act('tailor_get', job_id=self.job_id)['document']
        self.assertEqual(stored['edits'][0]['status'], 'rejected')
        self.assertEqual(len(stored['exports']), 1)
        self.assertEqual(stored['checks']['export'], 'pass')


if __name__ == '__main__':
    unittest.main()
