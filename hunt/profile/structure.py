"""Résumé structure: which confirmed fact lines belong to which section and entry (docs/v2-tailoring-design.md 4.3).

The structure holds only references to facts (id + version) and character spans into an entry head's own text, never
text of its own, so it cannot introduce words that are not in a confirmed fact. Rules pre-fill it; the user corrects
and confirms it once; later tailoring reuses it. Standard library only; it does not import tailor, ai or app code.

Spans are [start, end) in Python code points of the head fact's `text`.
"""
import copy
import re

from ..base import digest

FIELDS = ('company', 'title', 'start', 'end')
SECTION_KEYS = ('education', 'work', 'internship', 'project', 'skills', 'certificates', 'awards', 'summary', 'other')
ENTRY_KEYS = ('education', 'work', 'internship', 'project')  # sections whose entries have a head line and fields
KEY_LABELS = dict(education='教育', work='工作经历', internship='实习经历', project='项目经历', skills='技能', certificates='证书',
                  awards='奖项', summary='自我评价', other='其他')
HEADINGS = {
    'education': ('教育背景', '教育经历', '学习经历', '学历', '教育'),
    'work': ('工作经历', '职业经历', '工作背景'),
    'internship': ('实习经历', '实习'),
    'project': ('项目经历', '项目经验', '科研经历', '项目'),
    'skills': ('专业技能', '技能清单', '技术栈', '技能'),
    'certificates': ('资格证书', '技能证书', '证书'),
    'awards': ('获奖情况', '荣誉奖项', '奖项', '荣誉'),
    'summary': ('自我评价', '个人简介', '个人优势', '个人总结', '自我介绍'),
    'other': ('其他', '兴趣爱好'),
}
_WORDS = sorted(((w, k) for k, ws in HEADINGS.items() for w in ws), key=lambda p: -len(p[0]))
_WORD_KEY = dict(_WORDS)
# "技能：Python、SQL" is an ordinary line; only longer heading words (and 学历) count as a heading in front of text.
_PREFIX_OK = {w for w, _ in _WORDS if len(w) >= 4 or w == '学历'}
_HEADING = re.compile(r'^\s*(?P<word>' + '|'.join(re.escape(w) for w, _ in _WORDS) + r')\s*(?P<colon>[:：]?)\s*(?P<rest>.*?)\s*$', re.S)
MAX_HEADING = 12
MAX_HEAD_LINE = 80

_YM = r'\d{4}\s*年\s*\d{1,2}\s*月?|\d{4}\s*[./\-]\s*\d{1,2}'
DATE = r'(?:' + _YM + r'|\d{4}\s*年?)'
NOW = r'(?:至今|现在|今|[Pp]resent|[Nn]ow)'
RANGE = re.compile(r'(?P<start>' + DATE + r')\s*(?:(?P<now>至今)|(?:[—–~～到至]+|-{1,2})\s*(?P<end>' + DATE + '|' + NOW + r'))')
_DATE_TOKEN = re.compile(_YM + r'|\d{4}\s*年|至今|现在|[Pp]resent')
_SEPARATOR = re.compile(r'[，,；;、|｜·•：:（）()]|(?<![\x21-\x7e])\s+|\s+(?![\x21-\x7e])|\s[-—–]\s')
_COMPANY = re.compile(r'(?:公司|集团|有限|大学|学院|学校|研究院|研究所|实验室|科技|医院|银行|中心|事务所|工作室|Inc\.?|Ltd\.?|Corp\.?|Co\.|LLC|University|College|Institute|Labs?)$')
_TITLE = re.compile(r'(?:工程师|经理|专员|实习生|实习|助理|总监|主管|开发|设计师|分析师|研究员|架构师|运营|顾问|教师|老师|主任|负责人|程序员)$')
_DEGREE = re.compile(r'(?:本科|硕士|博士|专科|大专|学士|研究生)$')


class StructureError(ValueError):
    """The structure is not consistent with the confirmed facts."""


def confirmed(facts):
    return [f for f in facts if isinstance(f, dict) and f.get('status') == 'confirmed' and isinstance(f.get('id'), str)]


def ref(fact):
    return {'id': fact['id'], 'version': fact.get('version', 1)}


def facts_digest(facts):
    return digest([[f['id'], f.get('version', 1)] for f in confirmed(facts)])


def _heading(text):
    """(key, rest_start) when the line is a section heading or starts with one followed by a colon, else None."""
    found = _HEADING.match(text)
    if not found: return None
    word, rest = found['word'], found['rest']
    if not rest and len(text.strip()) <= MAX_HEADING + 1:
        return _WORD_KEY[word], None
    if found['colon'] and rest and word in _PREFIX_OK:
        return _WORD_KEY[word], found.start('rest')
    return None


def _ranges(text, start=0):
    return [m for m in RANGE.finditer(text, start)]


def _end(m):
    return (m.start('now'), m.end('now')) if m.group('now') else (m.start('end'), m.end('end'))


def _head_start(text):
    heading = _heading(text)
    return heading[1] if heading and heading[1] is not None else 0


def _dated(text):
    return len(text) <= MAX_HEAD_LINE and bool(_ranges(text, _head_start(text)))


def fragments(text):
    """Spans of the text a user may pick for a field: pieces between separators, and date tokens."""
    begin = _head_start(text)
    masked = list(text)
    spans = []
    for m in _ranges(text, begin):
        spans.extend([(m.start('start'), m.end('start')), _end(m)])
        for i in range(m.start(), m.end()): masked[i] = '\0'
    for m in _DATE_TOKEN.finditer(text, begin):
        spans.append((m.start(), m.end()))
    pieces, cursor = [], begin
    flat = ''.join(masked)
    for sep in list(_SEPARATOR.finditer(flat, begin)) + [None]:
        stop = sep.start() if sep else len(flat)
        pieces.append((cursor, stop))
        if sep: cursor = sep.end()
    for a, b in pieces:
        piece = flat[a:b]
        if '\0' in piece:
            # a piece beside a masked date range: keep only the unmasked runs
            for run in re.finditer(r'[^\0]+', piece): _add_piece(spans, flat, a + run.start(), a + run.end())
        else:
            _add_piece(spans, flat, a, b)
    out, seen = [], set()
    for a, b in sorted(set(spans)):
        if (a, b) in seen or a >= b: continue
        seen.add((a, b))
        out.append({'span': [a, b], 'text': text[a:b]})
    return out


def _add_piece(spans, flat, a, b):
    while a < b and (flat[a].isspace() or flat[a] in '。.'): a += 1
    while b > a and (flat[b - 1].isspace() or flat[b - 1] in '。.'): b -= 1
    if b > a: spans.append((a, b))


def _is_date(text):
    return bool(_DATE_TOKEN.fullmatch(text.strip()) or RANGE.fullmatch(text.strip()))


def _guess_fields(text, key, force_uncertain=False):
    """Field spans cut from one head line. Anything missing or ambiguous is `uncertain`."""
    ranges = _ranges(text, _head_start(text))
    fields = {name: {'span': None, 'confidence': 'uncertain'} for name in FIELDS}
    if ranges:
        m = ranges[0]
        ok = len(ranges) == 1
        fields['start'] = {'span': [m.start('start'), m.end('start')], 'confidence': 'ok' if ok else 'uncertain'}
        fields['end'] = {'span': list(_end(m)), 'confidence': 'ok' if ok else 'uncertain'}
    pieces = [f for f in fragments(text) if not _is_date(f['text']) and not any(m.start() <= f['span'][0] < m.end() for m in ranges)]
    for name, test in (('title', _DEGREE if key == 'education' else _TITLE), ('company', _COMPANY)):
        hits = [f for f in pieces if test.search(f['text'])]
        if name == 'company': hits = [f for f in hits if not _TITLE.search(f['text']) and not (key == 'education' and _DEGREE.search(f['text']))]
        if hits:
            fields[name] = {'span': hits[0]['span'], 'confidence': 'ok' if len(hits) == 1 else 'uncertain'}
    if force_uncertain:
        for item in fields.values(): item['confidence'] = 'uncertain'
    return fields


def _new_entry(counter, head, key, text, force_uncertain):
    counter[0] += 1
    fields = _guess_fields(text, key, force_uncertain) if key in ENTRY_KEYS and head is not None else (
        {name: {'span': None, 'confidence': 'uncertain'} for name in FIELDS} if key in ENTRY_KEYS else {})
    return {'id': f'n{counter[0]}', 'status': 'ok', 'head': ref(head) if head else None, 'fields': fields, 'bullets': []}


def build(facts, version=0):
    """Pre-fill a structure from the confirmed facts, in their order. status is `prefilled`, never `confirmed`."""
    sections, unassigned, current = [], [], None
    entry_counter = [0]
    for fact in confirmed(facts):
        text = fact.get('text') or ''
        found = _heading(text)
        if found:
            current = {'id': f's{len(sections) + 1}', 'key': found[0], 'title_fact': ref(fact), 'entries': [],
                       '_lines': [], '_prefix': fact if found[1] is not None else None}
            sections.append(current)
        elif current is None:
            unassigned.append(ref(fact))
        else:
            current['_lines'].append(fact)
    for section in sections:
        lines, prefix, key = section.pop('_lines'), section.pop('_prefix'), section['key']
        candidates = ([prefix] if prefix else []) + lines
        if key not in ENTRY_KEYS:
            if candidates:
                entry = _new_entry(entry_counter, prefix, key, '', False)
                entry['bullets'] = [ref(f) for f in lines]
                section['entries'].append(entry)
            continue
        dated = [f for f in candidates if _dated(f['text'])]
        if not dated:
            if candidates:
                head = candidates[0]
                entry = _new_entry(entry_counter, head, key, head['text'], True)
                entry['bullets'] = [ref(f) for f in candidates[1:]]
                section['entries'].append(entry)
            continue
        heads = {f['id'] for f in dated} | ({prefix['id']} if prefix else set())
        entry = None
        for fact in candidates:
            if fact['id'] in heads:
                entry = _new_entry(entry_counter, fact, key, fact['text'], False)
                section['entries'].append(entry)
            elif entry is None:
                unassigned.append(ref(fact))
            else:
                entry['bullets'].append(ref(fact))
    return {'version': version, 'status': 'prefilled', 'confirmed_at': None, 'facts_digest': facts_digest(facts),
            'sections': sections, 'unassigned': unassigned}


def _refs(structure):
    """Every (kind, ref) the structure holds, for checks."""
    for section in structure['sections']:
        if section.get('title_fact'): yield 'title', section['title_fact']
        for entry in section['entries']:
            if entry.get('head'): yield 'head', entry['head']
            for b in entry['bullets']: yield 'bullet', b
    for u in structure['unassigned']: yield 'unassigned', u


def _check_ref(item, by_id, where, strict=True):
    if not isinstance(item, dict) or not isinstance(item.get('id'), str) or type(item.get('version')) is not int:
        raise StructureError(f'{where}：事实引用格式不对')
    fact = by_id.get(item['id'])
    if fact is None: raise StructureError(f'{where}：引用了不存在或未确认的事实')
    if strict and item['version'] != fact.get('version', 1): raise StructureError(f'{where}：引用的事实版本已变化')
    return {'id': item['id'], 'version': item['version']}, fact


def validate(structure, facts):
    """Return a normalized copy, or raise StructureError. Rejects duplicate references, facts that do not exist or are
    not confirmed, spans outside the head's text, overlapping field spans and unknown keys. A stale entry may still hold
    an old fact version (it is shown for re-checking); any other reference must be current."""
    if not isinstance(structure, dict): raise StructureError('结构需要是对象')
    by_id = {f['id']: f for f in confirmed(facts)}
    out = {'version': structure.get('version'), 'status': structure.get('status'), 'confirmed_at': structure.get('confirmed_at'),
           'facts_digest': structure.get('facts_digest'), 'sections': [], 'unassigned': []}
    if type(out['version']) is not int or out['version'] < 0: raise StructureError('结构版本无效')
    if out['status'] not in ('prefilled', 'confirmed'): raise StructureError('结构状态无效')
    if not isinstance(structure.get('sections'), list) or not isinstance(structure.get('unassigned'), list): raise StructureError('结构缺少章节或未分配列表')
    used, section_ids, entry_ids = {}, set(), set()
    def use(item, where, strict=True, same_section=None):
        clean, fact = _check_ref(item, by_id, where, strict)
        if clean['id'] in used and not (same_section is not None and used[clean['id']] == same_section):
            raise StructureError(f'{where}：同一条事实被引用了多次')
        used.setdefault(clean['id'], same_section)
        return clean, fact
    for si, section in enumerate(structure['sections'], 1):
        where = f'第 {si} 个章节'
        if not isinstance(section, dict) or section.get('key') not in SECTION_KEYS: raise StructureError(f'{where}：类型无效')
        if not isinstance(section.get('id'), str) or section['id'] in section_ids: raise StructureError(f'{where}：编号缺失或重复')
        section_ids.add(section['id'])
        title = None
        if section.get('title_fact') is not None:
            title, _ = use(section['title_fact'], where + '标题', True, section['id'])
        clean_section = {'id': section['id'], 'key': section['key'], 'title_fact': title, 'entries': []}
        if not isinstance(section.get('entries'), list): raise StructureError(f'{where}：缺少条目列表')
        for ei, entry in enumerate(section['entries'], 1):
            ewhere = f'{where}第 {ei} 条'
            if not isinstance(entry, dict) or not isinstance(entry.get('id'), str) or entry['id'] in entry_ids: raise StructureError(f'{ewhere}：编号缺失或重复')
            entry_ids.add(entry['id'])
            if entry.get('status') not in ('ok', 'stale'): raise StructureError(f'{ewhere}：状态无效')
            strict = entry['status'] != 'stale'
            head, head_fact = None, None
            if entry.get('head') is not None:
                same = isinstance(entry['head'], dict) and title is not None and title['id'] == entry['head'].get('id')
                head, head_fact = use(entry['head'], ewhere + '条目头', strict, section['id'] if same else None)
            if not isinstance(entry.get('bullets'), list): raise StructureError(f'{ewhere}：缺少要点列表')
            bullets = [use(b, ewhere + '要点', strict)[0] for b in entry['bullets']]
            fields = entry.get('fields')
            if not isinstance(fields, dict): raise StructureError(f'{ewhere}：字段无效')
            clean_fields, taken = {}, []
            if section['key'] in ENTRY_KEYS:
                if set(fields) != set(FIELDS): raise StructureError(f'{ewhere}：字段必须是公司、职位、起止时间')
            elif fields: raise StructureError(f'{ewhere}：这个章节的条目没有字段')
            for name, item in fields.items():
                if not isinstance(item, dict) or item.get('confidence') not in ('ok', 'uncertain'): raise StructureError(f'{ewhere}：字段 {name} 无效')
                span = item.get('span')
                if span is not None:
                    length = len(head_fact['text']) if head_fact is not None else -1
                    if (not isinstance(span, list) or len(span) != 2 or any(type(x) is not int for x in span)
                            or not 0 <= span[0] < span[1] <= length): raise StructureError(f'{ewhere}：字段 {name} 的位置超出条目头原文')
                    if any(span[0] < o[1] and o[0] < span[1] for o in taken): raise StructureError(f'{ewhere}：字段 {name} 与其他字段的位置重叠')
                    taken.append(span)
                clean_fields[name] = {'span': list(span) if span else None, 'confidence': item['confidence']}
            clean_section['entries'].append({'id': entry['id'], 'status': entry['status'], 'head': head, 'fields': clean_fields, 'bullets': bullets})
        out['sections'].append(clean_section)
    out['unassigned'] = [use(u, '未分配事实')[0] for u in structure['unassigned']]
    return out


def open_items(structure):
    """Counts of what still needs the user: uncertain fields, stale entries, facts not placed in any entry."""
    uncertain = sum(1 for s in structure['sections'] for e in s['entries'] for f in e['fields'].values() if f['confidence'] == 'uncertain')
    stale = sum(1 for s in structure['sections'] for e in s['entries'] if e['status'] == 'stale')
    return {'uncertain': uncertain, 'stale': stale, 'unassigned': len(structure['unassigned'])}


def mark_stale(structure, facts):
    """Compare with the current facts. An entry whose head or bullet changed version becomes `stale` (fields back to
    uncertain, spans dropped when the head changed); a reference to a fact that is no longer confirmed or is gone is
    removed and its entry marked stale; confirmed facts the structure does not hold go to `unassigned`."""
    result = copy.deepcopy(structure)
    by_id = {f['id']: f for f in confirmed(facts)}
    def current(item): return by_id[item['id']].get('version', 1)
    for section in result['sections']:
        title = section.get('title_fact')
        if title:
            section['title_fact'] = {'id': title['id'], 'version': current(title)} if title['id'] in by_id else None
        for entry in section['entries']:
            stale = entry['status'] == 'stale'
            head = entry['head']
            head_changed = False
            if head:
                if head['id'] not in by_id: entry['head'], stale, head_changed = None, True, True
                elif head['version'] != current(head): stale = head_changed = True
            kept = []
            for b in entry['bullets']:
                if b['id'] not in by_id: stale = True
                else:
                    if b['version'] != current(b): stale = True
                    kept.append(b)
            entry['bullets'] = kept
            if stale and entry['status'] != 'stale' or head_changed:
                entry['status'] = 'stale'
                for item in entry['fields'].values():
                    item['confidence'] = 'uncertain'
                    if head_changed: item['span'] = None
    held = set()
    result['unassigned'] = [{'id': u['id'], 'version': current(u)} for u in result['unassigned'] if u['id'] in by_id]
    for _, item in _refs(result): held.add(item['id'])
    for f in confirmed(facts):
        if f['id'] not in held: result['unassigned'].append(ref(f))
    return result


def migrate(facts, stored):
    """The structure to show for the current facts, or None when nothing is confirmed.

    - No stored structure yet (a candidate confirmed before structures existed): a fresh `prefilled` one, never `confirmed`.
    - The stored one shares no fact with the current facts (a new résumé replaced the old): fresh, version kept going up.
    - A stored `prefilled` one that no longer matches the facts: rebuilt, nothing was confirmed yet.
    - A `confirmed` one: stale marking only, so the user's corrections survive.
    No fact is ever changed."""
    live = confirmed(facts)
    if not live and stored is None: return None
    if stored is None: return build(facts)
    ids = {item['id'] for _, item in _refs(stored)}
    version = stored.get('version', 0)
    if not ids & {f['id'] for f in live}: return build(facts, version) if live else mark_stale(stored, facts)
    if stored.get('status') == 'prefilled':
        return stored if stored.get('facts_digest') == facts_digest(facts) else build(facts, version)
    return mark_stale(stored, facts)
