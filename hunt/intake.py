"""Bounded local resume intake. Reading text never confirms it or permits disclosure."""
import argparse
import hashlib
import io
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from hunt.profile import build_profile

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_PAGES = 40
MAX_TEXT_CHARS = 200_000
MAX_ZIP_BYTES = 40 * 1024 * 1024
MAX_XML_BYTES = 10 * 1024 * 1024
MAX_STREAM_BYTES = 8 * 1024 * 1024


def _clean_text(text):
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    if '\x00' in text or any(ord(ch) < 32 and ch not in '\n\t' for ch in text):
        raise ValueError('文本含异常控制字符，请重新导出简历')
    return text


class _SafeTreeBuilder(ElementTree.TreeBuilder):
    def doctype(self, name, pubid, system):
        raise ValueError('DOCX 不支持 XML 实体或 DTD')


def _docx_rows(content):
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries]
            if len(entries) > 1000 or len(names) != len(set(names)):
                raise ValueError('DOCX 包含过多或重复文件')
            if sum(entry.file_size for entry in entries) > MAX_ZIP_BYTES:
                raise ValueError('DOCX 解压后超过 40MiB')
            for entry in entries:
                if entry.flag_bits & 1 or (entry.file_size > 1024 * 1024 and entry.file_size / max(entry.compress_size, 1) > 200):
                    raise ValueError('DOCX 加密或压缩比例异常')
            info = archive.getinfo('word/document.xml')
            if info.file_size > MAX_XML_BYTES:
                raise ValueError('DOCX 正文超过 10MiB')
            xml = archive.read(info)
            if b'<!DOCTYPE' in xml.upper() or b'<!ENTITY' in xml.upper():
                raise ValueError('DOCX 不支持 XML 实体或 DTD')
            root = ElementTree.fromstring(xml, parser=ElementTree.XMLParser(target=_SafeTreeBuilder()))
            warnings = []
            if any(re.match(r'word/(header|footer|footnotes|endnotes)\d*\.xml$', name) for name in names):
                warnings.append('页眉、页脚和脚注未提取；请核对姓名及联系方式是否完整。')
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError, RuntimeError) as exc:
        raise ValueError('DOCX 损坏、加密或缺少正文') from exc
    ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    rows = []
    for index, para in enumerate(root.findall('.//w:p', ns), 1):
        parts = []
        for node in para.iter():
            if node.tag == '{%s}t' % ns['w']:
                parts.append(node.text or '')
            elif node.tag in ('{%s}tab' % ns['w'], '{%s}br' % ns['w']):
                parts.append(' ')
        text = _clean_text(''.join(parts)).strip()
        if text:
            rows.append({'paragraph': index, 'text': text})
    return rows, {'paragraph_count': len(root.findall('.//w:p', ns))}, warnings


def extract_docx(path):
    """Compatibility API for explicitly selected local paths."""
    path = Path(path)
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError('输入超过 20MiB')
    return [(r['paragraph'], r['text']) for r in _docx_rows(path.read_bytes())[0]]


def _pdf_worker(content):
    # Run in a disposable child process; decompression and extraction are bounded.
    import resource
    resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
    if sys.platform.startswith('linux'):
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024,) * 2)
    import pypdf.filters as filters
    from pypdf import PdfReader
    for key in ('ZLIB_MAX_OUTPUT_LENGTH', 'LZW_MAX_OUTPUT_LENGTH', 'RUN_LENGTH_MAX_OUTPUT_LENGTH',
                'MAX_ARRAY_BASED_STREAM_OUTPUT_LENGTH', 'MAX_DECLARED_STREAM_LENGTH'):
        if hasattr(filters, key):
            setattr(filters, key, MAX_STREAM_BYTES)
    if not content.startswith(b'%PDF-'):
        raise ValueError('文件内容不是 PDF')
    reader = PdfReader(io.BytesIO(content), strict=True)
    if reader.is_encrypted:
        raise ValueError('PDF 已加密，请先在本地导出未加密副本')
    if len(reader.pages) > MAX_PAGES:
        raise ValueError(f'PDF 最多支持 {MAX_PAGES} 页')
    rows, missing, bad = [], [], []
    for number, page in enumerate(reader.pages, 1):
        contents = page.get_contents()
        if contents and len(contents.get_data()) > MAX_STREAM_BYTES:
            raise ValueError('PDF 单页内容超过提取限制')
        text = _clean_text(page.extract_text() or '')
        visible = ''.join(text.split())
        if not visible:
            missing.append(number)
            continue
        if text.count('\ufffd') / max(len(visible), 1) > .02 or text.count('\u25a0') / max(len(visible), 1) > .1:
            bad.append(number)
            continue
        for index, paragraph in enumerate(text.splitlines(), 1):
            if paragraph.strip():
                rows.append({'page': number, 'paragraph': index, 'text': paragraph.strip()})
        if sum(len(row['text']) for row in rows) > MAX_TEXT_CHARS:
            raise ValueError('提取文字超过 200000 字符')
    return {'rows': rows, 'page_count': len(reader.pages), 'pages_needing_ocr': missing, 'pages_with_bad_text': bad}


def _pdf_rows(content):
    try:
        process = subprocess.run([sys.executable, '-m', 'hunt.intake', '--pdf-worker'], input=content,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20,
                                 cwd=str(Path(__file__).resolve().parent.parent))
    except subprocess.TimeoutExpired as exc:
        raise ValueError('PDF 解析超时，请导出精简文本 PDF') from exc
    try:
        result = json.loads(process.stdout)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError('PDF 损坏或超过解析资源限制') from exc
    if process.returncode or 'error' in result:
        raise ValueError(result.get('error', 'PDF 解析失败'))
    rows = result.pop('rows')
    warnings = []
    if result['pages_needing_ocr']:
        warnings.append('以下页没有可提取文字，需要本地 OCR 或重新导出：' + ', '.join(map(str, result['pages_needing_ocr'])))
    if result['pages_with_bad_text']:
        warnings.append('以下页文字疑似乱码，已排除，需重新导出：' + ', '.join(map(str, result['pages_with_bad_text'])))
    return rows, result, warnings


def _fields(facts):
    candidates = {}
    patterns = {
        'name': r'^(?:姓名|name)\s*[:：]\s*([^\n。；;]{1,40})$',
        'email': r'^(?:邮箱|联系邮箱|email)\s*[:：]\s*([A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,})[。.]?$',
        'years_experience': r'^(?:相关)?工作经验\s*[:：为]?\s*(\d+(?:\.\d+)?)\s*年[。.]?$',
    }
    for fact in facts:
        for key, pattern in patterns.items():
            found = re.match(pattern, fact['text'], re.I)
            if not found:
                continue
            value = float(found[1]) if key == 'years_experience' else found[1].strip()
            if key == 'years_experience' and value > 80:
                continue
            fact['value'] = value
            fact['tags'].append('experience' if key == 'years_experience' else 'contact' if key == 'email' else 'identity')
            candidates.setdefault(key, []).append({'value': value, 'fact_ids': [fact['id']]})
    return {key: matches[0] for key, matches in candidates.items() if len({str(item['value']) for item in matches}) == 1}


def analyze_resume(filename: str, content: bytes, synthetic=False) -> dict:
    """Analyze bytes only; filename is a label, never a filesystem read path.

    Raises ValueError for unsupported/damaged/oversized inputs. Scan-only PDFs return
    status=needs_ocr with no candidate claims; mixed PDFs return partial. Facts are
    always unconfirmed/private, including synthetic fixtures.
    """
    if not isinstance(filename, str) or not filename or '\x00' in filename:
        raise ValueError('请提供简历文件名')
    if not isinstance(content, bytes) or not content or len(content) > MAX_FILE_BYTES:
        raise ValueError('请上传非空且不超过 20MiB 的文件')
    label = filename.replace('\\', '/').rsplit('/', 1)[-1]
    suffix = Path(label).suffix.lower()
    if suffix not in {'.pdf', '.docx', '.txt', '.md'}:
        raise ValueError('支持 PDF、DOCX、TXT、MD 格式')
    sha = hashlib.sha256(content).hexdigest()
    if suffix == '.pdf':
        rows, metadata, warnings = _pdf_rows(content)
    elif suffix == '.docx':
        rows, metadata, warnings = _docx_rows(content)
    else:
        try:
            text = _clean_text(content.decode('utf-8-sig'))
        except UnicodeDecodeError as exc:
            raise ValueError('文本文件须使用 UTF-8 编码') from exc
        rows = [{'paragraph': i, 'text': line.strip()} for i, line in enumerate(text.splitlines(), 1) if line.strip()]
        metadata, warnings = {}, []
    if sum(len(row['text']) for row in rows) > MAX_TEXT_CHARS:
        raise ValueError('提取文字超过 200000 字符')
    facts = []
    for row in rows:
        if '\ufffd' in row['text']:
            warnings.append('原文含替换字符，可能存在乱码；请核对后重新导出。')
        locator = ('page=' + str(row['page']) + '&' if row.get('page') else '') + 'paragraph=' + str(row['paragraph'])
        source = dict(kind='user_resume_draft', reference=f'upload://{sha}#{locator}', sha256=sha, label=label, synthetic=bool(synthetic),
                      **{key: value for key, value in row.items() if key != 'text'})
        facts.append(dict(id='intake-' + hashlib.sha256((sha + '#' + locator).encode()).hexdigest()[:18],
                          text=row['text'], source=source, status='unconfirmed', version=1, disclosure='private', tags=[]))
    fields = _fields(facts)
    explicit_years = {f.get('value') for f in facts if 'experience' in f.get('tags', [])}
    if len(explicit_years) > 1:
        warnings.append('原文出现不同的整体工作年限，未选择其中任何一个；请核对。')
    candidate = dict(name=fields.get('name', {}).get('value', '待确认候选人'), synthetic=bool(synthetic),
                     version=1, facts=facts, fields=fields,
                     notice='仅从上传文件提取，所有事实待核对；未授权外传或投递。')
    if not facts:
        status = 'needs_ocr' if metadata.get('pages_needing_ocr') else 'needs_review'
        warnings.append('未得到可用简历文字，暂不能生成岗位检索建议。')
    elif metadata.get('pages_needing_ocr') or metadata.get('pages_with_bad_text'):
        status = 'partial'
    else:
        status = 'ready_for_review'
    document = dict(filename=label, sha256=sha, size_bytes=len(content), format=suffix[1:], status=status, synthetic=bool(synthetic),
                    paragraph_count=len(facts), **{k: v for k, v in metadata.items() if k != 'paragraph_count'})
    profile = build_profile(candidate)
    by_id = {fact['id']: fact for fact in facts}
    for skill in profile['skills']:
        for ident in skill['fact_ids']:
            by_id[ident]['tags'].append(skill['name'].casefold())
    return dict(candidate=candidate, profile=profile, warnings=list(dict.fromkeys(warnings)), document=document, status=status)


def extract(paths, output):
    """Legacy CLI: read only explicitly listed paths and save private pending facts."""
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    facts, documents = [], []
    for item in paths:
        path = Path(item).expanduser().resolve(strict=True)
        if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
            raise ValueError('输入不是 20MiB 以内的文件')
        result = analyze_resume(path.name, path.read_bytes())
        document = result['document']
        documents.append(dict(path=str(path), **document, warnings=result['warnings'], notice='工作稿，仅提取；未确认、不得外发'))
        for fact in result['candidate']['facts']:
            locator = fact['source']['reference'].split('#', 1)[1]
            fact['source']['reference'] = str(path) + '#' + locator
            fact['id'] = 'intake-' + hashlib.sha256((str(path) + '#' + locator).encode()).hexdigest()[:18]
            facts.append(fact)
    candidate = dict(name='待确认候选人', synthetic=False, version=1, facts=facts, fields={},
                     notice='仅为指定文件的原文提取；所有主张待用户核对。此文件尚未导入活动候选资料。')
    for filename, data in [('pending-candidate.json', candidate), ('source-documents.json', documents)]:
        p = output / filename
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        p.chmod(0o600)
    return dict(documents=len(documents), paragraphs=len(facts), confirmed=0, external_use=0, output=str(output / 'pending-candidate.json'))


if __name__ == '__main__':
    if sys.argv[1:] == ['--pdf-worker']:
        try:
            print(json.dumps(_pdf_worker(sys.stdin.buffer.read(MAX_FILE_BYTES + 1)), ensure_ascii=False))
        except Exception as exc:
            print(json.dumps({'error': str(exc) if isinstance(exc, ValueError) else 'PDF 损坏或无法解析'}, ensure_ascii=False))
            sys.exit(1)
    else:
        parser = argparse.ArgumentParser(description='仅提取明确指定的本地文件；不会扫描目录或自动确认事实')
        parser.add_argument('paths', nargs='+')
        parser.add_argument('--output', required=True)
        args = parser.parse_args()
        print(json.dumps(extract(args.paths, args.output), ensure_ascii=False, indent=2))
