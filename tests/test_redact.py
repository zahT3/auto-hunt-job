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
                    'lin＠example.com', '13800138000@qq.com']:
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
                 'x\n微信/QQ：lin12345': 'x\n微信/QQ：[QQ号]'}
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


if __name__ == '__main__':
    unittest.main()
