"""All-industry direction table and rule-based classification (no network, no model).

Each direction has Chinese `keywords` (title/body phrases), English `en` phrases for English
boards, and example `titles`. A phrase may join parts with '&' (all parts must appear in the
same text): '产品经理&ai' matches 'AI 产品经理' and 'Product Manager, AI' but not '大模型算法工程师'.
Text is NFKC-folded and lower-cased. Phrases containing Chinese are searched with whitespace
removed ('AI 产品经理' == 'AI产品经理'); pure ASCII phrases need word boundaries ('sre' is not in
'misrepresent'; 'back-end' reads as 'back end').

rule_match scores each allowed direction in 0..1, deterministically:
  title part  0.6 for the first phrase hit in the title (Chinese or English alike),
              +0.1 per further distinct hit (at most +0.2),
              +0.2 x (share of the title covered by the direction name or an example title found in
              it): '管理会计' fully covers its own name but only half of 会计, so it outranks accountant;
              capped at 1.
  body part   0.15 per distinct phrase hit in the job text, capped at 0.45.
  score       title part + min(body part, 0.2) when the title hit; body part alone otherwise.
A body-only match therefore stays below 0.5, the threshold callers use to accept a rule result,
so a direction needs a title hit to be assigned. Equal scores go to the direction whose best title hit
has more '&' parts, then more letters ('product manager&ai' beats 'senior product manager'), then to the earlier `allowed`.
Job text is data: it is only searched for these phrases, never interpreted.
"""
import copy
import functools
import json
import re
import unicodedata
from pathlib import Path

DATA = Path(__file__).resolve().parent / 'data' / 'directions.cn.json'
MAX_BODY = 20000
MAX_SUGGEST = 6
TITLE_BASE, TITLE_EXTRA, TITLE_EXTRA_CAP, TITLE_NAME, BODY_EACH, BODY_CAP, BODY_WITH_TITLE = 0.6, 0.1, 0.2, 0.2, 0.15, 0.45, 0.2
_CJK = re.compile(r'[㐀-鿿]')


@functools.lru_cache(maxsize=1)
def _rows():
    return tuple(json.loads(DATA.read_text(encoding='utf-8'))['directions'])


def load():
    return copy.deepcopy(list(_rows()))


def get(ident):
    for row in _rows():
        if row['id'] == ident:
            return copy.deepcopy(row)
    raise KeyError(ident)


def _fold(text):
    text = unicodedata.normalize('NFKC', str(text or '')).casefold()
    return re.sub(r'<[^>]{1,200}>', ' ', text)


class _Text:
    """One text in the two shapes phrases are searched in."""
    def __init__(self, value):
        folded = _fold(value)
        self.tight = re.sub(r'\s+', '', folded)
        self.spaced = re.sub(r'[^0-9a-z+#㐀-鿿]+', ' ', folded)


def _pattern(part):
    """(regex, uses_tight_text) for one '&'-free phrase."""
    folded = _fold(part)
    tight = bool(_CJK.search(folded))
    body = re.sub(r'\s+', '', folded) if tight else re.sub(r'[^0-9a-z+#]+', ' ', folded).strip()
    before = r'(?<![0-9a-z])' if body[:1].isascii() and body[:1].isalnum() else ''
    after = r'(?![0-9a-z])' if body[-1:].isascii() and body[-1:].isalnum() else ''
    return re.compile(before + re.escape(body) + after), tight


@functools.lru_cache(maxsize=None)
def _compiled(phrase):
    return tuple(_pattern(part) for part in phrase.split('&') if part.strip())


def _hit(phrase, text):
    parts = _compiled(phrase)
    return bool(parts) and all(rx.search(text.tight if tight else text.spaced) for rx, tight in parts)


def _hits(row, text):
    """Distinct phrase hits; a phrase inside a longer hit ('product manager' in 'senior product manager') is the same evidence."""
    found = [p for p in dict.fromkeys(row['keywords'] + row['en']) if _hit(p, text)]
    keys = {p: re.sub(r'[^0-9a-z+#\u3400-\u9fff]', '', _fold(p)) for p in found}
    single = [p for p in found if '&' not in p]

    def covered(p):
        # An equal key is dropped only when an earlier phrase has it, so one of the two stays.
        return any(keys[p] in keys[q] and (keys[p] != keys[q] or single.index(q) < single.index(p)) for q in single if q != p)
    return [p for p in found if '&' in p or not covered(p)]


def _names(row):
    name = re.sub(r'[（(].*?[）)]', '', row['name'])
    return [n for n in (re.sub(r'\s+', '', _fold(x)) for x in [name] + row['titles']) if n]


def rule_match(title, jd, allowed):
    """[(direction_id, score)] for allowed directions with score > 0, best first; see module docstring."""
    by_id = {r['id']: r for r in _rows()}
    title_text, body_text = _Text(title), _Text(str(jd or '')[:MAX_BODY])
    result = []
    for order, ident in enumerate(dict.fromkeys(i for i in (allowed or []) if isinstance(i, str) and i in by_id)):
        row = by_id[ident]
        in_title, in_body = _hits(row, title_text), _hits(row, body_text)
        body = min(BODY_CAP, BODY_EACH * len(in_body))
        if in_title:
            score = TITLE_BASE + min(TITLE_EXTRA_CAP, TITLE_EXTRA * (len(in_title) - 1))
            cover = max((len(n) for n in _names(row) if n in title_text.tight), default=0)
            score += TITLE_NAME * cover / max(len(title_text.tight), 1)
            score = min(1.0, score + min(body, BODY_WITH_TITLE))
        else:
            score = body
        if score > 0:
            longest = max(((p.count('&'), len(p)) for p in in_title), default=(0, 0))
            result.append((ident, round(score, 3), longest, order))
    result.sort(key=lambda r: (-r[1], tuple(-x for x in r[2]), r[3]))
    return [(i, s) for i, s, _, _ in result]


def suggest_from_profile(profile):
    """Up to six direction ids from confirmed skills, experience and education text.

    Counts distinct phrase hits; skills and experience weigh 1, education 0.5 (a degree says
    what was studied, not what to apply for). Unconfirmed items and anything unreadable are
    skipped. Ties keep table order.
    """
    if not isinstance(profile, dict):
        return []

    def texts(key, field):
        rows = profile.get(key)
        rows = rows if isinstance(rows, list) else []
        return ' \n '.join(str(r[f]) for r in rows if isinstance(r, dict) and r.get('status') == 'confirmed'
                           for f in field if isinstance(r.get(f), str))
    work = _Text(texts('skills', ('name', 'label')) + ' \n ' + texts('experience', ('text',)))
    study = _Text(texts('education', ('text',)))
    scored = []
    for order, row in enumerate(_rows()):
        score = len(_hits(row, work)) + 0.5 * len(_hits(row, study))
        if score > 0:
            scored.append((-score, order, row['id']))
    return [ident for _, _, ident in sorted(scored)[:MAX_SUGGEST]]
