"""Write a tailored résumé as Markdown, PDF or DOCX, and read the file back to check it.

Input is a "render structure" the caller builds from confirmed facts and accepted edits (nothing here invents text):

    {"title": "候选人姓名",                       # optional first line
     "sections": [{"key": "work", "title": "工作经历",
                   "lines": [{"text": "…", "kind": "head | bullet | text",   # kind defaults to text
                              "fact_ids": [{"id": "intake-…", "version": 2}],
                              "edit_ids": ["e7"]}]}]}

The self-check re-reads the exported file with this tool's own parser (`intake.analyze_resume`). It says nothing about
what any applicant tracking system would do.
"""
import functools
import hashlib
import json
import os
import re
import unicodedata
from pathlib import Path
from xml.sax.saxutils import escape

from .intake import analyze_resume

FONT_ENV = 'HUNT_PDF_FONT'
BUNDLED_FONT = Path(__file__).resolve().parent.parent / 'data' / 'fonts' / 'NotoSansSC-GB2312.ttf'
# Only TrueType-outline fonts can be embedded by reportlab; a candidate that fails to load is skipped.
SYSTEM_FONTS = ('/System/Library/Fonts/Supplemental/Arial Unicode.ttf', 'C:/Windows/Fonts/simhei.ttf')
MAX_PAGES = 2
FORMATS = ('md', 'pdf', 'docx')
FONT_HINT = '这些字不在内置字体里：{chars}。请用 HUNT_PDF_FONT 指定完整字体后重新导出。'
DOCX_HINT = '导出 DOCX 需要 python-docx：在项目的 .venv 里运行 pip install -r requirements.txt（它依赖 lxml，冷门平台需本地编译）。'
COVERAGE_LABELS = {'explicit': '原词', 'related': '相近', 'absent': '没有'}
NOTICE = '这是用本工具自己的解析器重读，不代表任何招聘系统的实际结果。'


class DocxUnavailable(RuntimeError):
    """python-docx is not installed; only DOCX export is affected."""


def _lines(render):
    """(section index or None, section key, line dict) for every output line in order, titles included."""
    out = []
    if render.get('title'):
        out.append((None, 'title', dict(text=render['title'], kind='title', fact_ids=[], edit_ids=[])))
    for index, section in enumerate(render.get('sections') or []):
        if section.get('title'):
            out.append((index, section.get('key', ''), dict(text=section['title'], kind='section', fact_ids=[], edit_ids=[])))
        for line in section.get('lines') or []:
            out.append((index, section.get('key', ''), {'kind': 'text', 'fact_ids': [], 'edit_ids': [], **line}))
    return out


def normalize(text):
    """NFKC, then all whitespace dropped: PDF extraction adds and removes spaces and wraps lines anywhere."""
    return ''.join(unicodedata.normalize('NFKC', text).split())


# --- fonts -----------------------------------------------------------------------------------------------------

def resolve_font(path=None):
    """Font file for the PDF: explicit path, then HUNT_PDF_FONT, then a system font, then the bundled subset."""
    explicit = path or os.environ.get(FONT_ENV)
    for candidate in [explicit] + ([] if path else list(SYSTEM_FONTS)) + [BUNDLED_FONT]:
        if not candidate or not Path(candidate).is_file():
            continue
        if _loads(str(candidate)):
            return Path(candidate)
        if candidate == explicit:
            raise ValueError(f'字体无法嵌入 PDF（需要 TrueType 轮廓的 .ttf）：{candidate}')
    raise ValueError('找不到可用的 PDF 字体')


@functools.lru_cache(maxsize=8)
def _loads(path):
    from reportlab.pdfbase.ttfonts import TTFont
    try:
        TTFont('probe', path)
        return True
    except Exception:
        return False


@functools.lru_cache(maxsize=8)
def _cmap(path):
    from reportlab.pdfbase.ttfonts import TTFont
    return frozenset(TTFont('probe', path).face.charToGlyph)


def font_chars(path):
    """Code points the font can draw (its cmap)."""
    return _cmap(str(path))


def missing_chars(render, font=None):
    """Characters of the output the PDF font cannot draw, sorted; whitespace is not counted."""
    have = font_chars(resolve_font(font))
    text = ''.join(line['text'] for _, _, line in _lines(render))
    return sorted({c for c in text if not c.isspace() and ord(c) not in have})


# --- writers ---------------------------------------------------------------------------------------------------

def render_markdown(render):
    out = []
    if render.get('title'):
        out.append('# ' + render['title'])
    for section in render.get('sections') or []:
        out.append('')
        if section.get('title'):
            out.append('## ' + section['title'])
            out.append('')
        for line in section.get('lines') or []:
            out.append(('- ' if line.get('kind') == 'bullet' else '') + line['text'])
    return ('\n'.join(out) + '\n').encode('utf-8')


def render_pdf(render, font=None):
    """PDF bytes: single column, text layer only, one font weight, section titles by size."""
    import io
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    path = resolve_font(font)
    name = 'HuntResume' + hashlib.sha256(str(path).encode()).hexdigest()[:8]
    if name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(name, str(path)))

    def style(key, size, lead, **kw):
        return ParagraphStyle(key, fontName=name, fontSize=size, leading=lead, wordWrap='CJK', **kw)
    styles = dict(title=style('t', 18, 24, spaceAfter=4), section=style('s', 12.5, 17, spaceBefore=9, spaceAfter=3),
                  head=style('h', 10.5, 15, spaceBefore=4), text=style('x', 10, 14.5),
                  bullet=style('b', 10, 14.5, leftIndent=11, firstLineIndent=0, bulletIndent=2))
    story = []
    for _, _, line in _lines(render):
        kind = line['kind'] if line['kind'] in styles else 'text'
        body = escape(line['text'])
        story.append(Paragraph(body, styles[kind], bulletText='•' if kind == 'bullet' else None))
    story.append(Spacer(1, 1))
    buffer = io.BytesIO()
    SimpleDocTemplate(buffer, pagesize=A4, leftMargin=44, rightMargin=44, topMargin=40, bottomMargin=40,
                      title='', author='', invariant=True).build(story)
    return buffer.getvalue()


def render_docx(render):
    """DOCX bytes with built-in styles only. Raises DocxUnavailable when python-docx is missing."""
    import io
    try:
        from docx import Document
    except ImportError as exc:
        raise DocxUnavailable(DOCX_HINT) from exc
    document = Document()
    for _, _, line in _lines(render):
        kind = line['kind']
        if kind == 'title':
            document.add_heading(line['text'], level=1)
        elif kind == 'section':
            document.add_heading(line['text'], level=2)
        elif kind == 'bullet':
            document.add_paragraph(line['text'], style='List Bullet')
        else:
            document.add_paragraph(line['text'])
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def build_trace(render, version=None, job_id=None, files=None, checks=None):
    """trace.json content: for each output line, the fact ids (with versions) and edit ids behind it."""
    return dict(schema_version=1, job_id=job_id, version=version, files=files or {}, checks=checks or {},
                lines=[dict(section=key, kind=line['kind'], text=line['text'], fact_ids=line['fact_ids'],
                            edit_ids=line['edit_ids']) for _, key, line in _lines(render)])


# --- read-back check -------------------------------------------------------------------------------------------

def _plain_markdown(content):
    text = content.decode('utf-8')
    return '\n'.join(re.sub(r'^(?:#+\s+|-\s+)', '', row) for row in text.splitlines()).encode('utf-8')


def check_export(render, filename, content, max_pages=MAX_PAGES, font=None, explain=None):
    """Re-read an exported file and compare it with the lines that were rendered.

    explain: optional callable(facts) -> match.explain-shaped dict; it is called once on the rendered lines and once on
    the read-back lines, and the per-keyword result is returned for the user to read (no percentage).
    Never raises for a failed check; only unreadable files raise ValueError. Returns
    dict(ok, notice, missing_lines, out_of_order, section_order_ok, page_count, pages_ok, warnings, missing_chars,
    keyword_coverage).
    """
    suffix = Path(filename).suffix.lower()
    absent = missing_chars(render, font) if suffix == '.pdf' else []
    try:
        analysis = analyze_resume(filename, _plain_markdown(content) if suffix == '.md' else content, synthetic=True)
    except ValueError as exc:
        if not absent:
            raise
        # A glyph the font lacks is written as a control code that intake refuses; the missing characters are the cause.
        return dict(ok=False, notice=NOTICE, missing_lines=[], out_of_order=[], section_order_ok=None, page_count=None,
                    pages_ok=None, warnings=[FONT_HINT.format(chars=''.join(absent)), f'读回失败：{exc}'],
                    missing_chars=absent, keyword_coverage=None)
    read_back = [fact['text'] for fact in analysis['candidate']['facts']]
    haystack = normalize(''.join(read_back))
    missing, out_of_order, cursor, positions = [], [], 0, {}
    lines = _lines(render)
    for number, (index, key, line) in enumerate(lines):
        needle = normalize(line['text'])
        if len(needle) < 2:
            continue
        found = haystack.find(needle, cursor)
        if found >= 0:
            cursor = found + len(needle)
            positions[number] = found
            continue
        elsewhere = haystack.find(needle)
        (out_of_order if elsewhere >= 0 else missing).append(line['text'])
    order_ok = not out_of_order
    page_count = analysis['document'].get('page_count')
    warnings = list(analysis['warnings'])
    if absent:
        warnings.append(FONT_HINT.format(chars=''.join(absent)))
    coverage = None
    if explain is not None:
        def keywords(texts):
            facts = [dict(id=f'row-{i}', text=t) for i, t in enumerate(texts)]
            return {row['keyword']: row['coverage'] for row in explain(facts)['keywords']}
        before = keywords([line['text'] for _, _, line in lines if line['kind'] != 'section'])
        after = keywords(read_back)
        coverage = [dict(keyword=word, before=COVERAGE_LABELS[before[word]], after=COVERAGE_LABELS[after.get(word, 'absent')],
                         changed=before[word] != after.get(word, 'absent')) for word in before]
    pages_ok = page_count is None or page_count <= max_pages
    ok = not missing and order_ok and pages_ok and not absent and not any(
        marker in w for w in analysis['warnings'] for marker in ('无法提取', '乱码', '替换字符'))
    return dict(ok=ok, notice=NOTICE, missing_lines=missing, out_of_order=out_of_order, section_order_ok=order_ok,
                page_count=page_count, pages_ok=pages_ok, warnings=warnings, missing_chars=absent, keyword_coverage=coverage)


# --- one call for the app layer --------------------------------------------------------------------------------

def export_all(render, out_dir, stem, formats=FORMATS, version=None, job_id=None, font=None, explain=None, max_pages=MAX_PAGES):
    """Write the requested formats and trace.json into out_dir (0700, files 0600); returns
    dict(files={fmt: {path, sha256, size, check}}, errors={fmt: message}, trace_path). A missing python-docx only puts
    a message in errors['docx']; the other formats are still written."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    writers = dict(md=render_markdown, pdf=lambda r: render_pdf(r, font), docx=render_docx)
    files, errors = {}, {}
    for fmt in formats:
        try:
            content = writers[fmt](render)
        except DocxUnavailable as exc:
            errors[fmt] = str(exc)
            continue
        path = out_dir / f'{stem}.{fmt}'
        _write(path, content)
        files[fmt] = dict(path=str(path), sha256=hashlib.sha256(content).hexdigest(), size=len(content),
                          check=check_export(render, path.name, content, max_pages=max_pages, font=font, explain=explain))
    trace = build_trace(render, version=version, job_id=job_id,
                        files={f: {k: v[k] for k in ('sha256', 'size')} for f, v in files.items()},
                        checks={f: v['check']['ok'] for f, v in files.items()})
    trace_path = out_dir / 'trace.json'
    _write(trace_path, (json.dumps(trace, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    return dict(files=files, errors=errors, trace_path=str(trace_path))


def _write(path, content):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'wb') as handle:
        handle.write(content)
    os.chmod(path, 0o600)
