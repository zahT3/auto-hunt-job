"""Local evidence-based profile hints; no network and no inferred qualifications."""
import copy
import math
import re
from collections import Counter

from . import directions

# Only public, generic job/technology terms can enter a suggested search query.
_SKILLS = {
    'Python': r'(?<![a-z0-9_])python(?![a-z0-9_])', 'SQL': r'(?<![a-z0-9_])sql(?![a-z0-9_])',
    'JavaScript': r'javascript|typescript', 'Java': r'(?<![a-z0-9_])java(?![a-z0-9_])',
    'React': r'(?<![a-z0-9_])react(?![a-z0-9_])', 'Vue': r'(?<![a-z0-9_])vue(?![a-z0-9_])',
    'RAG': r'(?<![a-z])rag(?![a-z])|检索增强', 'Agent': r'(?<![a-z])agents?(?![a-z])|智能体',
    'LLM': r'(?<![a-z])llms?(?![a-z])|大语言模型|大模型',
    'LangChain': r'langchain', 'PyTorch': r'pytorch', 'Docker': r'docker',
    'Solidity': r'solidity', 'Web3': r'web\s?3|区块链', 'Ethereum': r'ethereum|以太坊',
    '数据分析': r'数据分析|data analysis', '数字化': r'数字化|信息化',
    # Non-tech trades; each label is also a phrase in the direction table, so it feeds direction suggestions.
    '销售': r'销售|(?<![a-z])sales(?![a-z])|大客户|客户开发|业务拓展', '运营': r'运营|(?<![a-z])operations(?![a-z])',
    '市场营销': r'市场营销|品牌推广|(?<![a-z])marketing(?![a-z])', '客服': r'客服|客户服务|customer service',
    '财务': r'财务|(?<![a-z])finance|financial', '会计': r'会计|核算|记账|总账|accounting|accountant',
    '税务': r'税务|报税|纳税申报|(?<![a-z])tax(?![a-z])', '人力资源': r'人力资源|招聘|(?<![a-z])hr(?![a-z])|human resources|recruit',
    '法务': r'法务|合同审核|律师|(?<![a-z])legal(?![a-z])', '平面设计': r'平面设计|视觉设计|ui设计|graphic design|photoshop|illustrator',
    '教学': r'教学|授课|教师|讲师|teaching|teacher|tutor', '护理': r'护理|护士|nursing|(?<![a-z])nurse',
    '采购': r'采购|procurement|purchasing', '供应链': r'供应链|supply chain', '物流': r'物流|仓储|logistics|warehouse',
}
_NEGATIVE = re.compile(r'没有|不会|不具备|未掌握|不熟悉|无.{0,10}(?:经验|经历)|\bno\b|\bwithout\b', re.I)
# Skill mentions -> direction table ids. The table matches job-title phrases, and a bare skill word ('Python', 'RAG')
# hits none of them, so this short bridge says which directions a skill points to. Every id must exist in the table.
_SKILL_DIRECTIONS = {
    'Python': ['data-analyst', 'backend'], 'SQL': ['data-analyst', 'data-engineer'], 'Java': ['backend'],
    'JavaScript': ['frontend'], 'React': ['frontend'], 'Vue': ['frontend'], 'Docker': ['backend'],
    'RAG': ['ai-application-dev'], 'Agent': ['ai-application-dev'], 'LLM': ['ai-application-dev'], 'LangChain': ['ai-application-dev'],
    'PyTorch': ['data-scientist'], 'Solidity': ['blockchain-dev'], 'Web3': ['blockchain-dev'], 'Ethereum': ['blockchain-dev'],
    '数据分析': ['data-analyst'], '数字化': ['software-engineer'],
    '销售': ['b2b-enterprise-sales', 'retail-sales-guide'], '运营': ['user-operations', 'operations-management'],
    '市场营销': ['marketing-planning', 'brand-marketing'], '客服': ['customer-service'],
    '财务': ['accountant', 'management-accountant'], '会计': ['accountant'], '税务': ['tax-specialist'],
    '人力资源': ['hrbp', 'recruiter'], '法务': ['legal-counsel'], '平面设计': ['graphic-designer'],
    '教学': ['training-instructor', 'k12-teacher'], '护理': ['nurse'], '采购': ['procurement'],
    '供应链': ['supply-chain-planning', 'procurement'], '物流': ['logistics-warehouse'],
}
MAX_QUERIES_PER_DIRECTION = 3


def synthetic_profile(candidate):
    """Synthetic provenance survives editing the top-level profile toggle."""
    if candidate.get('synthetic') is True:
        return True
    return any(isinstance(f, dict) and isinstance(f.get('source'), dict)
               and (f['source'].get('synthetic') is True
                    or str(f['source'].get('reference', '')).startswith('synthetic://'))
               for f in candidate.get('facts', []))


def source_facts(candidate, confirmed_only=False):
    """Keep only unique, well-formed, source-backed facts; privacy stays local."""
    rows = candidate.get('facts', []) if isinstance(candidate, dict) else []
    if not isinstance(rows, list):
        return []
    counts = Counter(f['id'] for f in rows if isinstance(f, dict) and isinstance(f.get('id'), str))
    statuses = {'confirmed'} if confirmed_only else {'confirmed', 'unconfirmed'}
    valid = []
    for fact in rows:
        if not isinstance(fact, dict) or not isinstance(fact.get('id'), str) or not fact['id'].strip():
            continue
        if counts[fact['id']] != 1 or not isinstance(fact.get('status'), str) or fact['status'] not in statuses:
            continue
        if not isinstance(fact.get('text'), str) or not fact['text'].strip():
            continue
        source = fact.get('source')
        if not isinstance(source, dict) or not isinstance(source.get('reference'), str) or not source['reference'].strip():
            continue
        if str(source.get('kind', '')).casefold() in {'draft', 'generated', 'material', 'derived'}:
            continue
        if type(fact.get('version')) is not int or fact['version'] < 1:
            continue
        valid.append(fact)
    return valid


def _supported_fields(candidate, facts):
    fields = candidate.get('fields', {}) if isinstance(candidate, dict) else {}
    if not isinstance(fields, dict):
        return {}
    by_id = {fact['id']: fact for fact in facts}
    result = {}
    for key, field in fields.items():
        if not isinstance(field, dict):
            continue
        ids = field.get('fact_ids')
        if not isinstance(ids, list) or not ids or not all(isinstance(ident, str) and ident in by_id for ident in ids):
            continue
        value = field.get('value')
        if value is None or value == '' or not any(value == by_id[ident].get('value', by_id[ident]['text']) for ident in ids):
            continue
        if key == 'years_experience' and (type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 80):
            continue
        result[key] = copy.deepcopy(field)
    return result


def build_profile(candidate, confirmed_only=False):
    """Return reviewable mentions and generic queries, each linked to source facts.

    Mentions are search hints, not proficiency, eligibility, or a target preference.
    No years are computed from dates, graduation, project duration or age.
    confirmed_only=True also hides fields whose source facts were not confirmed.
    """
    facts = source_facts(candidate, confirmed_only=confirmed_only)
    fields = _supported_fields(candidate, facts)
    confirmed_ids = {f['id'] for f in facts if f['status'] == 'confirmed'}
    skills, education, experience = [], [], []
    for label, pattern in _SKILLS.items():
        ids = [f['id'] for f in facts if any(re.search(pattern, sentence, re.I) and not _NEGATIVE.search(sentence)
               for sentence in re.split(r'[。；;\n]', f.get('text', '')))]
        if ids:
            skills.append({'name': label, 'label': label, 'fact_ids': ids, 'kind': 'mentioned', 'status': 'confirmed' if set(ids) <= confirmed_ids else 'needs_confirmation'})
    for f in facts:
        text = f.get('text', '')
        if re.search(r'本科|硕士|博士|大专|学士|bachelor|master|ph\.?d', text, re.I):
            education.append({'text': text, 'fact_ids': [f['id']], 'status': 'confirmed' if f['id'] in confirmed_ids else 'needs_confirmation'})
        if re.search(r'工作经验|工作经历|实习|work experience|employment', text, re.I):
            experience.append({'text': text, 'fact_ids': [f['id']], 'status': 'confirmed' if f['id'] in confirmed_ids else 'needs_confirmation'})
    directions_found, queries, query_evidence = [], [], []
    # Every fact that passed the confirmed_only filter is evidence: project lines ('负责交互设计…') name the work as
    # often as lines tagged 工作经历. Degree and course lines weigh half, as in the table (studied, not done).
    study = re.compile(r'本科|硕士|博士|大专|学士|bachelor|master|ph\.?d|课程|course', re.I)
    lines = [dict(text=f['text'], fact_ids=[f['id']], status='confirmed') for f in facts]
    # Skill names are derived from these same lines, so only the lines feed the table phrases.
    view = dict(experience=[x for x in lines if not study.search(x['text'])], education=[x for x in lines if study.search(x['text'])])
    table, rank = directions.profile_scores(view), {r['id']: n for n, r in enumerate(directions.load())}
    written = {i: set(directions.evidence(view, i)) for i in table}
    support, pointing = {}, {}
    for skill in skills:
        for ident in _SKILL_DIRECTIONS.get(skill['label'], []):
            support.setdefault(ident, []).extend(skill['fact_ids'])
            # A skill adds nothing where its own lines already hit the direction's phrases ('眼动数据分析').
            if not set(skill['fact_ids']) & written.get(ident, set()):
                pointing.setdefault(ident, set()).add(skill['label'])
    # Job titles written in the résumé are evidence; a skill only hints, so each pointing skill adds half a hit
    # ('用过 Python' must not outrank '负责交互设计'). Ties: more written evidence, more facts, then table order.
    score = {i: table.get(i, 0) + 0.5 * len(pointing.get(i, ())) for i in set(table) | set(support)}
    ranked = sorted(score, key=lambda i: (-score[i], -table.get(i, 0), -len(set(support.get(i, []))), rank[i]))
    for ident in ranked[:directions.MAX_SUGGEST]:
        ids = list(dict.fromkeys(support.get(ident, []) + directions.evidence(view, ident)))
        if not ids:
            continue
        row = directions.get(ident)
        label = re.sub(r'[（(].*?[）)]', '', row['name']).strip()
        directions_found.append({'id': ident, 'label': label, 'fact_ids': ids, 'status': 'suggested'})
        # A name like '区块链 / 智能合约开发' is a label, not a search phrase; example titles are.
        for query in list(dict.fromkeys(([] if '/' in label else [label]) + row['titles']))[:MAX_QUERIES_PER_DIRECTION]:
            if query not in queries:
                queries.append(query)
                query_evidence.append({'query': query, 'fact_ids': ids})
    return {
        'method': 'local_rules_v2', 'skills': skills, 'directions': directions_found,
        'education': education, 'experience': experience,
        'years_experience': fields.get('years_experience'),
        'fields': fields, 'confirmed_only': bool(confirmed_only),
        'suggested_queries': queries, 'query_evidence': query_evidence,
        'missing_preferences': ['target_roles', 'locations_or_remote', 'salary_floor', 'exclusions', 'deadline'],
        'external_search_authorized': False,
        'unknowns': (['整体工作年限未明确或存在冲突'] if not fields.get('years_experience') else []) + ['技能熟练度', '生产项目成熟度', '当前求职偏好'],
        'notice': '规则提取而非深度语义理解，依据原文提出检索建议；技能熟练度、学历、经历和求职偏好仍需核对。上传不授权外传或投递。',
    }


def confirm_candidate(candidate, fact_ids, *, application_fact_ids=()):
    """Explicit review helper. Local confirmation defaults to private disclosure.

    Caller must collect the user's selection; this function must never run at upload.
    application_fact_ids is a separate explicit disclosure selection, not permission
    to submit. Existing snapshot-bound application approval remains mandatory.
    """
    result = copy.deepcopy(candidate)
    by_id = {f['id']: f for f in result.get('facts', [])}
    selected, disclosed = set(fact_ids), set(application_fact_ids)
    if not selected <= by_id.keys() or not disclosed <= selected:
        raise ValueError('确认项必须引用已有事实；用于申请的事实必须包含在本次确认中')
    for ident in selected:
        fact = by_id[ident]
        if not fact.get('source', {}).get('reference'):
            raise ValueError('事实缺少原文来源')
        fact['status'] = 'confirmed'
        fact['disclosure'] = 'application' if ident in disclosed else 'private'
        fact['version'] = int(fact.get('version', 1)) + 1
    result['version'] = int(result.get('version', 1)) + 1
    return result


def recommend(candidate, job, config=None):
    """Explain local relevance using confirmed source mentions; not hiring odds.

    priority is only a stable sorting aid (0-10). Missing skills mean no matching
    resume mention, not that the candidate fails a mandatory job requirement.
    """
    profile = build_profile(candidate, confirmed_only=True)
    text = ' '.join(str(job.get(key) or '') for key in ('title', 'description', 'jd', 'requirements', 'requirements_text', 'raw_text'))
    job_skills = {name for name, pattern in _SKILLS.items() if re.search(pattern, text, re.I)}
    skill_matches = [dict(name=s['name'], fact_ids=s['fact_ids']) for s in profile['skills'] if s['name'] in job_skills]
    # A suggested direction counts when the job itself clearly sits in it (the same 0.5 bar classification uses).
    direction_matches = [dict(name=d['label'], fact_ids=d['fact_ids']) for d in profile['directions']
                         if any(score >= 0.5 for _, score in directions.rule_match(job.get('title'), text, [d['id']]))]
    return {
        'skill_matches': skill_matches, 'direction_matches': direction_matches,
        'missing_skills': sorted(job_skills - {s['name'] for s in profile['skills']}),
        'priority': min(10, len(skill_matches) * 2 + len(direction_matches)),
        'note': '仅按已确认简历原文与岗位词项计算本地相关度；未提及不等于不会，非录用概率，也不替代硬条件审核。',
    }
