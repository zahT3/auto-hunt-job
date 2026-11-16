"""Hard gates and soft flags for AI rewrites (design 6.3). Synthetic facts only."""
import unittest

from hunt.profile import claims

FACTS = {
    'f1': dict(text='2021.07-2023.03 在星河科技有限公司担任后端工程师，负责订单服务开发，使用 Python 和 Docker', version=1),
    'f2': dict(text='参与推荐系统项目，搭建数据看板，服务 3 个业务团队', version=1),
    'f3': dict(text='协助团队完成 k8s 集群日常维护，没有独立负责过线上发布', version=2),
    'f4': dict(text='获得校级二等奖学金；本科毕业于南湖大学计算机学院', version=1),
}


def edit(after, ids=('f1',), requirement=None):
    return dict(op='rephrase', fact_ids=[dict(id=i, version=FACTS[i]['version']) for i in ids], after=after,
                requirement=requirement or {})


def check(after, ids=('f1',), **kw):
    return claims.check_rephrase(edit(after, ids, kw.pop('requirement', None)), FACTS, **kw)


def codes(verdict):
    return {h['code'] for h in verdict['hard']}


class HardGates(unittest.TestCase):
    def rejects(self, after, code, ids=('f1',), **kw):
        verdict = check(after, ids, **kw)
        self.assertFalse(verdict['ok'], after)
        self.assertIn(code, codes(verdict), after)

    def test_new_number_or_quantity(self):
        for after in ('负责订单服务开发，日均处理 500 万订单', '负责订单服务开发，性能提升 30%', '负责订单服务开发，带 5 人小组',
                      '负责订单服务开发，节省三个月工期', '负责订单服务开发，团队排名第一名', '负责订单服务开发，覆盖 100+ 门店',
                      '负责订单服务开发，多年经验'):
            with self.subTest(after=after):
                self.rejects(after, 'new_number')

    def test_unit_change_is_new_quantity(self):
        self.rejects('服务 3 年业务团队', 'new_number', ids=('f2',))

    def test_new_tool(self):
        self.rejects('负责订单服务开发，使用 Redis 做缓存', 'new_term')
        self.rejects('负责订单服务开发，使用 Node.js 和 C++', 'new_term')
        self.rejects('负责订单服务开发，使用 PyTorch 训练模型', 'new_term')
        self.rejects('负责订单服务开发，使用机器学习方法', 'new_term')

    def test_new_employer(self):
        self.rejects('在云帆集团担任后端工程师', 'new_employer')
        self.rejects('在腾飞科技有限公司负责订单服务开发', 'new_employer')

    def test_new_school(self):
        self.rejects('毕业于北辰大学计算机学院', 'new_school', ids=('f4',))

    def test_new_project(self):
        self.rejects('参与星辰项目，搭建数据看板', 'new_project', ids=('f2',))
        self.rejects('参与《云图》系统，搭建数据看板', 'new_project', ids=('f2',))
        self.rejects('搭建数据中台平台', 'new_project', ids=('f2',))

    def test_new_title(self):
        self.rejects('担任后端架构师，负责订单服务开发', 'new_title')
        self.rejects('与产品经理一起负责订单服务开发', 'new_title')
        self.rejects('担任技术总监', 'new_title')

    def test_new_award(self):
        self.rejects('获得校级一等奖学金', 'new_award', ids=('f4',))
        self.rejects('获得优秀员工荣誉，负责订单服务开发', 'new_award')
        self.rejects('发表论文，负责订单服务开发', 'new_award')

    def test_new_certificate(self):
        self.rejects('负责订单服务开发，持有 PMP 证书', 'new_certificate')
        self.rejects('负责订单服务开发，通过英语六级', 'new_certificate')

    def test_new_contact(self):
        for after in ('负责订单服务开发，详见 https://example.com/a', '负责订单服务开发，联系 a@b.cn', '负责订单服务开发，电话 13812345678',
                      '负责订单服务开发，见 example.com'):
            with self.subTest(after=after):
                self.rejects(after, 'new_contact')

    def test_contact_rejected_even_when_a_fact_has_it(self):
        facts = {'c1': dict(text='邮箱 a@b.cn，负责订单服务开发', version=1)}
        verdict = claims.check_rephrase(dict(after='负责订单服务开发，邮箱 a@b.cn', fact_ids=['c1']), facts)
        self.assertIn('new_contact', codes(verdict))

    def test_empty_missing_and_stale(self):
        self.assertIn('empty_after', codes(check('  ')))
        self.assertIn('missing_fact', codes(claims.check_rephrase(dict(after='负责订单服务开发', fact_ids=['nope']), FACTS)))
        self.assertIn('missing_fact', codes(claims.check_rephrase(dict(after='负责订单服务开发', fact_ids=[]), FACTS)))
        stale = dict(after='负责订单服务开发', fact_ids=[dict(id='f1', version=9)])
        self.assertIn('stale_fact', codes(claims.check_rephrase(stale, FACTS)))

    def test_job_only_word(self):
        verdict = check('负责订单服务开发，具备用户增长经验', keywords=['用户增长', 'Python'])
        self.assertFalse(verdict['ok'])
        self.assertIn('job_only_term', codes(verdict))
        verdict = check('负责订单服务开发，熟悉 Kubernetes', keywords=['Kubernetes'])
        self.assertFalse(verdict['ok'])  # f1 has no Kubernetes or k8s

    def test_tool_equivalence_only_for_the_requirement_keyword(self):
        ok = check('协助团队完成 Kubernetes 集群日常维护', ids=('f3',), keywords=['Kubernetes'],
                   requirement=dict(value='Kubernetes'))
        self.assertTrue(ok['ok'], ok)
        other = check('协助团队完成 Kubernetes 集群日常维护', ids=('f3',), keywords=['Kubernetes'],
                      requirement=dict(value='Docker'))
        self.assertFalse(other['ok'])

    def test_verdict_names_the_offending_text(self):
        verdict = check('负责订单服务开发，性能提升 30%')
        self.assertTrue(any('30%' in h['text'] for h in verdict['hard']))


class Legitimate(unittest.TestCase):
    def accepts(self, after, ids=('f1',), **kw):
        verdict = check(after, ids, **kw)
        self.assertTrue(verdict['ok'], (after, verdict))
        return verdict

    def test_restructured_sentence(self):
        self.accepts('使用 Python 和 Docker，负责订单服务开发')

    def test_reordered_words_and_existing_numbers(self):
        self.accepts('服务 3 个业务团队，搭建数据看板，参与推荐系统项目', ids=('f2',))

    def test_merge_two_facts(self):
        self.accepts('在星河科技有限公司担任后端工程师，并参与推荐系统项目、搭建数据看板', ids=('f1', 'f2'))

    def test_split_into_lines(self):
        self.accepts('参与推荐系统项目\n搭建数据看板\n服务 3 个业务团队', ids=('f2',))

    def test_job_wording_for_supported_content(self):
        self.accepts('参与推荐系统项目，构建数据看板，支撑 3 个业务团队', ids=('f2',), keywords=['数据看板', '推荐系统'],
                     jd_lines=['构建数据看板并支撑业务'])

    def test_synonym_for_requirement_keyword(self):
        self.accepts('协助团队完成 Kubernetes 集群日常维护', ids=('f3',), requirement=dict(value='Kubernetes'),
                     keywords=['Kubernetes'])

    def test_generic_project_and_platform_words(self):
        self.accepts('参与该项目，搭建数据看板', ids=('f2',))

    def test_title_and_org_already_in_fact(self):
        self.accepts('担任后端工程师，就职于星河科技有限公司')


class SoftFlags(unittest.TestCase):
    def flagged(self, after, flag, ids, **kw):
        verdict = check(after, ids, **kw)
        self.assertTrue(verdict['ok'], verdict)  # flagged, not rejected
        self.assertIn(flag, verdict['flags'], after)

    def test_strength_up(self):
        self.flagged('主导推荐系统项目，搭建数据看板', 'strength_up', ('f2',))
        self.flagged('负责推荐系统项目，搭建数据看板', 'strength_up', ('f2',))
        self.flagged('负责 k8s 集群日常维护', 'strength_up', ('f3',))

    def test_strength_up_from_no_verb(self):
        facts = {'g1': dict(text='订单服务开发，使用 Python', version=1)}
        verdict = claims.check_rephrase(dict(after='负责订单服务开发，使用 Python', fact_ids=['g1']), facts)
        self.assertTrue(verdict['ok'])
        self.assertIn('strength_up', verdict['flags'])

    def test_same_or_lower_strength_not_flagged(self):
        self.assertNotIn('strength_up', check('参与推荐系统项目，搭建数据看板', ('f2',))['flags'])
        self.assertNotIn('strength_up', check('了解推荐系统项目，搭建数据看板', ('f2',))['flags'])

    def test_strength_up_follows_the_matching_fact_in_a_merge(self):
        self.flagged('负责订单服务开发；负责推荐系统项目', 'strength_up', ('f1', 'f2'))

    def test_allowed_swap_is_not_flagged(self):
        verdict = check('负责推荐系统项目，搭建数据看板', ('f2',), allowed_swaps=[('参与', '负责')])
        self.assertTrue(verdict['ok'])
        self.assertNotIn('strength_up', verdict['flags'])

    def test_negation_dropped(self):
        self.flagged('协助团队完成 k8s 集群日常维护，独立负责过线上发布', 'negation_dropped', ('f3',))
        self.flagged('协助团队完成 k8s 集群日常维护，负责线上发布', 'negation_dropped', ('f3',))

    def test_negation_kept_not_flagged(self):
        self.assertNotIn('negation_dropped', check('协助团队完成 k8s 集群日常维护，未独立负责过线上发布', ('f3',))['flags'])

    def test_ordinary_words_with_bu_are_not_negation(self):
        facts = {'n1': dict(text='不断优化订单服务，参与开发', version=1)}
        verdict = claims.check_rephrase(dict(after='参与开发，优化订单服务', fact_ids=['n1']), facts)
        self.assertNotIn('negation_dropped', verdict['flags'])

    def test_close_to_jd(self):
        line = '参与推荐系统项目并搭建数据看板服务业务团队的日常分析'
        verdict = check('参与推荐系统项目，搭建数据看板，服务业务团队的日常分析', ('f2',), jd_lines=[line])
        self.assertTrue(verdict['ok'])
        self.assertIn('close_to_jd', verdict['flags'])

    def test_short_overlap_with_jd_is_fine(self):
        verdict = check('参与推荐系统项目，搭建数据看板', ('f2',), jd_lines=['搭建数据看板'])
        self.assertNotIn('close_to_jd', verdict['flags'])

    def test_copy_of_the_fact_is_not_close_to_jd(self):
        text = FACTS['f2']['text']
        self.assertNotIn('close_to_jd', check(text, ('f2',), jd_lines=[text])['flags'])


if __name__ == '__main__':
    unittest.main()
