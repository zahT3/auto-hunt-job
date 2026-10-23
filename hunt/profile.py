"""Local evidence-based profile hints; no network and no inferred qualifications."""
import copy
import math
import re
from collections import Counter

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
}
_NEGATIVE = re.compile(r'没有|不会|不具备|未掌握|不熟悉|无.{0,10}(?:经验|经历)|\bno\b|\bwithout\b', re.I)
_DIRECTIONS = {
    'AI 应用开发': ({'RAG', 'Agent', 'LLM', 'LangChain'}, ['AI 应用开发', 'Agent 开发', 'RAG 工程师']),
    'Web3 开发': ({'Solidity', 'Web3', 'Ethereum'}, ['Web3 开发', '区块链开发', 'Solidity 工程师']),
    '数据分析': ({'SQL', '数据分析'}, ['数据分析师']),
    '数字化': ({'数字化'}, ['数字化开发', '信息化工程师']),
    '软件开发': ({'Python', 'JavaScript', 'Java', 'React', 'Vue'}, ['软件开发工程师']),
}



def _source_facts(candidate, confirmed_only=False):
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
    facts = _source_facts(candidate, confirmed_only=confirmed_only)
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
    directions, queries, query_evidence = [], [], []
    for label, (terms, suggestions) in _DIRECTIONS.items():
        ids = list(dict.fromkeys(fid for skill in skills if skill['label'] in terms for fid in skill['fact_ids']))
        if not ids:
            continue
        directions.append({'label': label, 'fact_ids': ids, 'status': 'suggested'})
        for query in suggestions:
            queries.append(query)
            query_evidence.append({'query': query, 'fact_ids': ids})
    return {
        'method': 'local_rules_v1', 'skills': skills, 'directions': directions,
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
    direction_matches = [dict(name=d['label'], fact_ids=d['fact_ids']) for d in profile['directions']
                         if _DIRECTIONS[d['label']][0] & job_skills]
    return {
        'skill_matches': skill_matches, 'direction_matches': direction_matches,
        'missing_skills': sorted(job_skills - {s['name'] for s in profile['skills']}),
        'priority': min(10, len(skill_matches) * 2 + len(direction_matches)),
        'note': '仅按已确认简历原文与岗位词项计算本地相关度；未提及不等于不会，非录用概率，也不替代硬条件审核。',
    }
