"""Canonical company and job-title forms: the job library links sources by them, and the benchmark matches with them."""
import re
import unicodedata

BRACKETS = re.compile(r'\([^()]*\)|\[[^\[\]]*\]|【[^【】]*】')


def _text(text):
    text = unicodedata.normalize('NFKC', str(text or '')).casefold()
    while True:
        stripped = BRACKETS.sub('', text)
        if stripped == text:
            return text
        text = stripped


def normalize_title(text):
    return ''.join(c for c in _text(text) if not c.isspace() and
                   not unicodedata.category(c).startswith('P') and c != '|')


def normalize_company(text):
    text = ''.join(c for c in _text(text) if not c.isspace())
    return re.sub(r'(?:股份有限公司|有限公司|集团)+$', '', text)
