"""One searchable, embedded-font resume template; no network or model calls."""
import json
import os
from pathlib import Path
from xml.sax.saxutils import escape


def _font():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    name = 'HuntUnicode'
    if name in pdfmetrics.getRegisteredFontNames():
        return name
    choices = [os.environ.get('HUNT_PDF_FONT'),
               '/System/Library/Fonts/Supplemental/Arial Unicode.ttf',
               '/System/Library/Fonts/STHeiti Light.ttc',
               '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc']
    failures = []
    for path in choices:
        if path and Path(path).is_file():
            try:
                pdfmetrics.registerFont(TTFont(name, path))
                return name
            except Exception as exc:
                failures.append(type(exc).__name__)
    raise RuntimeError('缺少可嵌入的中文 TrueType 字体。设置 HUNT_PDF_FONT 指向合法授权的中文 TTF/TTC。' + ','.join(failures))


def _pdf(text, path):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    font = _font()
    body = ParagraphStyle('Body', fontName=font, fontSize=10.5, leading=18, textColor=colors.HexColor('#22302e'),
                          alignment=TA_LEFT, wordWrap='CJK', spaceAfter=8, allowWidows=0, allowOrphans=0)
    title = ParagraphStyle('Title', parent=body, fontSize=23, leading=31, spaceAfter=10)
    heading = ParagraphStyle('Heading', parent=body, fontSize=13, leading=23, spaceBefore=13, keepWithNext=True)
    doc = SimpleDocTemplate(str(path), pagesize=A4, rightMargin=53, leftMargin=53,
                            topMargin=48, bottomMargin=46, title='申请简历', author='')
    flow = []
    for index, line in enumerate(text.splitlines()):
        if not line.strip():
            flow.append(Spacer(1, 5))
            continue
        style = title if index == 0 else (heading if line in ['经历与能力'] else body)
        flow.append(Paragraph(escape(line), style))
    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont(font, 8)
        canvas.setFillColor(colors.HexColor('#6b7572'))
        canvas.drawRightString(A4[0] - 53, 25, str(document.page))
        canvas.restoreState()
    doc.build(flow, onFirstPage=footer, onLaterPages=footer)


def write_package(package, output_dir):
    """Caller chooses a private, version-specific directory. Returned names are relative."""
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(str(path), 0o700)
    files = {'text': 'resume.txt', 'pdf': 'resume.pdf', 'cover_letter': 'cover-letter.txt',
             'answers': 'answers.json', 'source_map': 'source-map.json'}
    (path / files['text']).write_text(package['resume'], encoding='utf-8')
    (path / files['cover_letter']).write_text(package.get('cover_letter', ''), encoding='utf-8')
    for key in ['answers', 'source_map']:
        (path / files[key]).write_text(json.dumps(package.get(key, [] if key == 'answers' else {}), ensure_ascii=False, indent=2), encoding='utf-8')
    _pdf(package['resume'], path / files['pdf'])
    for filename in files.values():
        os.chmod(str(path / filename), 0o600)
    return files
