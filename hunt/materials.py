"""Local, deterministic material preparation. Drafts never become facts."""
import copy
import math
import re
from collections import Counter


STATUS_LABELS = {
    'supported': '已有证据', 'not_met': '明确不符合',
    'missing_evidence': '缺失证据', 'needs_confirmation': '需要确认',
}


def synthetic_candidate():
    """Explicit development data; never the real user's profile."""
    rows = [
        ('demo-name', '姓名：林示例（合成候选人）。', ['identity'], '林示例'),
        ('demo-email', '联系邮箱：candidate@example.invalid。', ['contact'], 'candidate@example.invalid'),
        ('demo-python', '使用 Python 和 SQLite 实现过一个本地任务管理原型，并完成本地测试。', ['python', 'sqlite', '原型', '本地测试'], None),
        ('demo-analysis', '在合成数据练习中使用 SQL 分析 120 条记录，尚未上线，也没有业务效果证据。', ['sql', '数据分析', '合成数据'], None),
        ('demo-years', '已确认的相关工作经验为 1 年。', ['experience'], 1),
    ]
    facts = []
    for ident, text, tags, value in rows:
        fact = dict(id=ident, text=text, source={'reference': 'synthetic://candidate/v1#' + ident, 'label': '开发合成资料'}, status='confirmed', version=1, disclosure='application', tags=tags)
        if value is not None:
            fact['value'] = value
        facts.append(fact)
    return {'name': '林示例', 'synthetic': True, 'version': 1, 'facts': facts,
            'fields': {'name': {'value': '林示例', 'fact_ids': ['demo-name']},
                       'email': {'value': 'candidate@example.invalid', 'fact_ids': ['demo-email']},
                       'years_experience': {'value': 1, 'fact_ids': ['demo-years']}}}


def accepted_facts(candidate, for_application=True):
    """Only confirmed, referenced facts explicitly cleared for applications."""
    facts = candidate.get('facts', [])
    counts = Counter(str(f.get('id', '')) for f in facts if isinstance(f, dict))
    return [copy.deepcopy(f) for f in facts if isinstance(f, dict)
            and f.get('id') and counts[str(f['id'])] == 1
            and isinstance(f.get('text'), str) and f['text'].strip()
            and f.get('status') == 'confirmed'
            and isinstance(f.get('source'), dict)
            and isinstance(f['source'].get('reference'), str) and f['source']['reference'].strip()
            and str(f['source'].get('kind', '')).casefold() not in {'draft', 'generated', 'material', 'derived'}
            and (f.get('disclosure') == 'application' or not for_application and f.get('disclosure') == 'private')
            and isinstance(f.get('version'), int)]


def _field(candidate, name, facts):
    field = candidate.get('fields', {}).get(name, {})
    if not isinstance(field, dict) or not field.get('fact_ids'):
        return None
    by_id = {f['id']: f for f in facts}
    refs = [by_id.get(ident) for ident in field['fact_ids']]
    if not all(refs):
        return None
    value = field.get('value')
    if value is None or value == '':
        return None
    # An ID reference alone cannot substantiate a fabricated field value.
    if not any(value == f.get('value', f['text']) for f in refs):
        return None
    return {'value': value, 'fact_ids': list(field['fact_ids'])}


def _norm(text):
    return re.sub(r'\s+', ' ', str(text)).strip().rstrip('。.;；').casefold()


def _requirements(job):
    value = job.get('requirements') or job.get('requirements_text')
    if not value:
        value = job.get('description') or job.get('jd') or job.get('raw_text') or ''
    if isinstance(value, str):
        values = value.splitlines()
    elif isinstance(value, list):
        values = [item.get('text', '') if isinstance(item, dict) else str(item) for item in value]
    else:
        values = []
    headings = {'任职要求', '岗位要求', '必备条件', '硬性条件', '加分项', '优先条件', '经验', 'requirements', 'qualifications', 'preferred qualifications'}
    return [v.strip() for v in values if v.strip() and v.strip().strip('#*：: ').casefold() not in headings]


def _related(text, fact):
    lowered = text.casefold()
    return any(str(tag).casefold() in lowered for tag in fact.get('tags', []) if len(str(tag)) >= 2)


def _result(text, status, fact_ids=None, reason=''):
    return {'text': text, 'status': status, 'fact_ids': fact_ids or [], 'reason': reason}


def match(candidate, job, config=None):
    """Evidence coverage, never a hiring probability or inferred qualification."""
    config = config or {}
    facts = accepted_facts(candidate, for_application=False)
    requirements = []
    for text in _requirements(job):
        exact = [f['id'] for f in facts if _norm(f['text']) == _norm(text)]
        related = [f['id'] for f in facts if _related(text, f)]
        if exact:
            requirements.append(_result(text, 'supported', exact, '整条要求与已确认的事实原文一致；仅作本地匹配，不授予披露权限。'))
        elif related:
            requirements.append(_result(text, 'needs_confirmation', related, '仅有关键词相关证据；不能据此认定整条要求已满足。'))
        else:
            requirements.append(_result(text, 'missing_evidence', reason='没有已确认事实支持整条要求。'))
    hard = []
    cities = config.get('cities') or config.get('locations') or []
    if isinstance(cities, str):
        cities = [cities]
    location = job.get('location') or job.get('city')
    if cities:
        if not location or (isinstance(location, str) and any(word in location.casefold() for word in ['未知', '待确认', '待补充', 'unknown', 'n/a'])):
            hard.append(_result('工作地点', 'needs_confirmation', reason='岗位未提供地点。'))
        elif isinstance(location, (str, list)):
            locations = location if isinstance(location, list) else [location]
            allowed = any(_norm(city) == _norm(place) for city in cities for place in locations)
            # Multi-location or province-bearing strings need a human interpretation.
            composite = any(any(p in str(place) for p in ['/', '、', ',', '省', '市', '远程', 'remote']) for place in locations)
            status = 'supported' if allowed else ('needs_confirmation' if composite else 'not_met')
            hard.append(_result('工作地点', status, reason='岗位地点：{}；目标地点：{}。'.format(' / '.join(map(str, locations)), ' / '.join(map(str, cities)))))
    else:
        hard.append(_result('目标地点', 'needs_confirmation', reason='尚未确认目标地点与远程范围。'))
    minimum = job.get('min_years', job.get('experience_min'))
    if minimum is None:
        experience = str(job.get('experience') or job.get('experience_requirement') or '')
        found = re.search(r'(\d+(?:\.\d+)?)\s*[-~至]\s*\d+(?:\.\d+)?\s*(?:年|years?)', experience, re.I)
        if not found and not any(word in experience for word in ['以下', '以内', 'up to', 'at most']):
            found = re.search(r'(\d+(?:\.\d+)?)\s*\+?\s*(?:年|years?)', experience, re.I)
        if found:
            minimum = float(found.group(1))
    if minimum is None:
        # Only explicit lower bounds in experience requirements. Alternatives remain unresolved.
        for line in _requirements(job):
            # Parenthetical sector examples do not waive an explicit main-clause minimum.
            # A true alternative such as "3年以上经验或优秀应届生" remains unresolved.
            main_clause = re.sub(r'（[^）]*）|\([^)]*\)', '', line)
            if not re.search(r'经验|experience', main_clause, re.I) or re.search(r'或者|或|\bor\b', main_clause, re.I):
                continue
            found = re.search(r'(?:至少|不少于|最低|at least|minimum)\s*(\d+(?:\.\d+)?)\s*(?:年|years?)', main_clause, re.I)
            if not found:
                found = re.search(r'(\d+(?:\.\d+)?)\s*(?:年\s*以上|\+\s*(?:年|years?))', main_clause, re.I)
            if found:
                minimum = float(found.group(1))
                break
    if minimum is not None:
        years = _field(candidate, 'years_experience', facts)
        try:
            minimum = float(minimum)
            if minimum < 0 or not math.isfinite(minimum):
                raise ValueError()
            actual = float(years['value']) if years else None
            if actual is not None and (actual < 0 or not math.isfinite(actual)):
                actual = None
        except (TypeError, ValueError):
            actual = None
        if actual is None:
            hard.append(_result('相关经验年限', 'missing_evidence', reason='缺少可核对的相关年限；不能从项目关键词推导。'))
        else:
            hard.append(_result('相关经验年限', 'supported' if actual >= minimum else 'not_met', years['fact_ids'], '确认经验 {} 年；岗位最低 {} 年。仅判断年限，不代表整条职责已满足。'.format(actual, minimum)))
    salary = job.get('salary')
    floor = config.get('salary_min')
    if floor is not None:
        low = salary.get('min') if isinstance(salary, dict) else salary
        high = salary.get('max', low) if isinstance(salary, dict) else salary
        try:
            if isinstance(low, bool) or isinstance(high, bool) or isinstance(floor, bool):
                raise ValueError()
            low, high, floor = float(low), float(high), float(floor)
            if not all(math.isfinite(number) and number >= 0 for number in [low, high, floor]) or low > high:
                raise ValueError()
        except (TypeError, ValueError):
            hard.append(_result('岗位薪资', 'needs_confirmation', reason='薪资缺失或不是可直接比较的数字；需要确认币种、周期与单位。'))
        else:
            status = 'not_met' if high < floor else ('supported' if low >= floor else 'needs_confirmation')
            hard.append(_result('岗位薪资', status, reason='岗位数字范围 {} - {}；配置底线 {}，按相同币种、周期与单位比较。'.format(low, high, floor)))
    elif not salary:
        hard.append(_result('岗位薪资', 'needs_confirmation', reason='岗位薪资未知。'))
    excluded = config.get('exclude_keywords') or config.get('excluded_keywords') or []
    if isinstance(excluded, str):
        excluded = [excluded]
    searchable = ' '.join(str(job.get(key, '')) for key in ['title', 'company', 'industry', 'description', 'requirements_text']).casefold()
    for word in excluded:
        if str(word).strip() and str(word).casefold() in searchable:
            hard.append(_result('排除关键词：' + str(word), 'not_met', reason='岗位公开字段包含用户配置的排除关键词。'))
    counts = Counter(r['status'] for r in requirements + hard)
    return {'requirements': requirements, 'hard': hard,
            'summary': {'supported': counts['supported'], 'not_met': counts['not_met'],
                        'missing_evidence': counts['missing_evidence'], 'needs_confirmation': counts['needs_confirmation'],
                        'eligible': False if counts['not_met'] else None,
                        'note': '仅核对现有证据；未知条件仍需集中确认。'}}


def prepare(candidate, job, config=None):
    facts = accepted_facts(candidate)
    matching = match(candidate, job, config)
    name = _field(candidate, 'name', facts)
    email = _field(candidate, 'email', facts)
    fields = {}
    for key in candidate.get('fields', {}):
        proven = _field(candidate, key, facts)
        if proven:
            fields[key] = proven
    identity_ids = set((name or {}).get('fact_ids', []) + (email or {}).get('fact_ids', []))
    experience = [f for f in facts if f['id'] not in identity_ids and 'experience' not in f.get('tags', [])]
    jd = '\n'.join(_requirements(job)).casefold()
    experience.sort(key=lambda f: not _related(jd, f))
    selected = [f for f in facts if f['id'] in identity_ids] + experience
    claims = [{'text': f['text'], 'fact_ids': [f['id']]} for f in selected]
    lines = [str(name['value']) if name else '姓名待补充']
    if candidate.get('synthetic'):
        lines.append('合成候选人 - 仅用于开发验证')
    if email:
        lines.append(str(email['value']))
    lines.extend(['', '申请岗位：' + str(job.get('title', '岗位名称待补充')), '', '经历与能力'])
    lines.extend(f['text'] for f in experience)
    if not experience:
        lines.append('尚无可用于申请的已确认经历。')
    gaps = [r for r in matching['requirements'] + matching['hard'] if r['status'] != 'supported']
    blockers = []
    required_fields = job.get('required_fields', ['name', 'email'])
    for key in required_fields:
        if key not in fields:
            label = {'name': '姓名', 'email': '联系邮箱'}.get(key, str(key))
            issue = _result(label, 'missing_evidence', reason='申请必填字段缺少已确认、带来源且允许申请披露的事实。')
            gaps.append(issue)
            blockers.append(issue)
    answers = []
    for question in job.get('questions', []):
        item = question if isinstance(question, dict) else {'text': str(question)}
        key = item.get('field')
        proven = fields.get(key)
        answers.append({'question': item.get('text', item.get('label', '待核对问题')), 'field': key,
                        'answer': proven['value'] if proven else '', 'fact_ids': proven['fact_ids'] if proven else [],
                        'status': 'supported' if proven else 'needs_confirmation'})
        if not proven:
            issue = _result(str(item.get('text', '筛选问题')), 'needs_confirmation', reason='没有可直接复用的已确认答案。')
            gaps.append(issue)
            if item.get('required', True):
                blockers.append(issue)
    cover = ['申请岗位：' + str(job.get('title', '岗位名称待补充')), '', '以下为可核对的相关经历：']
    cover.extend(f['text'] for f in experience)
    cover.append('')
    if candidate.get('synthetic'):
        cover.insert(0, '合成候选人 - 仅用于开发验证')
    return {'claims': claims, 'resume': '\n'.join(lines) + '\n', 'cover_letter': '\n'.join(cover),
            'answers': answers, 'gaps': gaps, 'blockers': blockers, 'fields': fields, 'matching': matching,
            'candidate_version': candidate.get('version'), 'synthetic': bool(candidate.get('synthetic')),
            'source_map': {f['id']: {'text': f['text'], 'source': f['source'], 'version': f['version'], 'disclosure': f['disclosure']} for f in facts},
            'method': 'local_exact_evidence_v1'}
