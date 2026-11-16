"""Résumé export: three formats, read-back self-check, bundled font coverage. Synthetic data only."""
import copy
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hunt.profile import resume_render as rr

FONT = rr.BUNDLED_FONT


def fid(n):
    return {'id': f'intake-{n:02d}', 'version': 1}


RENDER = {
    'title': '示例候选人',
    'sections': [
        {'key': 'work', 'title': '工作经历', 'lines': [
            {'text': '示例科技有限公司 后端工程师 2021.07-2023.03', 'kind': 'head', 'fact_ids': [fid(1)]},
            {'text': '负责订单服务的接口设计与性能优化，把平均响应时间从 300ms 降到 120ms。', 'kind': 'bullet', 'fact_ids': [fid(2)], 'edit_ids': ['e1']},
            {'text': '使用 Kubernetes 管理 12 个微服务的发布，编写 Python 脚本自动化回滚流程。', 'kind': 'bullet', 'fact_ids': [fid(3)]},
        ]},
        {'key': 'skills', 'title': '专业技能', 'lines': [
            {'text': 'Python、Go、MySQL、Redis、Kubernetes', 'fact_ids': [fid(4)]},
        ]},
        {'key': 'edu', 'title': '教育经历', 'lines': [
            {'text': '示例大学 计算机科学与技术 本科 2017-2021', 'kind': 'head', 'fact_ids': [fid(5)]},
        ]},
    ],
}


class Formats(unittest.TestCase):
    def read_back(self, name, content):
        return rr.check_export(RENDER, name, content)

    def test_each_format_reads_back_clean(self):
        for name, content in (('r.md', rr.render_markdown(RENDER)), ('r.pdf', rr.render_pdf(RENDER)), ('r.docx', rr.render_docx(RENDER))):
            with self.subTest(name):
                check = self.read_back(name, content)
                self.assertEqual(check['missing_lines'], [], check)
                self.assertTrue(check['section_order_ok'])
                self.assertTrue(check['ok'], check)

    def test_pdf_page_count_and_limit(self):
        check = self.read_back('r.pdf', rr.render_pdf(RENDER))
        self.assertEqual(check['page_count'], 1)
        long = copy.deepcopy(RENDER)
        long['sections'][0]['lines'] += [{'text': f'第 {i} 条补充说明：负责某项模块的开发与维护工作内容。', 'kind': 'bullet'} for i in range(90)]
        check = rr.check_export(long, 'r.pdf', rr.render_pdf(long))
        self.assertGreater(check['page_count'], 2)
        self.assertFalse(check['pages_ok'])
        self.assertFalse(check['ok'])

    def test_shuffled_reading_order_is_reported(self):
        shuffled = copy.deepcopy(RENDER)
        shuffled['sections'].reverse()
        for name, content in (('r.pdf', rr.render_pdf(shuffled)), ('r.docx', rr.render_docx(shuffled)), ('r.md', rr.render_markdown(shuffled))):
            with self.subTest(name):
                check = self.read_back(name, content)  # judged against the order we meant to write
                self.assertFalse(check['section_order_ok'])
                self.assertTrue(check['out_of_order'])
                self.assertFalse(check['ok'])

    def test_changed_text_is_missing(self):
        other = copy.deepcopy(RENDER)
        other['sections'][1]['lines'][0]['text'] = 'Java、Rust'
        check = self.read_back('r.pdf', rr.render_pdf(other))
        self.assertEqual(check['missing_lines'], ['Python、Go、MySQL、Redis、Kubernetes'])

    def test_keyword_coverage_before_and_after(self):
        def explain(facts):
            text = ''.join(f['text'] for f in facts)
            return {'keywords': [{'keyword': 'Kubernetes', 'coverage': 'explicit' if 'Kubernetes' in text else 'absent'},
                                 {'keyword': 'Rust', 'coverage': 'absent'}]}
        check = rr.check_export(RENDER, 'r.pdf', rr.render_pdf(RENDER), explain=explain)
        self.assertEqual([(r['keyword'], r['before'], r['after'], r['changed']) for r in check['keyword_coverage']],
                         [('Kubernetes', '原词', '原词', False), ('Rust', '没有', '没有', False)])
        self.assertIn('不代表任何招聘系统', check['notice'])


class Font(unittest.TestCase):
    def test_all_gb2312_hanzi_are_in_the_subset(self):
        hanzi = [chr(c) for c in sorted(rr.font_chars(FONT)) if 0x4E00 <= c <= 0x9FFF]
        expected = []
        for lead in range(0xB0, 0xF8):
            for trail in range(0xA1, 0xFF):
                try:
                    expected.append(bytes((lead, trail)).decode('gb2312'))
                except UnicodeDecodeError:
                    pass
        self.assertEqual(len(expected), 6763)
        self.assertEqual(set(expected) - set(hanzi), set())

    def test_every_gb2312_hanzi_renders_and_reads_back(self):
        chars = []
        for lead in range(0xB0, 0xF8):
            for trail in range(0xA1, 0xFF):
                try:
                    chars.append(bytes((lead, trail)).decode('gb2312'))
                except UnicodeDecodeError:
                    pass
        lines = [{'text': ''.join(chars[i:i + 40])} for i in range(0, len(chars), 40)]
        render = {'sections': [{'key': 'all', 'title': '字表', 'lines': lines}]}
        self.assertEqual(rr.missing_chars(render, FONT), [])
        data = rr.render_pdf(render, FONT)
        self.assertEqual(rr.missing_chars(render, FONT), [])
        from hunt.profile.intake import analyze_resume
        text = ''.join(f['text'] for f in analyze_resume('a.pdf', data, synthetic=True)['candidate']['facts'])
        self.assertEqual(set(chars) - set(text), set())

    def test_outside_subset_is_listed_with_hint(self):
        render = copy.deepcopy(RENDER)
        render['sections'][0]['lines'][1]['text'] = '负责 𠮷 野家连锁店的收银系统开发与维护工作。'
        check = rr.check_export(render, 'r.pdf', rr.render_pdf(render))
        self.assertEqual(check['missing_chars'], ['𠮷'])
        self.assertTrue(any('HUNT_PDF_FONT' in w and '𠮷' in w for w in check['warnings']), check['warnings'])
        self.assertFalse(check['ok'])

    def test_env_font_wins_and_bad_font_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp, 'x.ttf')
            bad.write_bytes(b'not a font')
            with mock.patch.dict(os.environ, {rr.FONT_ENV: str(bad)}):
                with self.assertRaises(ValueError):
                    rr.resolve_font()
            with mock.patch.dict(os.environ, {rr.FONT_ENV: str(FONT)}):
                self.assertEqual(rr.resolve_font(), FONT)

    def test_size_budget(self):
        self.assertLess(FONT.stat().st_size, 3 * 1024 * 1024)


class Export(unittest.TestCase):
    def test_export_all_writes_files_and_trace(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp, 'v3')
            result = rr.export_all(RENDER, out, '示例-后端-v3', version=3, job_id='job1')
            self.assertEqual(set(result['files']), {'md', 'pdf', 'docx'})
            self.assertTrue(all(f['check']['ok'] for f in result['files'].values()))
            for name in os.listdir(out):
                self.assertEqual(stat.S_IMODE(os.stat(out / name).st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(os.stat(out).st_mode), 0o700)
            trace = json.loads(Path(result['trace_path']).read_text(encoding='utf-8'))
            self.assertEqual(trace['version'], 3)
            bullet = [l for l in trace['lines'] if l['edit_ids'] == ['e1']]
            self.assertEqual(bullet[0]['fact_ids'], [fid(2)])
            self.assertEqual(trace['checks'], {'md': True, 'pdf': True, 'docx': True})

    def test_missing_python_docx_only_affects_docx(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(sys.modules, {'docx': None}):
            with self.assertRaises(rr.DocxUnavailable) as caught:
                rr.render_docx(RENDER)
            self.assertIn('python-docx', str(caught.exception))
            result = rr.export_all(RENDER, Path(tmp, 'o'), 'r')
            self.assertEqual(set(result['files']), {'md', 'pdf'})
            self.assertIn('python-docx', result['errors']['docx'])


if __name__ == '__main__':
    unittest.main()
