"""Evidence intake cannot promote extracted prose to approved application claims."""
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from hunt.intake import extract
from hunt.materials import accepted_facts


class IntakeTests(unittest.TestCase):
    def test_docx_paragraphs_are_private_unconfirmed_and_stably_identified(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);doc=root/'resume.docx'
            xml='<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>参与原型设计，尚未上线。</w:t></w:r></w:p><w:p/><w:p><w:r><w:t>样本120条。</w:t></w:r></w:p></w:body></w:document>'
            with zipfile.ZipFile(doc,'w') as archive: archive.writestr('word/document.xml',xml)
            result=extract([doc],root/'out')
            candidate=json.loads(Path(result['output']).read_text())
            self.assertEqual(result['paragraphs'],2)
            self.assertFalse(accepted_facts(candidate))
            self.assertEqual(candidate['facts'][1]['text'],'样本120条。')
            self.assertTrue(candidate['facts'][1]['source']['reference'].endswith('#paragraph=3'))
            extract([doc],root/'other')
            other=json.loads((root/'other'/'pending-candidate.json').read_text())
            self.assertEqual([f['id'] for f in candidate['facts']],[f['id'] for f in other['facts']])

    def test_only_explicit_files_are_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'approved.txt').write_text('授权原文');(root/'unrelated.txt').write_text('不应读取')
            result=extract([root/'approved.txt'],root/'out')
            candidate=json.loads(Path(result['output']).read_text())
            self.assertEqual([f['text'] for f in candidate['facts']],['授权原文'])
            self.assertEqual(result['documents'],1)

    def test_unsupported_inputs_not_treated_as_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'x.pdf').write_bytes(b'%PDF-invalid')
            with self.assertRaises(ValueError): extract([root/'x.pdf'],root/'out')


class UploadTests(unittest.TestCase):
    def analyze(self, filename, content):
        from hunt.intake import analyze_resume
        return analyze_resume(filename, content, synthetic=True)

    def pdf(self, lines=(), pages=1):
        import io
        from reportlab.pdfgen import canvas
        stream = io.BytesIO()
        pdf = canvas.Canvas(stream)
        for _ in range(pages):
            for index, line in enumerate(lines):
                pdf.drawString(50, 780 - index * 20, line)
            pdf.showPage()
        pdf.save()
        return stream.getvalue()

    def docx(self, body, **extra):
        import io
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('word/document.xml', body)
            for name, value in extra.items():
                archive.writestr(name, value)
        return stream.getvalue()

    def test_text_pdf_records_page_and_paragraph_and_stable_hash(self):
        data = self.pdf(['Python RAG prototype', 'No production deployment'])
        one = self.analyze('test.pdf', data)
        two = self.analyze('/a/different/name.pdf', data)
        self.assertEqual(one['status'], 'ready_for_review')
        self.assertEqual(one['document']['page_count'], 1)
        self.assertEqual(one['candidate']['facts'], [dict(f, source=dict(f['source'], label='test.pdf')) for f in two['candidate']['facts']])
        for fact in one['candidate']['facts']:
            self.assertEqual(fact['source']['page'], 1)
            self.assertEqual(fact['status'], 'unconfirmed')
            self.assertEqual(fact['disclosure'], 'private')
            self.assertIn('#page=1&paragraph=', fact['source']['reference'])

    def test_scan_or_blank_pdf_requires_ocr_not_empty_success(self):
        result = self.analyze('scan.pdf', self.pdf())
        self.assertEqual(result['status'], 'needs_ocr')
        self.assertEqual(result['document']['pages_needing_ocr'], [1])
        self.assertFalse(result['candidate']['facts'])
        self.assertFalse(result['profile']['suggested_queries'])

    def test_page_limit_and_malformed_pdf(self):
        with self.assertRaisesRegex(ValueError, '40'):
            self.analyze('too-long.pdf', self.pdf(pages=41))
        for data in (b'%PDF-broken', b'not pdf'):
            with self.assertRaises(ValueError):
                self.analyze('broken.pdf', data)

    def test_mixed_pdf_is_partial(self):
        import io
        from reportlab.pdfgen import canvas
        buffer = io.BytesIO()
        pdf = canvas.Canvas(buffer)
        pdf.drawString(50, 750, 'Python project')
        pdf.showPage()
        pdf.showPage()
        pdf.save()
        result = self.analyze('mixed.pdf', buffer.getvalue())
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['document']['pages_needing_ocr'], [2])
        self.assertEqual(len(result['candidate']['facts']), 1)

    def test_docx_entity_and_zip_bomb_rejected(self):
        body = '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body/></w:document>'
        with self.assertRaisesRegex(ValueError, '压缩比例'):
            self.analyze('bomb.docx', self.docx(body, bomb=b'0' * (2 * 1024 * 1024)))
        entity = '<!DOCTYPE x [<!ENTITY x "Python">]>' + body
        with self.assertRaisesRegex(ValueError, '实体'):
            self.analyze('entity.docx', self.docx(entity))
        with self.assertRaises(ValueError):
            self.analyze('broken.docx', b'not zip')

    def test_filename_is_only_label_and_utf8_required(self):
        result = self.analyze('/must/not/read/private.txt', b'Python')
        self.assertEqual(result['document']['filename'], 'private.txt')
        self.assertEqual(result['candidate']['facts'][0]['text'], 'Python')
        with self.assertRaisesRegex(ValueError, 'UTF-8'):
            self.analyze('bad.txt', b'\xff\xfe')
        with self.assertRaisesRegex(ValueError, '控制字符'):
            self.analyze('bad.txt', b'Python\x00')
        result = self.analyze('bad.txt', 'Python \ufffd'.encode())
        self.assertTrue(result['warnings'])

    def test_size_limit_and_empty_content(self):
        from unittest.mock import patch
        with patch('hunt.intake.MAX_FILE_BYTES', 4):
            with self.assertRaises(ValueError):
                self.analyze('large.txt', b'12345')
        with self.assertRaises(ValueError):
            self.analyze('empty.txt', b'')

    def test_encrypted_pdf_is_not_reported_as_empty(self):
        import io
        from pypdf import PdfReader, PdfWriter
        writer = PdfWriter()
        writer.append(PdfReader(io.BytesIO(self.pdf(['Python']))))
        writer.encrypt('secret')
        buffer = io.BytesIO()
        writer.write(buffer)
        with self.assertRaisesRegex(ValueError, '加密'):
            self.analyze('encrypted.pdf', buffer.getvalue())


    def test_synthetic_upload_keeps_provenance_flag_on_document_and_facts(self):
        result = self.analyze('synthetic.txt', b'Python')
        self.assertTrue(result['candidate']['synthetic'])
        self.assertTrue(result['document']['synthetic'])
        self.assertTrue(all(f['source']['synthetic'] for f in result['candidate']['facts']))
        result['candidate']['synthetic'] = False
        self.assertTrue(result['candidate']['facts'][0]['source']['synthetic'])

if __name__ == '__main__':
    unittest.main()
