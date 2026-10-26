"""Strip contact details from resume text before it may leave the machine.

Matching runs on a width-normalised copy (full-width digits, @, colon, dashes), but the replacement is applied to the
original text, so everything that is not a match keeps its exact wording. Bias: a false positive on a contact-like
string costs a little context; a miss leaks personal data. Company names, roles, skills, dates and metrics must survive.
"""
import re

_DASHES = dict.fromkeys(map(ord, '‐‑‒–−﹣'), '-')


def _fold(text):
    out = []
    for ch in text.translate(_DASHES):
        code = ord(ch)
        out.append(chr(code - 0xFEE0) if 0xFF01 <= code <= 0xFF5E else ' ' if code == 0x3000 else ch)
    return ''.join(out)  # one character in, one out: spans found here index the original text


_SEP = r'[ \-.]{0,2}'
_PHONE = (r'(?<!\d)(?:(?:[(]?\+\s*86[)]?|0086|(?<!\d)86(?=[ \-]+1[3-9]))[ \-.]*)?1[3-9](?:'
          rf'\d{_SEP}\d{{4}}{_SEP}\d{{4}}|\d{{2}}{_SEP}\d{{3}}{_SEP}\d{{4}}|\d{_SEP}\d{{3}}{_SEP}\d{{5}})(?!\d)')
_LANDLINE = r'(?<!\d)0\d{2,3}[ \-]\d{7,8}(?!\d)'
_EMAIL = r'[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+'
_ID = r'(?<![0-9A-Za-z])\d{6}[ \-]?(?:19|20)\d{2}[ \-]?\d{2}[ \-]?\d{2}[ \-]?\d{3}[\dXx](?![0-9A-Za-z])'
_ID_LABEL = r'(?:身份证(?:号码?)?|证件号码?|ID\s*(?:No|Number)\.?)\s*[:：]?\s*(\d[\dXx \-]{12,21}[\dXx])'
_PHONE_LABEL = r'(?:手机(?:号码?)?|联系电话|电话|联系方式|Tel|Phone|Mobile|Cell)\s*[:：]?\s*(\+?\d[\d \-.()]{5,}\d)'
_SOCIAL = (r'((?:微信号?|WeChat|Weixin|wx|vx|QQ(?:号码?|号)?)(?:\s*[/、&]\s*(?:微信号?|WeChat|QQ(?:号)?))*)'
           r'(\s*[:：]\s*|\s+)([A-Za-z0-9_\-]{5,30})(?![A-Za-z0-9_\-])')
# Name fields only at the start of a line or after a field separator, so "Company Name: ..." is left alone.
_NAME_FIELD = (r'(?:^|(?<=[|｜,，;；\t])|(?<=\s\s))\s*(?:真实姓名|姓\s*名|名字|Full\s*Name|Name)\s*[:：]\s*'
               r"([一-鿿·]{2,6}|[A-Za-z][A-Za-z.\-']*(?: [A-Za-z][A-Za-z.\-']*){0,3})")
_ADMIN = (r'(?:[一-鿿]{2,5}?(?:省|自治区))?(?:[一-鿿]{2,4}?市)?(?:[一-鿿]{1,4}?(?:区|县|旗))?'
          r'(?:[一-鿿]{1,5}?(?:镇|乡|街道))?')
_UNIT = (r'(?:院|\d+号院)?(?:\d+(?:号楼|栋|幢|座|单元|层|楼|室|房|号)|[A-Za-z]座)*(?:\d{2,4}(?!\d))?')
_ADDRESS = [
    rf'{_ADMIN}[一-鿿A-Za-z0-9]{{1,8}}?(?:路|大街|街|大道|巷|弄)\d+(?:-\d+)?号{_UNIT}',
    r'(?:[一-鿿]{2,10}(?:小区|园|公寓|苑|府|大厦|广场))?\d+(?:号楼|栋|幢|座)(?:\d+单元)?(?:\d{1,4}室?)?',
    r'\d+单元\d{0,4}室?',
    r'(?<![\d])\d{2,4}室',
]
_ADDRESS_LABEL = r'(?:家庭住址|通讯地址|联系地址|现住址|住址|居住地|现居地?|地址)\s*[:：]?\s*([^\n，,;；。|｜]{4,60})'
_ADDRESS_DETAIL = re.compile(r'[路街巷弄号室栋幢楼院层]|\d')

_TITLES = {'简历', '个人简历', '求职简历', '中文简历', '个人资料', 'resume', 'cv', 'curriculum vitae'}
_HEADING_END = ('简历', '经历', '经验', '背景', '技能', '评价', '信息', '意向', '简介', '方式', '总结', '介绍', '奖项',
                '证书', '荣誉', '概述', '优势', '项目', '教育', '特长', '爱好', '奖励', '培训', '语言', '资料', '履历')
_HAN_NAME = re.compile(r'[一-鿿]{2,4}')


def _is_title(line):
    return line.strip().strip('-=_*# ').lower() in _TITLES


def _spans(text, top):
    """Return (start, end, replacement) spans, earlier rules winning where they overlap."""
    folded = _fold(text)
    found = []

    def add(pattern, repl, group=0, flags=0):
        for m in re.finditer(pattern, folded, flags):
            if m.start(group) < m.end(group):
                found.append((m.start(group), m.end(group), repl(m) if callable(repl) else repl))

    add(_EMAIL, '[邮箱]')
    add(_ID, '[身份证号]')
    add(_ID_LABEL, '[身份证号]', 1, re.I)
    add(_PHONE_LABEL, '[手机号]', 1, re.I)
    add(_PHONE, '[手机号]')
    add(_LANDLINE, '[电话]')
    for m in re.finditer(_SOCIAL, folded, re.I):
        ident = m.group(3)
        if m.group(2).strip() or any(c.isdigit() for c in ident):  # "WeChat Official Account" has no colon or digit
            found.append((m.start(3), m.end(3), '[QQ号]' if m.group(1).upper().endswith(('QQ', 'QQ号', 'QQ号码')) else '[微信号]'))
    add(_NAME_FIELD, '[姓名]', 1, re.I | re.M)
    for m in re.finditer(_ADDRESS_LABEL, folded):
        if _ADDRESS_DETAIL.search(m.group(1)):
            found.append((m.start(1), m.end(1), '[地址]'))
    for pattern in _ADDRESS:
        add(pattern, '[地址]')
    if top:
        pos = 0
        for line in folded.split('\n'):
            stripped = line.strip()
            if stripped and not _is_title(stripped):
                if _HAN_NAME.fullmatch(stripped) and not stripped.endswith(_HEADING_END):
                    start = pos + line.index(stripped)
                    found.append((start, start + len(stripped), '[姓名]'))
                break
            pos += len(line) + 1
    kept = []
    for span in found:
        if all(span[1] <= k[0] or span[0] >= k[1] for k in kept):
            kept.append(span)
    return sorted(kept)


def _apply(text, top):
    out, pos = [], 0
    for start, end, repl in _spans(text, top):
        out += [text[pos:start], repl]
        pos = end
    return ''.join(out) + text[pos:]


def redact(text: str) -> str:
    return _apply(text, True)


def redact_facts(facts: list[dict]) -> list[dict]:
    """Keep only id and redacted text. The name-line rule applies to the first real line of the whole resume only,
    otherwise every two-character fact such as a section heading would be treated as a name."""
    out, top = [], True
    for fact in facts:
        text = fact.get('text') or ''
        out.append(dict(id=fact['id'], text=_apply(text, top)))
        if top and text.strip() and not all(_is_title(line) or not line.strip() for line in text.split('\n')):
            top = False
    return out
