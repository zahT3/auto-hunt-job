"""Search terms: what a search may send, the inspectable recall aliases, and the local matches() filter.

Shared by the sources, the search engine and the AI orientation; it imports only hunt.search.parse.
"""
import re
from .parse import plain


def search_terms(config, profile=None):
    # The entire candidate profile is intentionally ignored at the network layer.
    # Local understanding proposes role labels; only explicit search fields leave.
    terms = config.get('keywords', config.get('search_terms'))
    # No built-in fallback terms: what to search for comes from the user's directions or keywords, never a default industry.
    if not isinstance(terms, list) or not terms: terms = [config.get('keyword')] if config.get('keyword') else []
    result = []
    for term in terms[:12]:
        if not isinstance(term, str): continue
        term = term.strip()
        if not term or len(term) > 100: continue
        if re.search(r'@|https?://|\d{7,}|[\r\n]', term): continue
        if term not in result: result.append(term)
        if len(result) == 8: break
    return result


ROLE_ALIASES = [
    (('开发', '工程师', '研发'), ['engineer', 'engineering', 'developer', 'development']),
    (('产品经理',), ['product manager', 'product owner', '产品专家', '产品负责人']),
]


def _segment_aliases(segment):
    # Only a segment of a multi-word term gets role aliases; a lone '开发' keeps matching narrowly.
    extra = [a for roles, values in ROLE_ALIASES if any(r in segment for r in roles) for a in values]
    if '应用' in segment and extra: extra += ['application', 'applied']
    return extra


ALIAS_GROUPS = {
    'ai': ['AI', '人工智能', 'machine learning', '机器学习', 'LLM', '大模型', '深度学习', 'MaaS'],
    'web3': ['web3', 'blockchain', '区块链', 'smart contract', '智能合约'],
    'agent': ['agent', '智能体'],
    'rag': ['RAG', 'retrieval augmented generation', '检索增强', 'retrieval'],
    # Non-tech groups. Every Chinese value is also a trigger, so keys stay specific: '设计师', not '设计' ('芯片设计' is not a designer).
    '销售': ['销售', 'sales', '业务拓展', 'business development', '大客户', 'account manager', 'account executive', '客户经理'],
    '运营': ['运营', 'operations', '用户运营', '内容运营', 'growth'],
    '财务': ['财务', 'finance', 'financial', '会计', 'accounting', 'accountant', '出纳', '审计', 'audit', 'auditor'],
    '人力资源': ['人力资源', 'HR', 'HRBP', 'human resources', '招聘', 'recruiter', 'recruiting', 'talent acquisition'],
    '设计师': ['设计师', 'designer', 'UI设计', 'UX', '视觉设计', '平面设计', 'graphic design'],
    '供应链': ['供应链', 'supply chain', '采购', 'procurement', 'purchasing', '物流', 'logistics', '仓储', 'warehouse'],
}


def expanded_terms(terms):
    """Explicit, inspectable recall aliases; this does not assert candidate fit."""
    groups = ALIAS_GROUPS
    result = {}
    for term in terms:
        aliases = [term]
        lower = term.lower()
        for key, values in groups.items():
            triggers = [key] + [v for v in values if any(ord(c) > 127 for c in v)]
            if any((re.search(r'(?<![a-z0-9_])' + re.escape(t) + r'(?![a-z0-9_])', lower) if t.isascii() else t in lower) for t in triggers):
                aliases.extend(values)
        if len(term.split()) > 1:
            for segment in term.split(): aliases.extend(_segment_aliases(segment))
        result[term] = list(dict.fromkeys(aliases))
    return result


def _found(words, text):
    for word in words:
        pattern = re.escape(word)
        if word[0].isascii() and word[0].isalnum(): pattern = r'(?<![A-Za-z0-9_])' + pattern
        if word[-1].isascii() and word[-1].isalnum(): pattern += r'(?![A-Za-z0-9_])'
        if re.search(pattern, text, re.I): return True
    return False


def _segments(term):
    """Words of a term. An unspaced Chinese term made of an alias word and a role word ('大模型产品经理') splits into the
    two, so both must match, as in 'AI 产品经理'; otherwise the alias word alone would match every AI title."""
    words = term.split()
    if len(words) > 1 or term.isascii(): return words
    triggers = sorted({w for key, values in ALIAS_GROUPS.items() for w in [key] + values if not w.isascii() and len(w) > 1},
                      key=len, reverse=True)
    for t in triggers:
        at = term.find(t)
        rest = [x for x in (term[:at], term[at + len(t):]) if x] if at >= 0 else []
        if rest and all(_segment_aliases(x) for x in rest):
            return [x for x in (term[:at], t, term[at + len(t):]) if x]
    return words


def matches(text, terms):
    """Local filter. A multi-word term matches as the whole phrase, or when every segment
    (each through its own alias group) matches: '大模型算法工程师' is not an 'AI 产品经理'."""
    if not terms: return False
    text = plain(text)
    for term, words in expanded_terms(terms).items():
        segments = _segments(term)
        if len(segments) < 2:
            if _found(words, text): return True
        elif _found([term], text) or all(_found(expanded_terms([s])[s] + _segment_aliases(s), text) for s in segments): return True
    return False
