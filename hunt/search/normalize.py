"""Canonical company and job-title forms: the job library links sources by them, and the benchmark matches with them."""
import re
import unicodedata

BRACKETS = re.compile(r'\([^()]*\)|\[[^\[\]]*\]|【[^【】]*】')


def _text(text):
    text = unicodedata.normalize('NFKC', str(text or '')).casefold()
    while True:
        stripped = BRACKETS.sub('', text)
        if stripped == text:
            return text
        text = stripped


def normalize_title(text):
    return ''.join(c for c in _text(text) if not c.isspace() and
                   not unicodedata.category(c).startswith('P') and c != '|')


def normalize_company(text):
    text = ''.join(c for c in _text(text) if not c.isspace())
    return re.sub(r'(?:股份有限公司|有限公司|集团)+$', '', text)


# Salary text as job sources write it: '15-25K·14薪', '2-3万', '200-300元/天', '年薪30-50万', 'CNY 18000–21000 MONTH',
# '$150K – $200K', '面议'. parse_salary() gives the amounts in whole currency units per pay unit; it never turns text it
# cannot read into 0.
SALARY_UNITS = ('month', 'day', 'year', 'hour')
_MONTHS = re.compile(r'[·•*x×]?\s*(\d{2})\s*薪')
_NUMBER = re.compile(r'(\d+(?:\.\d+)?)\s*(k|千|w|万)?')
_CURRENCIES = (('HKD', r'hkd|hk\$|港币|港元'), ('SGD', r'sgd|s\$|新币'), ('USD', r'usd|us\$|\$|美元'), ('EUR', r'eur|€|欧元'),
               ('GBP', r'gbp|£|英镑'), ('CNY', r'cny|rmb|人民币|¥|元'))
_UNIT_WORDS = (('year', r'年薪|/年|每年|per\s*year|yearly|annual|/yr|\byear\b|p\.a\.'),
               ('day', r'日薪|/天|/日|元/天|每天|per\s*day|daily|\bday\b'),
               ('hour', r'时薪|/小时|/时|每小时|per\s*hour|hourly|/hr|\bhour\b'),
               ('month', r'月薪|/月|每月|per\s*month|monthly|/mo\b|\bmonth\b'))
_AT_LEAST = re.compile(r'以上|起|\+|≥|>=|above|from|at\s*least')
_AT_MOST = re.compile(r'以下|≤|<=|up\s*to|below|under')


def parse_salary(value):
    """dict(status, low, high, unit, months, currency) for a salary text, or None when there is none.

    status is 'ok', 'negotiable' (面议) or 'unparsed'; only 'ok' carries amounts. low or high is None for an open
    end ('15k以上'). months is the stated pay months ('·14薪'), else None. Without a written unit, 'k' means per month
    (BOSS, 猎聘); '万' means per month up to 4万 and per year from 8万, and anything between is left unparsed;
    plain numbers from 1000 to 100000 mean per month; a foreign currency without a unit means per year."""
    if value is None: return None
    text = unicodedata.normalize('NFKC', str(value)).strip().casefold()
    if not text: return None
    failed = dict(status='unparsed', low=None, high=None, unit=None, months=None, currency=None)
    months = None
    found = _MONTHS.search(text)
    if found:
        months = int(found.group(1))
        if not 12 <= months <= 24: return failed
        text = text[:found.start()] + text[found.end():]
    numbers = _NUMBER.findall(text)
    if not numbers:
        return dict(failed, status='negotiable') if re.search(r'面议|面谈|negotiable|competitive', text) else failed
    if len(numbers) > 2: return failed
    currency = next((code for code, pattern in _CURRENCIES if re.search(pattern, text)), 'CNY')
    unit = next((name for name, pattern in _UNIT_WORDS if re.search(pattern, text)), None)
    scale = dict(k=1000, 千=1000, w=10000, 万=10000)
    last = numbers[-1][1]
    amounts = [float(n) * scale.get(suffix or last, 1) for n, suffix in numbers]
    if unit is None:
        biggest = max(amounts)
        # Postings in other currencies state yearly pay ('$150K – $200K' on Ashby); a Chinese 'k' is per month.
        if currency != 'CNY': unit = 'year' if biggest >= 10000 else None
        elif last in ('k', '千'): unit = 'month'
        elif last in ('w', '万'): unit = 'month' if biggest <= 40000 else 'year' if min(amounts) >= 80000 else None
        elif 1000 <= biggest <= 100000: unit = 'month'
        if unit is None: return failed
    if len(amounts) == 2: low, high = amounts
    elif _AT_LEAST.search(text): low, high = amounts[0], None
    elif _AT_MOST.search(text): low, high = None, amounts[0]
    else: low = high = amounts[0]
    if low is not None and high is not None and low > high: return failed
    whole = lambda x: None if x is None else int(round(x))
    return dict(status='ok', low=whole(low), high=whole(high), unit=unit, months=months, currency=currency)


def parse_amount(value):
    """A salary bound typed by a person: 15000, '15k', '1.5万' -> 15000; None for empty. ValueError for anything else."""
    if value is None: return None
    if isinstance(value, bool): raise ValueError('薪资须是数字，例如 15000、15k、1.5万')
    if isinstance(value, (int, float)): amount = float(value)
    else:
        text = unicodedata.normalize('NFKC', str(value)).strip().casefold()
        if not text: return None
        found = re.fullmatch(r'(\d+(?:\.\d+)?)\s*(k|千|w|万)?', text)
        if not found: raise ValueError('薪资须是数字，例如 15000、15k、1.5万')
        amount = float(found.group(1)) * dict(k=1000, 千=1000, w=10000, 万=10000).get(found.group(2), 1)
    if not 0 <= amount <= 10 ** 8: raise ValueError('薪资超出范围')
    return int(round(amount))
