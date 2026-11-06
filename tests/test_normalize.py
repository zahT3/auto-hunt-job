"""hunt.search.normalize: salary text parsing (unreadable text never becomes 0) and the job-link dedup key."""
import unittest

from hunt.search.normalize import parse_amount, parse_salary, url_key


def ok(low, high, unit='month', months=None, currency='CNY'):
    return dict(status='ok', low=low, high=high, unit=unit, months=months, currency=currency)


class Salary(unittest.TestCase):
    def test_common_forms(self):
        cases = {
            '15-25K·14薪': ok(15000, 25000, months=14), '15-25k': ok(15000, 25000), '8-13k·13薪': ok(8000, 13000, months=13),
            '15K-25K': ok(15000, 25000), '2-3万': ok(20000, 30000), '1.5-2万/月': ok(15000, 20000), '8千-1.2万': ok(8000, 12000),
            '200-300元/天': ok(200, 300, 'day'), '150元/天': ok(150, 150, 'day'), '年薪30-50万': ok(300000, 500000, 'year'),
            '20-40万': ok(200000, 400000, 'year'), '30-50万/年': ok(300000, 500000, 'year'), '50元/小时': ok(50, 50, 'hour'),
            '15k以上': ok(15000, None), '1万以下': ok(None, 10000), 'CNY 18000–21000 MONTH': ok(18000, 21000),
            'USD ≥100000 YEAR': ok(100000, None, 'year', currency='USD'),
            '$150K – $200K • Offers Equity': ok(150000, 200000, 'year', currency='USD'), '１５－２５Ｋ': ok(15000, 25000),
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(parse_salary(text), expected)

    def test_negotiable_and_unreadable(self):
        for text in ('面议', '薪资面议', 'Negotiable'):
            self.assertEqual(parse_salary(text)['status'], 'negotiable')
        # 5-8万 could be per month or per year; 100-200 has no unit at all; the others are not salaries.
        for text in ('5-8万', '100-200', '待遇优厚', '5-3k', '1-2-3k', '10-15k·30薪'):
            with self.subTest(text=text):
                pay = parse_salary(text)
                self.assertEqual((pay['status'], pay['low'], pay['high']), ('unparsed', None, None))
        self.assertIsNone(parse_salary(None))
        self.assertIsNone(parse_salary('  '))

    def test_amounts_people_type(self):
        self.assertEqual([parse_amount(v) for v in (15000, '15k', '1.5万', '15000', ' 2W ', None, '')], [15000, 15000, 15000, 15000, 20000, None, None])
        for bad in ('很多', '-1', True, 10 ** 9):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                parse_amount(bad)



class LinkKey(unittest.TestCase):
    def test_links_to_one_job_share_a_key(self):
        same = ['https://careers.example.com/jobs/42', 'http://careers.example.com/jobs/42', 'https://www.careers.example.com/jobs/42',
                'https://CAREERS.example.com./jobs/42/', 'https://careers.example.com:443/jobs/42', 'https://careers.example.com/jobs/42/apply',
                'https://careers.example.com/jobs/42/apply/', 'https://careers.example.com/jobs/42?utm_source=x&utm_campaign=y',
                'https://careers.example.com/jobs/42?gclid=1&spm=a.b', 'https://careers.example.com/jobs/42#section']
        self.assertEqual({url_key(u) for u in same}, {'careers.example.com/jobs/42'})

    def test_what_still_tells_jobs_apart(self):
        self.assertEqual(url_key('https://jobs.example.com/view?id=2&utm_source=x&a=1'), 'jobs.example.com/view?a=1&id=2')  # sorted
        self.assertNotEqual(url_key('https://jobs.example.com/view?id=1'), url_key('https://jobs.example.com/view?id=2'))
        self.assertNotEqual(url_key('https://jobs.example.com/a'), url_key('https://jobs.example.com/A'))  # paths keep case
        self.assertEqual(url_key('https://example.com:8443/jobs/1'), 'example.com:8443/jobs/1')
        self.assertEqual(url_key('https://app.mokahr.com/social-recruitment/x/1#/job/abc'), 'app.mokahr.com/social-recruitment/x/1#/job/abc')
        self.assertEqual(url_key('https://www.liepin.com/job/1970.shtml?skId=a&d_sfrom=b'), 'liepin.com/job/1970.shtml')
        self.assertEqual(url_key('https://jobs.lever.co/acme/0f1e/apply'), 'jobs.lever.co/acme/0f1e')
        for bad in (None, '', 'ftp://example.com/x', 'careers.example.com/jobs/1', 'https://', 'https://[bad'):
            self.assertEqual(url_key(bad), '')


if __name__ == '__main__':
    unittest.main()
