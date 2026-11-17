"""Fact check for a model's rewrite of résumé lines (design 6.3). Rules only; nothing is sent anywhere.

A rewrite may change the sentence freely, but every claim it makes must already be in the confirmed facts it cites.
Hard gates (a rewrite that trips one is rejected and the review page offers no way to accept it): a number or
quantity, tool or technology, employer, school, project name, job title, award, certificate or contact detail that the
cited facts do not contain, and a job keyword the facts do not support. Soft flags (the rewrite stays, marked red,
default pending): `strength_up` (参与 -> 负责 -> 主导), `negation_dropped`, `close_to_jd`.

The check is heuristic. A Chinese tool name that is on no list, a project name with no suffix, or a changed cause or
scope slips through; the review page is the last line of defence, not this module.
"""
import re
import unicodedata

from .profile import _SKILLS

# Groups of words that really mean the same thing. A later task may pass its own list through `synonyms`.
SYNONYMS = (('Kubernetes', 'k8s'), ('PostgreSQL', 'Postgres'), ('Go', 'Golang'), ('自然语言处理', 'NLP'),
            ('大模型', 'LLM', '大语言模型'), ('用户研究', '用研'))
CHINESE_TERMS = ('机器学习', '深度学习', '强化学习', '自然语言处理', '计算机视觉', '容器编排', '微服务', '大数据', '数据仓库',
                 '数据挖掘', '知识图谱', '智能合约', '爬虫', '数据可视化', '用户画像', 'a/b测试', '原型设计', '需求分析',
                 '项目管理', '新媒体运营', '财务分析')
STRENGTH = (('了解', 0), ('参与', 1), ('协助', 2), ('主要负责', 3), ('负责', 3), ('独立负责', 4), ('全面负责', 4),
            ('主导', 4), ('牵头', 4), ('带领', 4))
NEGATION = re.compile(r'没有|没|不|未|无|非|缺乏|仅')
NOT_NEGATION = re.compile(r'不断|不仅|不同|不少|不限|不错|不论|不久|不得不|无缝|无线|无人|无论|非常|未来|无锡')
CLOSE_RUN = 12
STOP_WORDS = {'and', 'or', 'the', 'of', 'to', 'for', 'with', 'in', 'on', 'a', 'an', 'is', 'at', 'by', 'as'}

# Words that may stand in front of a name suffix without being part of the name ("参与该项目", "担任后端工程师").
GENERIC = tuple(sorted(
    ('参与', '负责', '主导', '牵头', '带领', '协助', '推动', '完成', '开发', '搭建', '构建', '上线', '维护', '优化', '管理', '支持',
     '从事', '落地', '交付', '设计', '实现', '获得', '荣获', '取得', '获', '担任', '作为', '毕业于', '就读于', '任职于', '就职于',
     '该', '本', '此', '各', '多个', '一个', '相关', '核心', '重点', '大型', '小型', '内部', '整个', '整体', '所有', '其他',
     '上述', '新', '个', '多', '跨', '多方', '自研'), key=len, reverse=True))
BREAK = re.compile(r'[^一-鿿A-Za-z0-9]|[的和与及并在对把将从向给由]')

ORG = {'有限责任公司': 'new_employer', '股份有限公司': 'new_employer', '有限公司': 'new_employer', '集团': 'new_employer',
       '公司': 'new_employer', '研究院': 'new_employer', '研究所': 'new_employer', '实验室': 'new_employer',
       '大学': 'new_school', '学院': 'new_school', '中学': 'new_school', '学校': 'new_school',
       '项目': 'new_project', '平台': 'new_project'}
TITLES = ('工程师', '经理', '总监', '主管', '专员', '负责人', '架构师', '设计师', '分析师', '顾问', '实习生', '助理', '总裁')
AWARDS = ('奖学金', '奖项', '获奖', '荣誉', '专利', '证书', '认证', '论文', '奖')
CERTS = ('PMP', 'CPA', 'CFA', 'ACCA', 'CISSP', 'IELTS', 'TOEFL', 'GMAT', 'CET-4', 'CET-6', 'CET4', 'CET6', '六级', '四级', '专四',
         '专八', '雅思', '托福', '软考', '法考', '司考', '注册会计师', '教师资格', '法律职业资格')

_ORG = re.compile('|'.join(sorted(ORG, key=len, reverse=True)))
_TITLE = re.compile('|'.join(sorted(TITLES, key=len, reverse=True)).replace('负责人', '负责人(?!员)'))
_AWARD = re.compile('|'.join(sorted(AWARDS, key=len, reverse=True)))
_CERT = re.compile('|'.join(sorted(map(re.escape, CERTS), key=len, reverse=True)), re.I)
_QUOTES = (re.compile(r'《(.{1,30}?)》'), re.compile(r'“(.{1,30}?)”'), re.compile(r'「(.{1,30}?)」'), re.compile(r'"(.{1,30}?)"'))
_LATIN = re.compile(r'[A-Za-z][A-Za-z0-9]*(?:[+#]+|[.\-][A-Za-z0-9+#]+)*')
UNITS = r'(?:%|倍|万|亿|个月|年|人|家|次|名|项|个|天|周|月|小时|\+)'
_DIGITS = re.compile(r'(?<![A-Za-z])(?:top\s*)?(\d+(?:\.\d+)?)\s*(' + UNITS + r')?', re.I)
_CN_NUM = re.compile(r'百分之[零一二三四五六七八九十百]+|第[一二三四五六七八九十百\d]+名'
                     r'|[零〇一二两三四五六七八九十百千万亿]+(?:个月|年|人|家|次|倍|万|亿|名|项|个|套|成)'
                     r'|(?:多|数|几|十余|百余|千余)(?:年|个月|万|亿|倍|次)')
_CN_EXEMPT = {'一个', '一项', '一套', '两个', '两项'}
_URL = re.compile(r'https?://|www\.|[\w.+-]+@[\w-]+\.[\w.]+|\b[a-z0-9-]+\.(?:com|cn|io|net|org|dev|app|me|co)\b', re.I)
_PHONE = re.compile(r'(?<!\d)1[3-9]\d{9}(?!\d)|(?<!\d)\d{3,4}-\d{7,8}(?!\d)')
_CLAUSE = re.compile(r'[，。；;,\n、]')
_SKILL_RES = {label: re.compile(pattern, re.I) for label, pattern in _SKILLS.items()}
_STRENGTH_RE = re.compile('|'.join(sorted((w for w, _ in STRENGTH), key=len, reverse=True)))
_LEVEL = dict(STRENGTH)


def _fold(text):
    return unicodedata.normalize('NFKC', str(text)).casefold()


def _tight(text):
    return re.sub(r'\s+', '', _fold(text))


def _punctuationless(text):
    return re.sub(r'[\W_]+', '', _fold(text))


def _group_of(term, synonyms):
    key = _fold(term)
    return next((g for g in synonyms if any(_fold(m) == key for m in g)), ())


class _Facts:
    """The cited facts as one searchable text, with the tokens the checks compare against."""
    def __init__(self, texts):
        self.texts = texts
        self.text = _tight('\n'.join(texts))
        self.raw = _fold('\n'.join(texts))
        self.latin = {_trim(t) for t in _LATIN.findall(self.raw)}
        self.numbers = set()
        self.measured = set()
        for m in _DIGITS.finditer(self.raw):
            self.numbers.update([m.group(1)] + m.group(1).split('.'))
            if m.group(2):
                self.measured.add(m.group(1) + m.group(2))
        self.cn_numbers = {m.group(0) for m in _CN_NUM.finditer(self.text)}

    def has(self, term):
        t = _tight(term)
        if not t:
            return False
        if t.isascii():
            return bool(re.search(r'(?<![a-z0-9])%s(?![a-z0-9])' % re.escape(t), self.raw.replace(' ', '')) or _trim(t) in self.latin)
        return t in self.text

    def has_or_equivalent(self, term, synonyms):
        return self.has(term) or any(self.has(m) for m in _group_of(term, synonyms))


def _trim(token):
    return token.rstrip('.-').casefold()


def _name_before(text, start, floor):
    """The name-like stretch right before a suffix at `start`, without leading verbs and filler words."""
    chunk = BREAK.split(text[max(floor, start - 8):start])[-1]
    cut = True
    while cut and chunk:
        cut = False
        for word in GENERIC:
            if chunk.startswith(word):
                chunk, cut = chunk[len(word):], True
                break
    return chunk


def _hard(code, text):
    return dict(code=code, text=text)


def _numbers(after, facts):
    out = []
    for m in _DIGITS.finditer(after):
        num, unit = m.group(1), m.group(2) or ''
        if unit and (num + unit) in facts.measured:
            continue
        if unit == '年' and re.fullmatch(r'(?:19|20)\d\d', num) and num in facts.numbers:
            continue  # the same year, written 2021.03 in the fact
        if not unit and num in facts.numbers:
            continue
        out.append(_hard('new_number', re.sub(r'\s+', '', m.group(0))))
    for m in _CN_NUM.finditer(after):
        token = m.group(0)
        if token not in _CN_EXEMPT and token not in facts.cn_numbers:
            out.append(_hard('new_number', token))
    return out


def _terms(after, facts, requirement, synonyms):
    out, want = [], _fold((requirement or {}).get('value') or '')
    for raw in _LATIN.findall(after):
        term = _trim(raw)
        if len(term) < 1 or term in STOP_WORDS or term in facts.latin:
            continue
        equal = _group_of(term, synonyms)
        supported = any(_fold(m) in facts.latin or facts.has(m) for m in equal if _fold(m) != term)
        asked = bool(want) and (want == term or want in {_fold(m) for m in equal})
        if not (supported and asked):
            out.append(_hard('new_term', raw))
    for label, pattern in _SKILL_RES.items():
        for m in pattern.finditer(after):
            if m.group(0).isascii():
                continue  # Latin skill words are the tokens above
            if not pattern.search(facts.raw) and not facts.has_or_equivalent(m.group(0), synonyms):
                out.append(_hard('new_term', m.group(0)))
    for word in CHINESE_TERMS:
        if _tight(word) in _tight(after) and not facts.has_or_equivalent(word, synonyms):
            out.append(_hard('new_term', word))
    return out


def _named(after, facts):
    out, prev_end, folded = [], 0, _fold(after)
    for m in _ORG.finditer(folded):
        name = _name_before(folded, m.start(), prev_end)
        prev_end = m.end()
        if (name and name.replace(' ', '') not in facts.text) or m.group(0) not in facts.text:
            out.append(_hard(ORG[m.group(0)], name + m.group(0)))
    for pattern in _QUOTES:
        for m in pattern.finditer(after):
            if _tight(m.group(1)) not in facts.text:
                out.append(_hard('new_project', m.group(1)))
    return out


def _titles(after, facts):
    out, folded, prev_end = [], _fold(after), 0
    for m in _TITLE.finditer(folded):
        name = _name_before(folded, m.start(), prev_end)
        prev_end = m.end()
        if (name + m.group(0)) not in facts.text and not (not name and m.group(0) in facts.text):
            out.append(_hard('new_title', name + m.group(0)))
    return out


def _awards(after, facts):
    out, folded, prev_end = [], _fold(after), 0
    for m in _AWARD.finditer(folded):
        name = _name_before(folded, m.start(), prev_end)
        prev_end = m.end()
        if m.group(0) not in facts.text or (name and name not in facts.text):
            out.append(_hard('new_award', name + m.group(0)))
    for m in _CERT.finditer(after):
        if not facts.has(m.group(0)):
            out.append(_hard('new_certificate', m.group(0)))
    return out


def _contacts(after):
    return [_hard('new_contact', m.group(0)) for pattern in (_URL, _PHONE) for m in pattern.finditer(_fold(after))]


def _job_only(after, facts, keywords, synonyms):
    out, folded, tight = [], _fold(after), _tight(after)
    for kw in keywords or ():
        key = _tight(kw)
        if not key:
            continue
        present = (re.search(r'(?<![a-z0-9])%s(?![a-z0-9])' % re.escape(key), folded.replace(' ', '')) if key.isascii()
                   else key in tight)
        if present and not facts.has_or_equivalent(kw, synonyms):
            out.append(_hard('job_only_term', str(kw)))
    return out


def _level(clause):
    """(verb, level) of the first strength verb in a clause, or None when it has none or the verb is negated."""
    m = _STRENGTH_RE.search(clause)
    if not m or NEGATION.search(NOT_NEGATION.sub('', clause[:m.start()])):
        return None
    return m.group(0), _LEVEL[m.group(0)]


def _bigrams(clause):
    tight = re.sub(_STRENGTH_RE, '', _punctuationless(clause))
    return {tight[i:i + 2] for i in range(len(tight) - 1)}


def _strength(after, fact_texts, swaps):
    pool = []
    for text in fact_texts:
        for clause in _CLAUSE.split(_fold(text)):
            if clause.strip():
                pool.append((_bigrams(clause), _level(clause)))
    fallback = max((lv for _, lv in pool if lv), key=lambda lv: lv[1], default=None)
    allowed = {(_fold(a), _fold(b)) for a, b in swaps or ()}
    for clause in _CLAUSE.split(_fold(after)):
        mine = _level(clause)
        if not mine:
            continue
        grams = _bigrams(clause)
        best = max(pool, key=lambda p: len(p[0] & grams), default=None)
        base = best[1] if best and len(best[0] & grams) >= 2 else fallback
        if (base is None or mine[1] > base[1]) and not (base and (base[0], mine[0]) in allowed):
            return True
    return False


def _negations(text):
    return len(NEGATION.findall(NOT_NEGATION.sub('', _fold(text))))


def _close_to_jd(after, fact_text, jd_lines):
    mine = _punctuationless(after)
    lines = [_punctuationless(line) for line in jd_lines or ()]
    for i in range(len(mine) - CLOSE_RUN + 1):
        window = mine[i:i + CLOSE_RUN]
        if any(window in line for line in lines) and window not in _punctuationless(fact_text):
            return True
    return False


def check_rephrase(edit, facts, jd_lines=(), keywords=(), synonyms=SYNONYMS, allowed_swaps=()):
    """Check one rephrase edit against the facts it cites.

    edit: dict(after=str, fact_ids=[id | dict(id, version)], requirement=dict(value=...)).
    facts: {fact id: dict(text, version?)}; only confirmed facts belong in it.
    jd_lines: the job's own lines (for close_to_jd). keywords: the job's keyword values (job-only words).
    Returns dict(ok, hard=[dict(code, text)], flags=[...]); ok is False when any hard gate tripped.
    """
    after = edit.get('after')
    if isinstance(after, list):
        after = '\n'.join(str(x) for x in after)
    after = unicodedata.normalize('NFKC', after).strip() if isinstance(after, str) else ''
    hard, texts = [], []
    if not after:
        hard.append(_hard('empty_after', ''))
    refs = edit.get('fact_ids') if isinstance(edit.get('fact_ids'), list) else []
    for ref in refs:
        ident, version = (ref.get('id'), ref.get('version')) if isinstance(ref, dict) else (ref, None)
        fact = facts.get(ident) if isinstance(facts, dict) else None
        if not isinstance(fact, dict) or not isinstance(fact.get('text'), str):
            hard.append(_hard('missing_fact', str(ident)))
        elif version is not None and fact.get('version') is not None and fact['version'] != version:
            hard.append(_hard('stale_fact', str(ident)))
        else:
            texts.append(fact['text'])
    if not refs:
        hard.append(_hard('missing_fact', ''))
    if not after or not texts or any(h['code'] in ('missing_fact', 'stale_fact') for h in hard):
        return dict(ok=False, hard=hard, flags=[])
    cited = _Facts([unicodedata.normalize('NFKC', t) for t in texts])
    for found in (_numbers(after, cited), _terms(after, cited, edit.get('requirement'), synonyms), _named(after, cited),
                  _titles(after, cited), _awards(after, cited), _contacts(after), _job_only(after, cited, keywords, synonyms)):
        hard += found
    seen, unique = set(), []
    for h in hard:
        key = (h['code'], _fold(h['text']))
        if key not in seen:
            seen.add(key)
            unique.append(h)
    flags = []
    if _strength(after, texts, allowed_swaps):
        flags.append('strength_up')
    if _negations(after) < _negations('\n'.join(texts)):
        flags.append('negation_dropped')
    if _close_to_jd(after, '\n'.join(texts), jd_lines):
        flags.append('close_to_jd')
    return dict(ok=not unique, hard=unique, flags=flags)
