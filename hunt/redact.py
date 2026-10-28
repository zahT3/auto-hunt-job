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
# Old 15-digit IDs have no checksum; the yymmdd at positions 7-12 is the only structure to test.
_ID15 = r'(?<![0-9A-Za-z])\d{6}\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}(?![0-9A-Za-z])'
_CARD = r'(?<!\d)(?:\d{4}(?:[ \-]\d{4}){3}(?:[ \-]\d{1,3})?|\d{16,19})(?!\d)'
_CARD_LABEL = r'(?:银行卡号?|卡号|银行账号|账号)\s*[:：]\s*(\d[\d \-]{14,24}\d)'
_URL = r'https?://[^\s<>"\')\]，。；;]+'
_URL_START = r'(?<![\w.@/\-])'
_URL_BARE = [
    _URL_START + r'(?:www\.)?(?:github|gitee|gitlab)\.com/[\w.\-]+(?:/[\w.\-/]*)?',
    _URL_START + r'(?:www\.)?linkedin\.com/(?:in|pub)/[\w%\-]+/?',
    _URL_START + r'(?:www\.)?zhihu\.com/people/[\w\-]+',
    _URL_START + r'(?:www\.)?(?:weibo\.com|juejin\.cn/user|jianshu\.com/u|cnblogs\.com|blog\.csdn\.net)/[\w.\-/]+',
    _URL_START + r'[\w\-]+\.(?:github|gitee)\.io(?:/\S*)?',
]
_URL_LABEL = (r'(?:个人网站|个人主页|个人博客|主页|博客|Blog|Website|Homepage|Portfolio)\s*[:：]\s*'
              r'((?:https?://)?[A-Za-z0-9][A-Za-z0-9\-]*(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}(?:/\S*)?)')
_DATE = r'\d{4}(?:\s*[年./\-]\s*\d{1,2}(?:\s*[月./\-]\s*\d{1,2}\s*日?|\s*月)?)?年?'
_BIRTH_LABEL = (r'(?<![A-Za-z])(?:出生日期|出生年月|出生年份|出生|生日|Date\s+of\s+Birth|DOB|Birthday|Birth\s*Date)\s*[:：]\s*(' + _DATE + ')')
_BIRTH_POST = [r'(?<!\d)\d{2,4}\s*年(?:\s*\d{1,2}\s*月(?:\s*\d{1,2}\s*[日号])?)?\s*出生(?:日期)?',
               r'(?<!\d)\d{4}\s*[./\-]\s*\d{1,2}(?:\s*[./\-]\s*\d{1,2})?\s*出生']
_BIRTH_PRE = r'(?:出生于|生于)\s*\d{2,4}\s*年?(?:\s*\d{1,2}\s*月(?:\s*\d{1,2}\s*[日号])?)?'
_AGE_LABEL = r'(?<![A-Za-z])(?:年龄|Age)\s*[:：]\s*(\d{1,3}(?:\s*岁)?)'
_AGE = r'(?<![\d.])(?:1[6-9]|[2-6]\d)\s*(?:周)?岁'

_ID_LABEL = r'(?:身份证(?:号码?)?|证件号码?|ID\s*(?:No|Number)\.?)\s*[:：]?\s*(\d[\dXx \-]{12,21}[\dXx])'
_PHONE_LABEL = r'(?:手机(?:号码?)?|联系电话|电话|联系方式|Tel|Phone|Mobile|Cell)\s*[:：]?\s*(\+?\d[\d \-.()]{5,}\d)'
_SOCIAL = (r'(?<![A-Za-z])((?:微信号?|WeChat|Weixin|wx|vx|QQ(?:号码?)?)(?:\s*[/、&]\s*(?:微信号?|WeChat|QQ(?:号)?))*)'
           r'(\s*[:：]\s*|\s+)([A-Za-z0-9_\-]{5,30})(?![A-Za-z0-9_\-])')
# Name fields only at the start of a line or after a field separator, so "Company Name: ..." is left alone.
_NAME_FIELD = (r'(?:^|(?<=[|｜,，;；\t])|(?<=\s\s))\s*(?:真实姓名|姓\s*名|名字|Full\s*Name|Name)\s*[:：]\s*'
               r"([\u4e00-\u9fff·]{2,6}|[A-Za-z][A-Za-z.\-']*(?: [A-Za-z][A-Za-z.\-']*){0,3})")
_PROVINCE = ('河北|山西|辽宁|吉林|黑龙江|江苏|浙江|安徽|福建|江西|山东|河南|湖北|湖南|广东|海南|四川|贵州|云南|陕西|甘肃|青海|台湾|'
             '内蒙古|广西|西藏|宁夏|新疆|香港|澳门')
_CITY = ('北京|上海|天津|重庆|深圳|广州|杭州|南京|成都|武汉|西安|苏州|郑州|长沙|青岛|宁波|无锡|合肥|厦门|福州|济南|大连|沈阳|哈尔滨|长春|石家庄|'
         '太原|南昌|昆明|贵阳|南宁|海口|兰州|西宁|银川|乌鲁木齐|呼和浩特|拉萨|佛山|东莞|珠海|中山|惠州|常州|南通|徐州|温州|嘉兴|绍兴|金华|台州|'
         '烟台|潍坊|临沂|洛阳|唐山|保定|泉州|漳州|扬州|镇江|盐城|芜湖|襄阳|宜昌|株洲|湘潭|岳阳|柳州|桂林|三亚|汕头|江门|湛江|肇庆|绵阳|德阳|遵义')
# Province and city are matched from lists, not as "any Han characters + 市", so a company name right before the
# address ("在腾讯科技深圳市南山区...") is not swallowed. Only the district and street names stay generic.
_ADMIN = (rf'(?:(?:{_PROVINCE})(?:省|壮族自治区|回族自治区|维吾尔自治区|自治区|特别行政区)?)?(?:(?:{_CITY})市?)?'
          r'(?:[\u4e00-\u9fff]{1,3}?(?:区|县|旗))?(?:[\u4e00-\u9fff]{1,4}?(?:镇|乡|街道))?')
_STREET = r'(?:(?![区市县省])[\u4e00-\u9fffA-Za-z0-9]){1,8}?(?:路|大街|街|大道|巷|弄)[甲乙丙丁A-Za-z]?\d+(?:-\d+)?号'
_UNIT = (r'(?:院|\d+号院)?(?:\d+(?:号楼|栋|幢|座|单元|层|楼|室|房|号)|[A-Za-z]座)*(?:\d{2,4}(?!\d))?')
_ADDRESS = [
    rf'{_ADMIN}{_STREET}{_UNIT}',
    r'(?:[\u4e00-\u9fff]{2,10}(?:小区|园|公寓|苑|府|大厦|广场))?\d+(?:号楼|栋|幢|座)(?:\d+单元)?(?:\d{1,4}室?)?',
    r'\d+单元\d{0,4}室?',
    r'(?<![\d])\d{2,4}室',
]
_ADDRESS_LABEL = r'(?:家庭住址|通讯地址|联系地址|现住址|住址|居住地|现居地?|地址)\s*[:：]?\s*([^\n，,;；。|｜]{4,60})'
_ADDRESS_DETAIL = re.compile(r'[路街巷弄号室栋幢楼院层]|\d')

_TITLES = {'简历', '个人简历', '求职简历', '中文简历', '个人资料', 'resume', 'cv', 'curriculum vitae'}
_HEADING_END = ('简历', '经历', '经验', '背景', '技能', '评价', '信息', '意向', '简介', '方式', '总结', '介绍', '奖项',
                '证书', '荣誉', '概述', '优势', '项目', '教育', '特长', '爱好', '奖励', '培训', '语言', '资料', '履历')
_JOB_END = ('经理', '工程师', '设计师', '专员', '主管', '总监', '运营', '开发', '分析师', '顾问', '助理', '程序员', '架构师',
            '研究员', '讲师', '会计', '律师', '医生', '护士', '老师', '编辑', '销售', '实习生')
_FIELD_WORDS = {'电话', '手机', '邮箱', '邮件', '微信', '地址', '住址', '性别', '年龄', '籍贯', '学历', '专业', '姓名', '生日', '主页', '博客'}
# 2-4 Han characters, possibly with one space between each ('林 示 例' is how many designed résumés print a name).
_LEAD_NAME = re.compile(r'([\u4e00-\u9fff](?:[ \u3000]?[\u4e00-\u9fff]){1,3})(?=[ \t|/·,、]|$)')


def _is_title(line):
    return ''.join(line.split()).strip('-=_*#').lower() in _TITLES


def _spans(text, top, names):
    """Return (start, end, replacement) spans, earlier rules winning where they overlap."""
    folded = _fold(text)
    found = []

    def add(pattern, repl, group=0, flags=0, check=None):
        for m in re.finditer(pattern, folded, flags):
            if m.start(group) < m.end(group) and (check is None or check(m.group(group))):
                found.append((m.start(group), m.end(group), repl(m) if callable(repl) else repl))

    # URLs first: an address-, id- or email-looking piece inside a URL must not split it.
    add(_URL, '[链接]')
    for pattern in _URL_BARE:
        add(pattern, '[链接]', flags=re.I)
    add(_URL_LABEL, '[链接]', 1, re.I)
    add(_EMAIL, '[邮箱]')
    add(_ID, '[身份证号]')
    add(_ID15, '[身份证号]')
    add(_ID_LABEL, '[身份证号]', 1, re.I)
    add(_CARD_LABEL, '[银行卡号]', 1)
    add(_CARD, '[银行卡号]', check=lambda value: _luhn(re.sub(r'\D', '', value)))
    add(_PHONE_LABEL, '[手机号]', 1, re.I)
    add(_PHONE, '[手机号]')
    add(_LANDLINE, '[电话]')
    for name in names:
        name = _fold(name).strip()
        if len(name) >= 2:
            # Han names also match with spaces between characters; other names keep their own word breaks.
            body = (r'\s*'.join(map(re.escape, ''.join(name.split()))) if re.fullmatch(r'[\u4e00-\u9fff\s]+', name)
                    else r'\s+'.join(map(re.escape, name.split())))
            add((r'(?<![A-Za-z])' if name[0].isascii() else '') + body + (r'(?![A-Za-z])' if name[-1].isascii() else ''),
                '[姓名]', flags=re.I)
    for m in re.finditer(_SOCIAL, folded, re.I):
        label, ident = m.group(1), m.group(3)
        if m.group(2).strip() or any(c.isdigit() for c in ident):  # "WeChat Official Account" has no colon or digit
            qq = 'QQ' in label.upper()
            wechat = bool(re.search('微信|wechat|weixin|wx|vx', label, re.I))
            # QQ ids are numeric: a letter in the id of a "微信/QQ" label means WeChat.
            found.append((m.start(3), m.end(3), '[QQ号]' if qq and (not wechat or ident.isdigit()) else '[微信号]'))
    add(_NAME_FIELD, '[姓名]', 1, re.I | re.M)
    add(_BIRTH_LABEL, '[出生日期]', 1, re.I)
    for pattern in _BIRTH_POST + [_BIRTH_PRE]:
        add(pattern, '[出生日期]')
    add(_AGE_LABEL, '[年龄]', 1, re.I)
    add(_AGE, '[年龄]')
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
                lead = _lead_match(stripped)
                if lead:
                    start = pos + line.index(stripped)
                    found.append((start, start + len(lead[1]), '[姓名]'))
                break
            pos += len(line) + 1
    kept = []
    for span in found:
        if all(span[1] <= k[0] or span[0] >= k[1] for k in kept):
            kept.append(span)
    return sorted(kept)


def _luhn(digits):
    if not 16 <= len(digits) <= 19:
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch) * (2 if i % 2 else 1)
        total += n - 9 if n > 9 else n
    return total % 10 == 0


def _apply(text, top, names):
    out, pos = [], 0
    for start, end, repl in _spans(text, top, names):
        out += [text[pos:start], repl]
        pos = end
    return ''.join(out) + text[pos:]


def redact(text: str, names=()) -> str:
    """names: strings (e.g. the candidate's name field) redacted wherever they occur, in addition to the pattern rules."""
    return _apply(text, True, tuple(names))


def redact_facts(facts: list[dict], names=()) -> list[dict]:
    """Keep only id and redacted text. The leading-name rule applies to the first real line of the whole resume only,
    otherwise every two-character fact such as a section heading would be treated as a name."""
    out, top, names = [], True, tuple(names)
    for fact in facts:
        text = fact.get('text') or ''
        out.append(dict(id=fact['id'], text=_apply(text, top, names)))
        if top and text.strip() and not all(_is_title(line) or not line.strip() for line in text.split('\n')):
            top = False
            # A name found only by the leading-line rule is redacted in every later fact too.
            found = lead_name(text)
            if found: names += (found,)
    return out


def _lead_match(line):
    """The leading-name match on a stripped first line, or None for a field word, heading or job title."""
    lead = _LEAD_NAME.match(line)
    tight = ''.join(lead[1].split()) if lead else ''
    return lead if lead and tight not in _FIELD_WORDS and not tight.endswith(_HEADING_END + _JOB_END) else None


def lead_name(text):
    """The name the leading-line rule would redact in the first real line of `text`, without spaces, or None."""
    for line in _fold(text).split('\n'):
        stripped = line.strip()
        if stripped and not _is_title(stripped):
            lead = _lead_match(stripped)
            return ''.join(lead[1].split()) if lead else None
    return None
