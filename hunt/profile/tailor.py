"""Per-job résumé tailoring, core and rule path (docs/v2-tailoring-design.md, sections 4–6).

A tailored résumé is the confirmed facts plus a list of edits; no text is stored on its own. This module
proposes edits without a model (``propose``), applies the accepted ones through four gates (``apply_edits``),
checks the result (``check_result``) and proves every output line traces to a confirmed fact (``trace``).
It reads the résumé structure only as the JSON of section 4.3 and takes the ``job_match`` result as an argument,
so it imports neither ``profile.structure`` nor ``ai.match``.

Ported from Resume-Matcher (https://github.com/srbhr/Resume-Matcher, commit e2a32b6823bb7f5996cafdf007b6ba6f0efd8f98,
Apache-2.0, ``apps/backend/app/services/improver.py``): the gate order of ``apply_diffs`` (allowed operation, blocked
identity targets, original text must match, reorder must keep the same set) and the checks of ``verify_diff_result``
(section counts, identity fields, size ratio, new metrics; ``_METRIC_RE`` is widened to Chinese quantifiers). Modified:
rewritten in Python for this project's fact ids and edit records instead of resume JSON paths, ratio 1.8 -> 1.5 per
line, the ``add_skill`` / ``jd_added`` path is not ported. See THIRD_PARTY_NOTICES.md.
"""
import hashlib
import json
import re
import unicodedata

from .claims import SYNONYMS

OPS = ('reorder', 'hide', 'alias', 'rephrase')
GROWTH = 1.5

_DEGREE = re.compile(r'本科|硕士|博士|学士|大专|专科|研究生|学历|学位|毕业|GPA', re.I)
_RANGE = re.compile(r'\d{4}\s*[./年-]\s*\d{1,2}\s*月?\s*[-–—~～至到]+\s*(?:\d{4}|至今|现在|今)')
_CONTACT = re.compile(r'(?:姓名|邮箱|电话|手机|微信|联系方式|e-?mail)\s*[:：]|[\w.+-]+@[\w-]+\.[\w.]+|(?<!\d)1[3-9]\d{9}(?!\d)|https?://|www\.', re.I)
_NUMBER = re.compile(r'(?<![A-Za-z\d.])(?:Top\s*\d+|第\s*[一二三四五六七八九十\d]+\s*名|\d+(?:\.\d+)?\s*(?:%|％|倍|万|亿|个月|年|人|家|次|x|X|[+＋])?'
                     r'|[一二三四五六七八九十百千两]+\s*(?:%|倍|万|亿|个月|年|人|家|次))', re.I)


def _nfkc(text):
    return unicodedata.normalize('NFKC', str(text)).strip()


def _tight(text):
    return re.sub(r'\s+', '', _nfkc(text)).casefold()


def _same(a, b):
    return isinstance(a, str) and isinstance(b, str) and _nfkc(a) == _nfkc(b)


def _ref(fact):
    return dict(id=fact['id'], version=fact.get('version', 1))


def _confirmed(facts):
    return {f['id']: f for f in facts or [] if isinstance(f, dict) and isinstance(f.get('id'), str)
            and isinstance(f.get('text'), str) and f.get('status') == 'confirmed'}


# ---- synonyms -------------------------------------------------------------------------------------------------

def _group(word):
    return next((g for g in SYNONYMS if any(_tight(word) == _tight(w) for w in g)), None)


def equivalent(a, b):
    """True when two wordings are in the same whitelist group (and so may replace each other)."""
    group = _group(a)
    return bool(group) and _tight(a) != _tight(b) and any(_tight(b) == _tight(w) for w in group)


def _pattern(word):
    body = re.escape(word)
    return re.compile(r'(?<![A-Za-z0-9])' + body + r'(?![A-Za-z0-9])', re.I) if word.isascii() else re.compile(body)


def _has(text, word):
    return bool(_pattern(word).search(text))


def _swap(text, old, new):
    return _pattern(old).sub(lambda _m: new, text)


# ---- layout: the 4.3 structure resolved against the current facts ----------------------------------------------

def _layout(facts, structure):
    """Sections -> entries with resolved facts. An entry is `stale` when the structure says so or any reference
    is not a confirmed fact at the recorded version; stale entries are passed through verbatim (design 4.3)."""
    by_id = _confirmed(facts)
    sections = []
    for sec in (structure or {}).get('sections') or []:
        title = by_id.get((sec.get('title_fact') or {}).get('id'))
        entries = []
        for ent in sec.get('entries') or []:
            refs = ([ent.get('head')] if ent.get('head') else []) + list(ent.get('bullets') or [])
            stale = ent.get('status') == 'stale'
            for r in refs:
                f = by_id.get((r or {}).get('id'))
                if f is None or f.get('version', 1) != r.get('version'):
                    stale = True
            head = by_id.get((ent.get('head') or {}).get('id'))
            bullets = [by_id[r['id']] for r in ent.get('bullets') or [] if r.get('id') in by_id]
            entries.append(dict(id=ent.get('id'), stale=stale, head=head, bullets=bullets))
        sections.append(dict(id=sec.get('id'), key=sec.get('key'), title=title, entries=entries))
    return sections


def _targets(layout):
    """fact id -> (section, entry) for every editable bullet (valid entries only)."""
    out = {}
    for sec in layout:
        for ent in sec['entries']:
            if not ent['stale']:
                for f in ent['bullets']:
                    out[f['id']] = (sec, ent)
    return out


def editable(facts, structure):
    """The confirmed facts an alias or rephrase may target: bullets of valid entries that are not identity lines."""
    return [f for sec in _layout(facts, structure) for ent in sec['entries'] if not ent['stale']
            for f in ent['bullets'] if not _is_identity(f, sec['key'])]


def gate(facts, structure, edit):
    """Reason `apply_edits` would refuse this edit on its own, or None."""
    return _gate(edit, _confirmed(facts), _targets(_layout(facts, structure)))


def _is_identity(fact, section_key):
    text = fact['text']
    return (section_key in ('education', 'header', 'basic') or bool(set(fact.get('tags') or []) & {'identity', 'contact'})
            or bool(_DEGREE.search(text) or _RANGE.search(text) or _CONTACT.search(text)))


def _split_skills(text):
    """('技能：', ['Python', 'SQL']) for a one-line skill list joined by 、, else None."""
    m = re.match(r'^([^：:]{1,12}[：:])(.+)$', text.strip())
    if not m:
        return None
    items = m[2].split('、')
    if len(items) < 2 or any(not i.strip() for i in items) or m[1] + '、'.join(items) != text.strip():
        return None
    return m[1], items


# ---- render ---------------------------------------------------------------------------------------------------

def _line(text, kind, facts_, sec, ent=None, edit_ids=()):
    return dict(text=text, kind=kind, fact_ids=[_ref(f) for f in facts_], edit_ids=list(edit_ids),
                section=sec['id'], entry=ent['id'] if ent else None)


def _render(layout, structure, plan=None):
    """Rendered résumé: sections of lines. `plan` carries what the gates accepted (order, hidden, text per fact)."""
    plan = plan or dict(order={}, hidden={}, text={}, merge={})
    sections = []
    for sec in layout:
        lines = [_line(sec['title']['text'], 'title', [sec['title']], sec)] if sec['title'] else []
        for ent in sec['entries']:
            if ent['head']:
                lines.append(_line(ent['head']['text'], 'head', [ent['head']], sec, ent))
            bullets = plan['order'].get(ent['id'], ent['bullets']) if not ent['stale'] else ent['bullets']
            merged_done = set()
            for f in bullets:
                if f['id'] in plan['hidden']:
                    continue
                if f['id'] in plan['merge']:
                    key = plan['merge'][f['id']]
                    if key in merged_done:
                        continue
                    merged_done.add(key)
                    edit, cited = plan['text'][key]
                    for text in edit['after'].split('\n'):
                        lines.append(_line(text, 'bullet', cited, sec, ent, [edit['id']]))
                elif f['id'] in plan['text']:
                    edit, cited = plan['text'][f['id']]
                    for text in edit['after'].split('\n'):
                        lines.append(_line(text, 'bullet', cited, sec, ent, [edit['id']]))
                else:
                    lines.append(_line(f['text'], 'bullet', [f], sec, ent, plan.get('order_edit', {}).get(ent['id'], ())))
        sections.append(dict(id=sec['id'], key=sec['key'], lines=lines))
    return dict(structure_version=(structure or {}).get('version'), sections=sections)


# ---- gates (Resume-Matcher apply_diffs, section 6.1) ---------------------------------------------------------

def _gate(edit, by_id, targets):
    """Reason the edit is refused, or None. Gate order follows apply_diffs: allowed operation, blocked targets,
    the target exists, the original text matches, reorder keeps the same set."""
    if not isinstance(edit, dict) or not isinstance(edit.get('id'), str):
        return 'malformed'
    op, refs = edit.get('op'), edit.get('fact_ids')
    if op not in OPS:  # gate 1
        return 'op_not_allowed'
    if not isinstance(refs, list) or not refs or any(not isinstance(r, dict) for r in refs):
        return 'malformed'
    ids = [r.get('id') for r in refs]
    if len(set(ids)) != len(ids):
        return 'duplicate_fact'
    for r in refs:
        fact = by_id.get(r.get('id'))
        if fact is None:
            return 'not_confirmed'
        if fact.get('version', 1) != r.get('version'):
            return 'stale_fact'
    if any(i not in targets for i in ids):
        return 'unknown_target'  # not an editable bullet: heads, titles, stale entries, unassigned facts
    sec, ent = targets[ids[0]]
    if any(targets[i][1] is not ent for i in ids):
        return 'cross_entry'
    facts_ = [by_id[i] for i in ids]
    texts = [f['text'] for f in facts_]
    before, after = edit.get('before'), edit.get('after')
    if op in ('alias', 'rephrase') and any(_is_identity(f, sec['key']) for f in facts_):  # gate 2
        return 'identity_line'
    if op == 'reorder' and len(ids) > 1:
        if set(ids) != {f['id'] for f in ent['bullets']} or len(ids) != len(ent['bullets']):
            return 'reorder_set_mismatch'
        original = [f['text'] for f in ent['bullets']]
        if not _same(before, '\n'.join(original)):
            return 'before_mismatch'
        if not _same(after, '\n'.join(texts)):
            return 'reorder_set_mismatch'
        return None
    if op == 'reorder':  # one-line skill list: items move, the set does not
        if not _same(before, texts[0]):
            return 'before_mismatch'
        old, new = _split_skills(texts[0]), _split_skills(after) if isinstance(after, str) else None
        if not old or not new or old[0] != new[0] or sorted(old[1]) != sorted(new[1]):
            return 'reorder_set_mismatch'
        return None
    if op == 'hide':
        return None if _same(before, texts[0]) and len(ids) == 1 and after is None else ('before_mismatch' if len(ids) == 1 else 'malformed')
    if op == 'alias':
        if len(ids) != 1 or not _same(before, texts[0]):  # gate 3
            return 'before_mismatch'
        value = (edit.get('requirement') or {}).get('value')
        group = _group(value) if isinstance(value, str) else None
        ok = isinstance(after, str) and group and any(_tight(t) != _tight(value) and _has(texts[0], t) and _swap(texts[0], t, value) == after
                                                      for t in group)
        return None if ok else 'alias_not_whitelisted'
    if not _same(before, '\n'.join(texts)):  # rephrase
        return 'before_mismatch'
    if not isinstance(after, str) or not after.strip() or any(not l.strip() for l in after.split('\n')):
        return 'after_missing'
    return None


def apply_edits(facts, structure, edits, statuses=('accepted',)):
    """Apply the edits whose status is in `statuses` and return dict(rendered, applied, rejected_by_gate, hidden).

    Each edit goes through the four gates of design 6.1. A refused edit goes to `rejected_by_gate` as
    {edit, reason}; reasons: malformed, op_not_allowed, not_confirmed, stale_fact, duplicate_fact, unknown_target,
    cross_entry, identity_line, before_mismatch, reorder_set_mismatch, alias_not_whitelisted, after_missing,
    conflict. Two edits may not change the same fact's text or position."""
    layout = _layout(facts, structure)
    by_id, targets = _confirmed(facts), _targets(layout)
    plan = dict(order={}, hidden={}, text={}, merge={}, order_edit={})
    applied, rejected, claimed = [], [], set()
    for edit in edits or []:
        if not isinstance(edit, dict) or edit.get('status') not in statuses:
            continue
        reason = _gate(edit, by_id, targets)
        ids = [r['id'] for r in edit.get('fact_ids') or [] if isinstance(r, dict) and 'id' in r] if not reason else []
        block = edit.get('op') == 'reorder' and len(ids) > 1
        keys = [('order', targets[ids[0]][1]['id'])] if block else [('fact', i) for i in ids]
        if not reason and any(k in claimed for k in keys):
            reason = 'conflict'
        if reason:
            rejected.append(dict(edit=edit, reason=reason))
            continue
        claimed.update(keys)
        applied.append(edit)
        op = edit['op']
        if block:
            plan['order'][targets[ids[0]][1]['id']] = [by_id[i] for i in ids]
            plan['order_edit'][targets[ids[0]][1]['id']] = [edit['id']]
        elif op == 'hide':
            plan['hidden'][ids[0]] = edit['id']
        else:  # alias, rephrase, or a skill-list reorder: the line's text comes from `after`
            plan['text'][ids[0]] = (edit, [by_id[i] for i in ids])
            plan['merge'].update({i: ids[0] for i in ids} if len(ids) > 1 else {})
    return dict(rendered=_render(layout, structure, plan), applied=[e['id'] for e in applied], rejected_by_gate=rejected,
                hidden=dict(plan['hidden']))


def refresh_status(facts, edits):
    """Edits whose cited facts changed version or are no longer confirmed become `stale` (design 4.2)."""
    by_id, out = _confirmed(facts), []
    for edit in edits or []:
        edit = dict(edit)
        if edit.get('status') != 'rejected' and any(
                by_id.get(r.get('id')) is None or by_id[r['id']].get('version', 1) != r.get('version') for r in edit.get('fact_ids') or []):
            edit['status'] = 'stale'
        out.append(edit)
    return out


# ---- after-checks (Resume-Matcher verify_diff_result, section 6.2) --------------------------------------------

def _numbers(text):
    return {re.sub(r'\s+', '', m).casefold() for m in _NUMBER.findall(_nfkc(text))}


def _skeleton(rendered):
    return {(s['id'], e) for s in rendered['sections'] for e in {l['entry'] for l in s['lines'] if l['entry']}} | {(s['id'], None) for s in rendered['sections']}


def check_result(facts, structure, rendered, edits=()):
    """Local checks on an applied result: dict(ok, problems[{code, line?, detail}]).

    block_count: sections and entries are the ones the structure has; identity: title and head lines are the
    fact text; growth: no line longer than 1.5x the facts it cites; new_number: no number or quantity
    (including 中文量词) that the cited facts do not contain."""
    by_id, problems = _confirmed(facts), []
    base = _render(_layout(facts, structure), structure)
    if _skeleton(rendered) != _skeleton(base):
        problems.append(dict(code='block_count', detail='章节或条目的数量与简历结构不一致'))
    for sec in rendered['sections']:
        for line in sec['lines']:
            cited = [by_id[r['id']] for r in line['fact_ids'] if r['id'] in by_id]
            source = '\n'.join(f['text'] for f in cited)
            if line['kind'] in ('title', 'head') and not (len(cited) == 1 and _same(line['text'], source)):
                problems.append(dict(code='identity', line=line['text'], detail='章节标题或条目头被改动'))
            if not line['edit_ids'] or _same(line['text'], source):
                continue
            if source and len(_nfkc(line['text'])) > GROWTH * len(_nfkc(source)):
                problems.append(dict(code='growth', line=line['text'], detail='改写后的行超过原文的 1.5 倍'))
            digits = set(re.findall(r'\d+', _nfkc(source)))
            # a year the facts write as 2021.03 may be written 2021年
            new = {n for n in _numbers(line['text']) - _numbers(source) if not (re.fullmatch(r'(?:19|20)\d\d年', n) and n[:4] in digits)}
            if new:
                problems.append(dict(code='new_number', line=line['text'], detail='原文没有的数字或量词：' + '、'.join(sorted(new))))
    return dict(ok=not problems, problems=problems)


# ---- trace (section 3, rule 1) -------------------------------------------------------------------------------

def trace(facts, rendered, edits):
    """Every output line is either verbatim a confirmed fact, or carries an accepted edit that cites confirmed facts at
    their current version and whose `after` contains the line. Returns dict(status 'pass'|'fail', problems, lines);
    `lines` is the trace.json body: text, fact ids with versions, edit ids."""
    by_id = _confirmed(facts)
    edit_by_id = {e.get('id'): e for e in edits or [] if isinstance(e, dict)}
    problems, out = [], []
    for sec in rendered['sections']:
        for line in sec['lines']:
            refs, text = line.get('fact_ids') or [], line['text']
            out.append(dict(text=text, fact_ids=refs, edit_ids=line.get('edit_ids') or [], section=sec['id']))
            if not refs:
                problems.append(dict(code='no_fact', line=text))
                continue
            if any(r.get('id') not in by_id or by_id[r['id']].get('version', 1) != r.get('version') for r in refs):
                problems.append(dict(code='fact_not_current', line=text))
                continue
            if len(refs) == 1 and _same(text, by_id[refs[0]['id']]['text']):
                if any(edit_by_id.get(i, {}).get('status') != 'accepted' for i in line.get('edit_ids') or []):
                    problems.append(dict(code='edit_not_accepted', line=text))
                continue
            cited = {r['id'] for r in refs}
            ok = False
            for eid in line.get('edit_ids') or []:
                edit = edit_by_id.get(eid)
                if (edit and edit.get('status') == 'accepted' and isinstance(edit.get('after'), str) and edit.get('op') in ('alias', 'rephrase', 'reorder')
                        and cited <= {r.get('id') for r in edit.get('fact_ids') or []}
                        and any(_same(text, l) for l in edit['after'].split('\n'))):
                    ok = True
            if not ok:
                problems.append(dict(code='unsupported_line', line=text))
    return dict(status='fail' if problems else 'pass', problems=problems, lines=out)


# ---- rule path (section 5.1) ----------------------------------------------------------------------------------

def requirements(match, keywords=('explicit',)):
    """(requirement dict, fact ids serving it) in priority order: met hard conditions, keywords whose coverage is in
    `keywords`, supported or related duties. The refs (h<i>, k<i>, d<i>) index the match lists, so the rule path and the
    AI path name the same requirement the same way."""
    rows = []
    for i, r in enumerate((match or {}).get('hard') or []):
        if r.get('status') == 'met':
            rows.append((dict(type='hard', value=r.get('requirement'), jd_evidence=r.get('jd_evidence'), ref=f'h{i}'), list(r.get('fact_ids') or [])))
    for i, r in enumerate((match or {}).get('keywords') or []):
        if r.get('coverage') in keywords:
            rows.append((dict(type='keyword', value=r.get('keyword'), jd_evidence=r.get('jd_evidence'), ref=f'k{i}'), list(r.get('fact_ids') or [])))
    for i, r in enumerate((match or {}).get('evidence') or []):
        if r.get('status') in ('supported', 'related'):
            ids = r.get('fact_ids') if r.get('status') == 'supported' else r.get('related_fact_ids')
            rows.append((dict(type='duty', value=r.get('requirement'), jd_evidence=r.get('jd_evidence'), ref=f'd{i}'), list(ids or [])))
    return rows


def match_digest(match):
    rows = {k: (match or {}).get(k) or [] for k in ('hard', 'keywords', 'evidence')}
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]


def _gaps(match, aliased):
    gaps = []
    for i, r in enumerate((match or {}).get('keywords') or []):
        cov = r.get('coverage')
        if cov == 'absent' or (cov == 'related' and i not in aliased):
            gaps.append(dict(type=cov, requirement=r.get('keyword'), jd_evidence=r.get('jd_evidence'), related_terms=list(r.get('related_terms') or []),
                             fact_ids=list(r.get('related_fact_ids') or []), ref=f'k{i}'))
    for i, r in enumerate((match or {}).get('hard') or []):
        if r.get('status') in ('not_met', 'unknown'):
            gaps.append(dict(type='hard_' + r['status'], requirement=r.get('requirement'), jd_evidence=r.get('jd_evidence'), related_terms=[],
                             fact_ids=list(r.get('fact_ids') or []), ref=f'h{i}'))
    return gaps


def propose(facts, structure, match, line_limit=None):
    """Rule-path edits and gaps: dict(edits, gaps). Edits are by 'rules' and 'accepted' (they add no text).

    reorder: bullets inside one entry by how many job requirements they serve, ties keep their order; a one-line
    skill list moves the job's named items first. alias: a fact's wording replaced by the job's word only when both
    are in SYNONYMS. hide: only when `line_limit` (max output lines) is given and exceeded, oldest zero-relevance
    bullets first. Stale entries and unassigned facts are never touched."""
    layout, reqs = _layout(facts, structure), requirements(match)
    served = {}
    for req, ids in reqs:
        for i in ids:
            served.setdefault(i, []).append(req)
    edits, counter = [], [0]

    def make(op, fs, requirement, before, after, why):
        counter[0] += 1
        edits.append(dict(id=f'e{counter[0]}', op=op, fact_ids=[_ref(f) for f in fs], requirement=requirement, before=before, after=after,
                          why=why, by='rules', status='accepted', checks=dict(hard='pass', flags=[], reviewer=None)))

    aliased, touched = set(), set()
    for i, r in enumerate((match or {}).get('keywords') or []):  # alias first: it claims the fact's text
        if r.get('coverage') != 'related':
            continue
        word = r.get('keyword') or ''
        for sec in layout:
            for ent in sec['entries']:
                if ent['stale']:
                    continue
                for f in ent['bullets']:
                    if f['id'] not in (r.get('related_fact_ids') or []) or f['id'] in touched or _is_identity(f, sec['key']):
                        continue
                    term = next((t for t in r.get('related_terms') or [] if equivalent(t, word) and _has(f['text'], t)), None)
                    if term:
                        after = _swap(f['text'], term, word)
                        if after != f['text']:
                            req = dict(type='keyword', value=word, jd_evidence=r.get('jd_evidence'), ref=f'k{i}')
                            make('alias', [f], req, f['text'], after, f'把「{term}」换成岗位原词「{word}」，ATS 的字面匹配才认得')
                            aliased.add(i)
                            touched.add(f['id'])
    keywords = [(i, r) for i, r in enumerate((match or {}).get('keywords') or []) if r.get('coverage') == 'explicit']
    for sec in layout:
        for ent in sec['entries']:
            if ent['stale'] or len(ent['bullets']) < 1 or sec['key'] in ('basic', 'header'):  # contact lines keep their order
                continue
            for f in ent['bullets']:  # items of a one-line skill list
                parts = _split_skills(f['text']) if f['id'] not in touched else None
                if not parts:
                    continue
                prefix, items = parts
                named = [(next(((i, r) for i, r in keywords if _tight(r['keyword']) == _tight(it)), None)) for it in items]
                order = [n for n in range(len(items)) if named[n]] + [n for n in range(len(items)) if not named[n]]
                if order != list(range(len(items))):
                    first = next(named[n] for n in order if named[n] and order.index(n) != n)
                    k, r = first
                    after = prefix + '、'.join(items[n] for n in order)
                    make('reorder', [f], dict(type='keyword', value=r['keyword'], jd_evidence=r.get('jd_evidence'), ref=f'k{k}'), f['text'], after,
                         '把岗位点名的技能提前，技能的集合不变')
                    touched.add(f['id'])
            old = ent['bullets']
            new = sorted(old, key=lambda f: -len(served.get(f['id'], [])))  # stable: ties keep their order
            if [f['id'] for f in new] != [f['id'] for f in old] and len(old) > 1:
                moved = next(f for n, f in enumerate(new) if f is not old[n])
                req = (served.get(moved['id']) or [None])[0]
                make('reorder', new, req, '\n'.join(f['text'] for f in old), '\n'.join(f['text'] for f in new), '把和岗位要求相关的条目提前，条目内容不变')
    if line_limit:
        _hide(layout, served, edits, make, int(line_limit))
    return dict(edits=edits, gaps=_gaps(match, aliased))


def _hide(layout, served, edits, make, limit):
    hidden = {e['fact_ids'][0]['id'] for e in edits if e['op'] == 'hide'}
    total = sum((1 if s['title'] else 0) + sum((1 if e['head'] else 0) + len(e['bullets']) for e in s['entries']) for s in layout)
    entries = [(s, e) for s in layout for e in s['entries'] if not e['stale'] and s['key'] not in ('education', 'header', 'basic')]
    for sec, ent in reversed(entries):  # sections run newest to oldest, so the last entries are the oldest
        for f in reversed(ent['bullets']):
            if total <= limit:
                return
            if not served.get(f['id']) and f['id'] not in hidden:
                make('hide', [f], None, f['text'], None, '超出页数上限：隐藏与这个岗位要求无关、最旧的条目')
                hidden.add(f['id'])
                total -= 1


def build(job_id, version, facts, structure, match, jd_digest='', created_at=None, line_limit=None):
    """A section 4.1 document for the rule path, with the trace check filled in (`checks.trace` pass|fail)."""
    out = propose(facts, structure, match, line_limit)
    applied = apply_edits(facts, structure, out['edits'])
    result = trace(facts, applied['rendered'], out['edits'])
    after = check_result(facts, structure, applied['rendered'], out['edits'])
    by_id = _confirmed(facts)
    used = sorted({r['id'] for e in out['edits'] for r in e['fact_ids']} | {r['id'] for l in result['lines'] for r in l['fact_ids']})
    return dict(schema_version=1, id=f'tl-{job_id}-v{version}', job_id=job_id, version=version, created_at=created_at, by='rules', model=None,
                base=dict(facts=[_ref(by_id[i]) for i in used if i in by_id], jd_digest=jd_digest, match_digest=match_digest(match)),
                structure=dict(version=(structure or {}).get('version')), edits=out['edits'], gaps=out['gaps'],
                rejected_by_gate=applied['rejected_by_gate'],
                checks=dict(trace=result['status'], result='pass' if after['ok'] else 'fail', export=None))
