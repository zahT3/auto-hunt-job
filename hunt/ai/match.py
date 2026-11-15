"""One job seen the way an applicant tracking system screens it, in three stages. Rules only; nothing is sent.

1. hard: knock-out conditions (education, years, languages, certificates and work permits, location, remote), each
   met / not_met / unknown with the JD quote and the fact ids (or the user's search conditions for location).
2. keywords: every skill keyword the JD names, and whether the confirmed facts use the same word (explicit), only a
   near wording (related: you may have it, but a keyword filter will not see it), or neither (absent).
3. evidence: each duty or outcome the JD lists (岗位职责) and the confirmed facts that back it. Hard conditions and keywords
   are steps 1 and 2 and are not repeated; a JD without a duties section leaves this stage empty.

Input is the job's structure (jd.py), the confirmed, source-backed facts (orient.confirmed_facts: drafts, generated
materials and unconfirmed facts never count) and optionally the user's orientation conditions. Rows keep the JD's
order. There is no total, no ranking and no prediction of the screening outcome.
"""
import re
import unicodedata

from . import jd
from ..search.query import expanded_terms

NOTICE = '按招聘系统的筛选顺序对照已确认的简历事实；不打分、不排序，也不预测筛选结果'
# Near wordings an ATS keyword filter would not treat as the JD's word. Each group is symmetric.
RELATED = (('Kubernetes', 'k8s', '容器编排'), ('PostgreSQL', 'Postgres'), ('Go', 'Golang'), ('JavaScript', 'JS', 'TypeScript'),
           ('机器学习', 'machine learning', '深度学习'), ('大模型', 'LLM', '大语言模型', 'GPT'), ('自然语言处理', 'NLP'),
           ('计算机视觉', 'CV', '图像识别'), ('数据分析', 'SQL', 'Excel', 'Tableau', 'BI', '报表'), ('需求分析', '需求文档', 'PRD'),
           ('产品设计', '原型设计', 'Axure', '原型'), ('用户研究', '用研', '用户访谈', '调研'), ('项目管理', '项目负责', 'PMP', '项目推进'),
           ('沟通能力', '沟通', '协调', '对接'), ('团队协作', '团队', '协作', '合作'), ('学习能力', '自学', '快速学习'),
           ('抗压能力', '压力', '高强度'), ('逻辑思维', '逻辑', '分析能力'), ('新媒体运营', '公众号', '小红书', '抖音'),
           ('财务分析', '财务报表', '预算'), ('招聘', '面试', '人才招聘'))
ENGLISH_STRONG = ('六级', 'cet-6', 'cet6', '专八', '专四', '雅思', 'ielts', '托福', 'toefl', '流利', 'fluent', '英语工作', '海外', '英文工作')
ENGLISH_WEAK = ('四级', 'cet-4', 'cet4')
WHY = dict(
    no_years='已确认事实里没有写工作年限', short_years='已确认事实里的年限都低于要求',
    no_degree='已确认事实里没有写学历', low_degree='已确认事实里的学历低于要求',
    no_language='已确认事实里没有写这门语言的水平', low_language='已确认事实里只有英语四级',
    no_certificate='已确认事实里没有提到；如果持有，请补充并确认',
    no_cities='你还没有填写意向城市', other_city='不在你填的意向城市里', remote='是否接受远程看你的求职条件，这里只列出岗位的说法',
    explicit='简历事实里有原词', related='简历事实里只有相近表述，关键词筛选可能认不出；如果确有这项能力，可改用岗位原词',
    absent='简历事实里没有；如果你有这项能力，先补充并确认事实，否则就是缺口',
    no_duties='原文里没有找到"岗位职责"或"工作内容"小节，这一步没有可对照的条目；硬条件和关键词见前两步')
DUTY_LEAD = re.compile(r'^(?:负责|参与|协助|主要负责|全面负责|独立负责|带领|牵头|完成|承担|推动|管理|维护|开展|制定|组织|配合|支持|\d+[.、)）])+')
DUTY_GRAM = 3  # one shared 3-character run that is not filler makes a fact "close" to a duty
FILLER = re.compile(r'[的与和及等并或在对为把将]|工作|项目|公司|相关|团队|业务|产品|系统|开发|设计|负责|参与|经验|能力|管理')


def _fold(text):
    return unicodedata.normalize('NFKC', str(text)).casefold()


def _tight(text):
    return re.sub(r'\s+', '', _fold(text))


def _facts(facts):
    rows = []
    for fact in facts or []:
        if isinstance(fact, dict) and isinstance(fact.get('id'), str) and isinstance(fact.get('text'), str):
            text = unicodedata.normalize('NFKC', fact['text'])
            rows.append(dict(id=fact['id'], low=_fold(text), tight=_tight(text), years=[int(y) for y in jd.FACT_YEARS.findall(text)],
                             degrees=[d for d, words in jd.DEGREE_WORDS if any(w in text.lower() for w in words)]))
    return rows


def _says(word, fact):
    want = _tight(word)
    if not want:
        return False
    if want.isascii():  # 'Go' must not match 'Google', nor 'SQL' 'MySQL'
        return bool(re.search(r'(?<![a-z0-9])%s(?![a-z0-9])' % r'\s*'.join(map(re.escape, want)), fact['low']))
    return want in fact['tight']


def _naming(word, facts):
    return [f['id'] for f in facts if _says(word, f)]


def _near(word):
    """Near wordings of one keyword: the RELATED groups plus the search layer's recall aliases."""
    words = [w for group in RELATED if any(_tight(w) == _tight(word) for w in group) for w in group]
    words += expanded_terms([word])[word]
    return [w for w in dict.fromkeys(words) if _tight(w) != _tight(word)]


def _hard(kind, requirement, item, status, fact_ids=(), why=None, basis='facts'):
    return dict(kind=kind, requirement=requirement, jd_evidence=item['evidence'], status=status, fact_ids=list(fact_ids),
                basis=basis, why=why)


def _years(item, facts):
    need, label = item['value']['min'], jd.label('years', item['value'])
    stated = [f for f in facts if f['years']]
    meets = [f['id'] for f in stated if max(f['years']) >= need]
    if meets:
        return _hard('years', label, item, 'met', meets)
    return _hard('years', label, item, 'not_met' if stated else 'unknown', why=WHY['short_years' if stated else 'no_years'])


def _education(item, facts):
    need = jd.DEGREES.index(item['value'])
    stated = [f for f in facts if f['degrees']]
    meets = [f['id'] for f in stated if max(jd.DEGREES.index(d) for d in f['degrees']) >= need]
    if meets:
        return _hard('education', item['value'], item, 'met', meets)
    return _hard('education', item['value'], item, 'not_met' if stated else 'unknown', why=WHY['low_degree' if stated else 'no_degree'])


def _language(item, facts):
    value = item['value']
    if value in ('英语六级', '英语四级'):
        strong = [f['id'] for f in facts if any(w in f['low'] for w in ENGLISH_STRONG)]
        weak = [f['id'] for f in facts if any(w in f['low'] for w in ENGLISH_WEAK)]
        met = strong + (weak if value == '英语四级' else [])
        if met:
            return _hard('language', value, item, 'met', dict.fromkeys(met))
        if weak:
            return _hard('language', value, item, 'not_met', weak, why=WHY['low_language'])
        return _hard('language', value, item, 'unknown', why=WHY['no_language'])
    words = next((w for name, w in jd.LANGUAGES if name == value), (value,))
    hits = [f['id'] for f in facts if any(_says(w, f) for w in words)]
    return _hard('language', value, item, 'met', hits) if hits else _hard('language', value, item, 'unknown', why=WHY['no_language'])


def _certificate(item, facts):
    words = next((w for name, w in jd.CERTS if name == item['value']), (item['value'],))
    hits = [f['id'] for f in facts if any(_says(w, f) for w in words)]
    if hits:
        return _hard('certificate', item['value'], item, 'met', hits)
    return _hard('certificate', item['value'], item, 'unknown', why=WHY['no_certificate'])


def _location(item, conditions):
    cities = [c for c in (conditions or {}).get('cities') or [] if isinstance(c, str)]
    if not cities:
        return _hard('location', item['value'], item, 'unknown', why=WHY['no_cities'], basis='conditions')
    hit = any(_tight(c) in _tight(item['value']) or _tight(item['value']) in _tight(c) for c in cities)
    return _hard('location', item['value'], item, 'met' if hit else 'not_met', why=None if hit else WHY['other_city'], basis='conditions')


def _keyword(value, source, item, facts):
    exact = _naming(value, facts)
    near = {w: _naming(w, facts) for w in _near(value)}
    near = {w: ids for w, ids in near.items() if ids}
    related_ids = list(dict.fromkeys(i for ids in near.values() for i in ids if i not in exact))
    coverage = 'explicit' if exact else 'related' if near else 'absent'
    return dict(keyword=value, source=source, jd_evidence=item['evidence'], coverage=coverage, fact_ids=exact,
                related_fact_ids=[] if exact else related_ids, related_terms=[] if exact else list(near), why=WHY[coverage])


def _bonus_keywords(structure):
    seen = {_tight(i['value']) for f in ('hard_skills', 'soft_skills') for i in structure.get(f) or []}
    out = []
    for item in structure.get('bonus') or []:
        for word in jd.phrases(item['value']):
            if not re.fullmatch(r'\d+(?:-\d+)?年(?:以上)?', word) and _tight(word) not in seen:
                seen.add(_tight(word))
                out.append((word, item))
    return out


def backing(phrase, facts):
    """Confirmed fact ids that state one requirement phrase ('3年以上', '本科', 'Python') in so many words."""
    rows = _facts(facts)
    years = re.fullmatch(r'(\d+)(?:-\d+)?年(?:以上)?', phrase)
    if years:
        return [f['id'] for f in rows if f['years'] and max(f['years']) >= int(years.group(1))]
    if phrase in jd.DEGREES:
        return [f['id'] for f in rows if f['degrees'] and max(map(jd.DEGREES.index, f['degrees'])) >= jd.DEGREES.index(phrase)]
    return _naming(phrase, rows)


def _grams(text):
    """CJK 3-grams and ASCII words (2+ letters) of one text, for comparing a duty with a fact."""
    tight = _tight(text)
    runs = re.findall(r'[\u4e00-\u9fff]+', tight)
    out = {run[i:i + DUTY_GRAM] for run in runs for i in range(len(run) - DUTY_GRAM + 1)}
    out = {g for g in out if not FILLER.search(g)}
    return out | {w for w in re.findall(r'[a-z][a-z0-9+#]+', tight)}


def _duty(item, facts, hard_quotes):
    """One duty row: facts that state the duty's own words (有事实), facts sharing a non-filler 3-character run or a skill word (相近), or none."""
    text = item['value']
    if item['evidence'] in hard_quotes:
        return None
    clause = _tight(DUTY_LEAD.sub('', text.strip()))
    skills = jd.phrases(text)
    exact = [f['id'] for f in facts if len(clause) >= 4 and clause.rstrip('。；;.') in f['tight']]
    want = _grams(DUTY_LEAD.sub('', text.strip()))
    close = []
    for f in facts:
        if f['id'] in exact:
            continue
        shared = want & _grams(f['low'])
        asked = [w for w in skills if _says(w, f) or any(_says(n, f) for n in _near(w))]
        if shared or asked:
            close.append(f['id'])
    return dict(kind='duty', requirement=text, jd_evidence=item['evidence'], fact_ids=exact, related_fact_ids=close,
                status='supported' if exact else 'related' if close else 'none')


def explain(structure, facts, conditions=None):
    """dict(hard, keywords, evidence, notice, evidence_note) for one job's structure."""
    facts = _facts(facts)
    hard = []
    if structure.get('education'):
        hard.append(_education(structure['education'], facts))
    if structure.get('years'):
        hard.append(_years(structure['years'], facts))
    hard += [_language(i, facts) for i in structure.get('languages') or []]
    hard += [_certificate(i, facts) for i in structure.get('certificates') or []]
    hard += [_location(i, conditions) for i in structure.get('location') or []]
    if structure.get('remote'):
        remote = structure['remote']
        hard.append(_hard('remote', remote['value'], remote, 'unknown', why=WHY['remote'], basis='conditions'))
    keywords = [_keyword(i['value'], src, i, facts) for f, src in (('hard_skills', 'hard_skill'), ('soft_skills', 'soft_skill'))
                for i in structure.get(f) or []]
    keywords += [_keyword(word, 'bonus', item, facts) for word, item in _bonus_keywords(structure)]
    quotes = {r['jd_evidence'] for r in hard}
    evidence = [row for row in (_duty(i, facts, quotes) for i in structure.get('duties') or []) if row]
    return dict(hard=hard, keywords=keywords, evidence=evidence, notice=NOTICE, evidence_note=None if evidence else WHY['no_duties'])
