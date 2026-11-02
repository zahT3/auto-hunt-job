"""One job's requirements, each matched to confirmed facts or marked missing or unknown. Rules only; nothing is sent.

Input is the job's structure (jd.py) and the confirmed, source-backed facts (orient.confirmed_facts): generated
materials, drafts and unconfirmed facts are never a source. Each row says which fact ids meet a requirement, or
`missing` (the facts speak to it and fall short, or never name a skill the job requires), or `unknown` (the facts
cannot settle it: soft skills, a degree or years the facts never state, location and remote preferences).
There is no score and no hiring probability: the rows are for the user to read.
"""
import re
import unicodedata

from . import jd

NOTICE = '只对照已确认的简历事实；不打分，也不估计录用概率'
WHY = dict(
    no_years='已确认事实里没有写工作年限', short_years='已确认事实里的年限都低于要求',
    no_degree='已确认事实里没有写学历', low_degree='已确认事实里的学历低于要求',
    no_skill='已确认事实里没有提到', soft='软技能很少写进简历事实，需要你自己判断',
    bonus_none='加分项里没有能对照的技能或证书', bonus_miss='已确认事实里没有提到这条加分项涉及的内容',
    condition='这是工作条件，对照你的求职条件，不对照简历事实')


def _norm(text):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(text))).casefold()


def _facts(facts):
    rows = []
    for fact in facts or []:
        if isinstance(fact, dict) and isinstance(fact.get('id'), str) and isinstance(fact.get('text'), str):
            text = unicodedata.normalize('NFKC', fact['text'])
            rows.append(dict(id=fact['id'], text=_norm(text), low=text.casefold(), phrases={_norm(p) for p in jd.phrases(text)},
                             years=[int(y) for y in jd.FACT_YEARS.findall(text)],
                             degrees=[d for d, words in jd.DEGREE_WORDS if any(w in text.lower() for w in words)]))
    return rows


def _naming(value, facts):
    want = _norm(value)
    if not want:
        return []
    if want.isascii():  # 'Go' must not match 'Google', nor 'SQL' 'MySQL'
        rx = re.compile(r'(?<![a-z0-9])%s(?![a-z0-9])' % r'\s*'.join(map(re.escape, want)))
        return [f['id'] for f in facts if want in f['phrases'] or rx.search(f['low'])]
    return [f['id'] for f in facts if want in f['phrases'] or want in f['text']]


def _row(kind, item, status, fact_ids=(), why=None, value=None):
    return dict(kind=kind, requirement=value if value is not None else item['value'], evidence=item['evidence'],
                status=status, fact_ids=list(fact_ids), why=why)


def _years(item, facts):
    need = item['value']['min']
    stated = [f for f in facts if f['years']]
    meets = [f['id'] for f in stated if max(f['years']) >= need]
    label = jd.label('years', item['value'])
    if meets:
        return _row('years', item, 'matched', meets, value=label)
    return _row('years', item, 'missing' if stated else 'unknown', why=WHY['short_years' if stated else 'no_years'], value=label)


def _education(item, facts):
    need = jd.DEGREES.index(item['value'])
    stated = [f for f in facts if f['degrees']]
    meets = [f['id'] for f in stated if max(jd.DEGREES.index(d) for d in f['degrees']) >= need]
    if meets:
        return _row('education', item, 'matched', meets)
    return _row('education', item, 'missing' if stated else 'unknown', why=WHY['low_degree' if stated else 'no_degree'])


def _bonus(item, facts):
    named = [p for p in jd.phrases(item['value']) if not re.fullmatch(r'\d+(?:-\d+)?年(?:以上)?', p)]
    hits = list(dict.fromkeys(i for p in named for i in _naming(p, facts)))
    if hits:
        return _row('bonus', item, 'matched', hits)
    return _row('bonus', item, 'missing' if named else 'unknown', why=WHY['bonus_miss' if named else 'bonus_none'])


def explain(structure, facts):
    """dict(rows, counts, notice). Rows follow the structure: years, education, hard and soft skills, bonus, conditions."""
    facts = _facts(facts)
    rows = []
    if structure.get('years'):
        rows.append(_years(structure['years'], facts))
    if structure.get('education'):
        rows.append(_education(structure['education'], facts))
    for item in structure.get('hard_skills') or []:
        hits = _naming(item['value'], facts)
        rows.append(_row('hard_skill', item, 'matched', hits) if hits else _row('hard_skill', item, 'missing', why=WHY['no_skill']))
    for item in structure.get('soft_skills') or []:
        hits = _naming(item['value'], facts)
        rows.append(_row('soft_skill', item, 'matched', hits) if hits else _row('soft_skill', item, 'unknown', why=WHY['soft']))
    rows += [_bonus(item, facts) for item in structure.get('bonus') or []]
    rows += [_row('location', item, 'unknown', why=WHY['condition']) for item in structure.get('location') or []]
    if structure.get('remote'):
        rows.append(_row('remote', structure['remote'], 'unknown', why=WHY['condition']))
    counts = {s: sum(r['status'] == s for r in rows) for s in ('matched', 'missing', 'unknown')}
    return dict(rows=rows, counts=counts, notice=NOTICE)
