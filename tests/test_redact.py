import unittest
from pathlib import Path

from hunt.redact import redact, redact_facts

ROOT = Path(__file__).resolve().parent.parent


class PhoneTests(unittest.TestCase):
    def test_common_spellings(self):
        for raw in ['13800138000', '138 0013 8000', '138-0013-8000', '138.0013.8000', '+86 138 0013 8000',
                    '+86-13800138000', '0086 13800138000', '(+86)13800138000', '86-13800138000',
                    '１３８００１３８０００', '１３８－００１３－８０００', '138 001 38000', '1380 013 8000']:
            with self.subTest(raw=raw):
                self.assertEqual(redact(f'x\n联系 {raw} 随时'), 'x\n联系 [手机号] 随时')

    def test_labelled_and_landline(self):
        self.assertEqual(redact('x\n手机：1234567'), 'x\n手机：[手机号]')
        self.assertEqual(redact('x\n办公 010-12345678 转'), 'x\n办公 [电话] 转')

    def test_numbers_in_normal_sentences_survive(self):
        text = ('2021.07—2024.06 在示例科技负责后端，年销售额 1200 万，同比增长 30%，团队 15 人，'
                '接口耗时降到 120ms，覆盖 13 个城市、1800 家门店，订单 2024 年达 138000 单。')
        self.assertEqual(redact('x\n' + text), 'x\n' + text)


class EmailTests(unittest.TestCase):
    def test_variants(self):
        for raw in ['lin@example.com', 'lin.shi+jobs@mail.example.co.uk', 'LIN_1@sub.a-b.example.invalid',
                    'lin＠example.com', '13800138000@mail.example.com']:
            with self.subTest(raw=raw):
                self.assertEqual(redact(f'x\n邮箱：{raw}。'), 'x\n邮箱：[邮箱]。')


class IdTests(unittest.TestCase):
    def test_eighteen_digits(self):
        for raw in ['110101199003071234', '11010119900307123X', '11010119900307123x', '110101 19900307 1234',
                    '１１０１０１１９９００３０７１２３４']:
            with self.subTest(raw=raw):
                self.assertEqual(redact(f'x\n证件 {raw} 完'), 'x\n证件 [身份证号] 完')

    def test_labelled_fifteen_digits(self):
        self.assertEqual(redact('x\n身份证号：110101900307123'), 'x\n身份证号：[身份证号]')

    def test_long_metric_is_not_an_id_or_phone(self):
        self.assertEqual(redact('x\n累计处理 12345678901234567890 条日志'), 'x\n累计处理 12345678901234567890 条日志')


class SocialTests(unittest.TestCase):
    def test_wechat_and_qq(self):
        cases = {'x\n微信：abc_12345': 'x\n微信：[微信号]', 'x\n微信号 lin12345': 'x\n微信号 [微信号]',
                 'x\nWeChat: lin_shi': 'x\nWeChat: [微信号]', 'x\nQQ 12345678': 'x\nQQ [QQ号]',
                 'x\nQQ：12345678': 'x\nQQ：[QQ号]', 'x\nQQ号：987654321': 'x\nQQ号：[QQ号]',
                 'x\n微信/QQ：lin12345': 'x\n微信/QQ：[微信号]',
                 'x\nQQ/微信：12345678': 'x\nQQ/微信：[QQ号]'}
        for raw, want in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(redact(raw), want)

    def test_product_mentions_survive(self):
        for text in ['负责微信小程序开发', '对接 WeChat Official Account 接口', '维护 QQ 音乐推荐服务']:
            self.assertEqual(redact('x\n' + text), 'x\n' + text)


class NameTests(unittest.TestCase):
    def test_name_field(self):
        cases = {'x\n姓名：林示例': 'x\n姓名：[姓名]', 'x\n姓 名: 林示例': 'x\n姓 名: [姓名]',
                 'x\nName: Lin Shili': 'x\nName: [姓名]', 'x\n姓名：林示例  性别：女': 'x\n姓名：[姓名]  性别：女',
                 'x\n基本信息 | 姓名：林示例 | 本科': 'x\n基本信息 | 姓名：[姓名] | 本科'}
        for raw, want in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(redact(raw), want)

    def test_company_name_field_is_kept(self):
        text = 'x\nCompany Name: Example Tech\n公司名称：示例科技'
        self.assertEqual(redact(text), text)

    def test_lone_name_line_on_top(self):
        self.assertEqual(redact('林示例\n软件工程师'), '[姓名]\n软件工程师')
        self.assertEqual(redact('\n  林示例  \n软件工程师'), '\n  [姓名]  \n软件工程师')
        self.assertEqual(redact('个人简历\n林示例\n软件工程师'), '个人简历\n[姓名]\n软件工程师')
        self.assertEqual(redact('欧阳示例\n软件工程师'), '[姓名]\n软件工程师')

    def test_top_line_that_is_not_a_name_is_kept(self):
        for first in ['教育背景', '工作经历', '示例科技有限公司', '软件开发工程师', '个人简历']:
            with self.subTest(first=first):
                self.assertEqual(redact(first + '\n软件工程师'), first + '\n软件工程师')

    def test_name_rule_only_for_first_line(self):
        self.assertEqual(redact('软件工程师\n林示例'), '软件工程师\n林示例')


class AddressTests(unittest.TestCase):
    def test_street_addresses(self):
        cases = {'北京市海淀区中关村大街1号院3号楼502室': '[地址]', '上海市浦东新区世纪大道100号': '[地址]',
                 '广东省深圳市南山区科苑路15号': '[地址]', '示例路88号3栋2单元501': '[地址]',
                 '阳光小区3栋2单元501室': '[地址]', '科技园２号楼１５０１室': '[地址]', '人民街7号A座': '[地址]',
                 '建国路８８号': '[地址]'}
        for raw, want in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(redact(f'x\n{raw}'), 'x\n' + want)

    def test_labelled_address(self):
        self.assertEqual(redact('x\n住址：示例镇三组12号'), 'x\n住址：[地址]')

    def test_city_only_and_ordinary_text_survive(self):
        for text in ['现居北京，期望城市：上海', '在示例科技负责路径规划与网络优化', '带领团队完成 3 个项目，覆盖 5 号线',
                     '获得第 2 名，高铁 G12 次，实验室 3 个']:
            self.assertEqual(redact('x\n' + text), 'x\n' + text)


class UrlTests(unittest.TestCase):
    def test_urls_and_profile_forms(self):
        cases = {'详见 https://example.com/lin/cv?x=1 谢谢': '详见 [链接] 谢谢', '主页 http://lin.example.invalid': '主页 [链接]',
                 'github.com/linshi': '[链接]', 'https://github.com/linshi/repo': '[链接]', 'linkedin.com/in/lin-shi-123': '[链接]',
                 'www.linkedin.com/in/lin-shi/': '[链接]', 'gitee.com/linshi': '[链接]', 'zhihu.com/people/lin-shi': '[链接]',
                 'linshi.github.io': '[链接]', 'linshi.github.io/blog': '[链接]',
                 '个人网站：linshi.example.invalid': '个人网站：[链接]', 'Blog: www.linshi.example.invalid/posts': 'Blog: [链接]',
                 '博客：linshi.cn': '博客：[链接]', 'Website：https://linshi.example.invalid': 'Website：[链接]'}
        for raw, want in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(redact('产品经理\n' + raw), '产品经理\n' + want)

    def test_brand_mentions_survive(self):
        for text in ['维护 GitHub 开源项目，star 3000', '使用 github.com 托管代码', '参与 LinkedIn 招聘产品运营', '博客系统开发']:
            self.assertEqual(redact('产品经理\n' + text), '产品经理\n' + text)

    def test_email_still_wins_over_domain(self):
        self.assertEqual(redact('产品经理\nlin@linshi.github.io'), '产品经理\n[邮箱]')


class LeadingNameTests(unittest.TestCase):
    def test_name_with_more_on_the_first_line(self):
        cases = {'张三 | 产品经理 | 13800138000': '[姓名] | 产品经理 | [手机号]',
                 '张三  男  28岁  本科': '[姓名]  男  [年龄]  本科', '张三/产品经理': '[姓名]/产品经理',
                 '张三·男': '[姓名]·男', '张三，产品经理': '[姓名]，产品经理', '欧阳示例、男': '[姓名]、男',
                 '个人简历\n张三 | 138-0013-8000': '个人简历\n[姓名] | [手机号]'}
        for raw, want in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(redact(raw), want)

    def test_heading_and_job_title_first_lines_are_kept(self):
        for first in ['产品经理', '后端工程师', '资深设计师 | 5年', '运营', '数据分析师', '教育背景 2017-2021', '工作经历：示例科技',
                      '求职意向 产品运营', '销售总监，上海', '技术顾问', 'Java开发']:
            with self.subTest(first=first):
                self.assertEqual(redact(first + '\n软件工程师'), first + '\n软件工程师')

    def test_field_label_first_line_is_not_a_name(self):
        for raw, want in {'电话 13800138000': '电话 [手机号]', '邮箱 a@b.com': '邮箱 [邮箱]', '手机：13800138000': '手机：[手机号]',
                          '微信 lin12345': '微信 [微信号]', '地址 示例路8号': '地址 [地址]'}.items():
            with self.subTest(raw=raw):
                self.assertEqual(redact(raw), want)

    def test_company_run_is_not_a_leading_name(self):
        self.assertEqual(redact('示例科技有限公司 | 产品经理'), '示例科技有限公司 | 产品经理')

    def test_provided_names_are_redacted_everywhere(self):
        text = '负责人林示例 与 Lin Shili 对接；林示例带队，林示 不变。'
        self.assertEqual(redact(text, names=['林示例', 'lin  shili']), '负责人[姓名] 与 [姓名] 对接；[姓名]带队，林示 不变。')
        self.assertEqual(redact(text, names=['林', '', ' ']), text)
        self.assertEqual(redact('姓名：林示例\n简历', names=['林示例']), '姓名：[姓名]\n简历')

    def test_provided_names_in_facts(self):
        facts = [dict(id='a', text='项目由林示例主导'), dict(id='b', text='增长 30%')]
        self.assertEqual(redact_facts(facts, names=['林示例']), [dict(id='a', text='项目由[姓名]主导'), dict(id='b', text='增长 30%')])
        self.assertEqual(redact_facts(facts)[0]['text'], '项目由林示例主导')


class BirthAgeTests(unittest.TestCase):
    def test_labelled_birth_and_age(self):
        cases = {'出生日期：1995-03-07': '出生日期：[出生日期]', '出生年月: 1995.03': '出生年月: [出生日期]',
                 '出生：1995年3月': '出生：[出生日期]', '生日：1995年3月7日  性别：女': '生日：[出生日期]  性别：女',
                 'Date of Birth: 1995/03/07': 'Date of Birth: [出生日期]', 'DOB: 1995-03': 'DOB: [出生日期]',
                 '出生日期：１９９５年３月': '出生日期：[出生日期]',
                 '年龄：28': '年龄：[年龄]', '年龄：28岁': '年龄：[年龄]', 'Age: 28': 'Age: [年龄]'}
        for raw, want in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(redact('产品经理\n' + raw), '产品经理\n' + want)

    def test_prose_forms(self):
        cases = {'1995年3月出生': '[出生日期]', '1995年出生，本科': '[出生日期]，本科', '出生于1995年3月': '[出生日期]',
                 '1995-03-07 出生': '[出生日期]', '男，28岁，已婚': '男，[年龄]，已婚'}
        for raw, want in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(redact('产品经理\n' + raw), '产品经理\n' + want)

    def test_other_dates_and_ages_survive(self):
        text = '2020年3月入职示例科技，2021年毕业，出生地：北京，带 3 岁以下儿童产品线，2020.03—2022.06，满 5 年'
        self.assertEqual(redact('产品经理\n' + text), '产品经理\n' + text)


class AddressMoreTests(unittest.TestCase):
    def test_numbers_with_prefix_letter(self):
        for raw in ['北京市海淀区知春路甲48号', '朝阳区建国路乙12号院', '示例路A8号']:
            with self.subTest(raw=raw):
                self.assertEqual(redact('产品经理\n' + raw), '产品经理\n[地址]')

    def test_company_text_before_a_known_city_survives(self):
        cases = {'在腾讯科技深圳市南山区科苑路15号任职': '在腾讯科技[地址]任职',
                 '就职于示例网络科技北京市海淀区中关村大街1号': '就职于示例网络科技[地址]',
                 '阿里巴巴杭州市余杭区文一西路969号': '阿里巴巴[地址]',
                 '腾讯广东省深圳市南山区科苑路15号': '腾讯[地址]'}
        for raw, want in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(redact('产品经理\n' + raw), '产品经理\n' + want)


class CardAndOldIdTests(unittest.TestCase):
    def test_bank_cards(self):
        for raw in ['4111111111111111', '4111 1111 1111 1111', '6222020200112233446', '6222 0202 0011 2233 446',
                    '4111-1111-1111-1111', '４１１１１１１１１１１１１１１１']:
            with self.subTest(raw=raw):
                self.assertEqual(redact(f'产品经理\n卡 {raw} 完'), '产品经理\n卡 [银行卡号] 完')

    def test_labelled_card_without_luhn(self):
        self.assertEqual(redact('产品经理\n银行卡号：6222 0202 0011 2233 445'), '产品经理\n银行卡号：[银行卡号]')

    def test_non_luhn_long_numbers_survive(self):
        text = '处理 4111111111111112 条记录，流水 1234567890123456'
        self.assertEqual(redact('产品经理\n' + text), '产品经理\n' + text)

    def test_fifteen_digit_ids(self):
        self.assertEqual(redact('产品经理\n证 110101900307123 完'), '产品经理\n证 [身份证号] 完')
        self.assertEqual(redact('产品经理\n证 110101900307123'), '产品经理\n证 [身份证号]')
        text = '编号 123456789012345 共计'  # month 90 at positions 9-10: not a date
        self.assertEqual(redact('产品经理\n' + text), '产品经理\n' + text)


class TopLineInteractionTests(unittest.TestCase):
    def test_contact_on_the_very_first_line(self):
        self.assertEqual(redact('13800138000\n软件工程师'), '[手机号]\n软件工程师')
        self.assertEqual(redact('a@b.com\n软件工程师'), '[邮箱]\n软件工程师')

    def test_name_field_and_top_line_together(self):
        self.assertEqual(redact('林示例\n姓名：林示例\n邮箱：a@b.com'), '[姓名]\n姓名：[姓名]\n邮箱：[邮箱]')

    def test_top_line_name_then_address_line(self):
        self.assertEqual(redact('林示例\n示例路88号'), '[姓名]\n[地址]')

    def test_top_line_that_is_a_field_is_not_double_redacted(self):
        self.assertEqual(redact('姓名：林示例\n软件工程师'), '姓名：[姓名]\n软件工程师')


class SampleTests(unittest.TestCase):
    def test_synthetic_resume_keeps_substance(self):
        text = (ROOT / 'examples' / 'resume.synthetic.txt').read_text(encoding='utf-8')
        out = redact(text)
        self.assertIn('姓名：[姓名]', out)
        self.assertIn('邮箱：[邮箱]', out)
        for gone in ['林示例', 'candidate@example.invalid']:
            self.assertNotIn(gone, out)
        for kept in ['示例科技', '软件开发工程师', 'Python、SQL、FastAPI', '2021.07—2024.06', '120条', '3年', '示例大学']:
            self.assertIn(kept, out)

    def test_idempotent(self):
        text = '林示例\n手机 138-0013-8000\n邮箱 a@b.com\n微信：abc12345\n住址 示例路8号'
        self.assertEqual(redact(redact(text)), redact(text))


class FactsTests(unittest.TestCase):
    def fact(self, i, text):
        return dict(id=f'f{i}', text=text, status='pending', source=dict(reference='x#1'), version=1, tags=['t'])

    def test_keeps_only_id_and_text(self):
        out = redact_facts([self.fact(1, '电话 13800138000'), self.fact(2, '增长 30%')])
        self.assertEqual(out, [dict(id='f1', text='电话 [手机号]'), dict(id='f2', text='增长 30%')])

    def test_name_line_only_for_first_fact(self):
        facts = [self.fact(1, '个人简历'), self.fact(2, '林示例'), self.fact(3, '教育背景'), self.fact(4, '示例科技')]
        self.assertEqual([f['text'] for f in redact_facts(facts)], ['个人简历', '[姓名]', '教育背景', '示例科技'])

    def test_short_facts_after_the_first_are_not_names(self):
        facts = [self.fact(1, '软件工程师'), self.fact(2, '林示例')]
        self.assertEqual([f['text'] for f in redact_facts(facts)], ['软件工程师', '林示例'])

    def test_missing_text_and_input_unchanged(self):
        facts = [dict(id='a'), self.fact(2, 'a@b.com')]
        before = repr(facts)
        self.assertEqual(redact_facts(facts)[0], dict(id='a', text=''))
        self.assertEqual(repr(facts), before)



class SpacedNameTests(unittest.TestCase):
    def test_spaced_leading_name_is_redacted_and_reused_later(self):
        from hunt.redact import redact_facts
        facts = [dict(id='a', text='林 示 例'), dict(id='b', text='University of Example · MSc'),
                 dict(id='c', text='作品集：林示例的设计作品'), dict(id='d', text='联系人 林 示 例')]
        out = [f['text'] for f in redact_facts(facts)]
        self.assertEqual(out[0], '[姓名]')
        self.assertEqual(out[1], 'University of Example · MSc')
        self.assertNotIn('林示例', out[2]); self.assertNotIn('林 示 例', out[3])

    def test_spaced_heading_is_not_taken_for_a_name(self):
        from hunt.redact import redact_facts
        out = [f['text'] for f in redact_facts([dict(id='a', text='个 人 简 历'), dict(id='b', text='林 示 例 | 产品经理')])]
        self.assertEqual(out[0], '个 人 简 历')
        self.assertTrue(out[1].startswith('[姓名]'), out[1])
        self.assertIn('产品经理', out[1])

    def test_known_name_matches_with_spaces_between_characters(self):
        from hunt.redact import redact
        self.assertEqual(redact('负责人：林 示 例，组长 林示例', names=['林示例']).count('[姓名]'), 2)


if __name__ == '__main__':
    unittest.main()
