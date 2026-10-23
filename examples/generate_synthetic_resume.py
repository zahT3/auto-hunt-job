"""Create public synthetic upload fixtures. No real candidate information is used.
Run: .venv/bin/python examples/generate_synthetic_resume.py
"""
from pathlib import Path
from xml.sax.saxutils import escape
import zipfile
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

LINES = [
    '合成候选人，仅用于开发验收，不能用于真实求职。',
    '姓名：林示例',
    '邮箱：candidate@example.invalid',
    '工作经验：3年',
    '学历：本科，计算机科学，示例大学，2021年毕业。',
    '工作经历：2021.07—2024.06，示例科技，软件开发工程师。',
    '使用 Python、SQL、FastAPI 开发内部知识检索原型，采用 RAG 和 LangChain。',
    'Agent 工具调用在合成的120条测试问题中完成本地验证；未上线，无生产效果证据。',
    '使用 Docker 运行本地服务，使用 React 实现简历审核页面。',
    'Web3 学习项目：使用 Solidity 和 Ethereum 测试网实现智能合约原型。',
    '实习经历：2020.07—2020.09，示例实验室，数据整理实习；未计入3年工作经验。',
    '尚无交易所工作经历，不具备金融交易生产系统经验。',
]


def generate(directory=None):
    directory = Path(directory or Path(__file__).resolve().parent)
    directory.mkdir(parents=True, exist_ok=True)
    stem = directory / 'resume.synthetic'
    stem.with_suffix('.synthetic.txt').write_text('\n'.join(LINES) + '\n', encoding='utf-8')
    paragraphs = ''.join(f'<w:p><w:r><w:t>{escape(line)}</w:t></w:r></w:p>' for line in LINES)
    doc = f'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>{paragraphs}<w:sectPr/></w:body></w:document>'
    with zipfile.ZipFile(str(stem) + '.docx', 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml', '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        archive.writestr('_rels/.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        archive.writestr('word/document.xml', doc)
    pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
    pdf = canvas.Canvas(str(stem) + '.pdf', pagesize=(595, 842), pageCompression=1)
    pdf.setTitle('合成候选人简历 - 开发验收')
    pdf.setFont('STSong-Light', 12)
    y = 790
    for line in LINES:
        # Wrap by measured width; PDF extraction preserves each line's page source.
        buffer = ''
        for char in line:
            if pdfmetrics.stringWidth(buffer + char, 'STSong-Light', 12) > 490:
                pdf.drawString(50, y, buffer)
                y -= 21
                buffer = ''
            buffer += char
        pdf.drawString(50, y, buffer)
        y -= 32
    pdf.save()
    return [str(stem) + ext for ext in ('.pdf', '.docx', '.txt')]


if __name__ == '__main__':
    print('\n'.join(generate()))
