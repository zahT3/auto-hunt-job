import contextlib
import importlib.util
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
import unittest.mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('build_release', ROOT / 'scripts' / 'build_release.py')
build_release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_release)


class ReleaseCheckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def track(self, name, content, force=False):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding='utf-8')
        subprocess.run(['git', 'add'] + (['-f'] if force else []) + [name], cwd=self.root, check=True)
        return path

    def init(self):
        subprocess.run(['git', 'init', '-q'], cwd=self.root, check=True)

    def test_source_files_lists_only_tracked(self):
        self.init()
        self.track('a.py', 'x = 1\n')
        (self.root / 'b.py').write_text('y = 2\n', encoding='utf-8')
        self.assertEqual([p.name for p in build_release.source_files(self.root)], ['a.py'])

    def test_source_files_requires_git(self):
        with self.assertRaisesRegex(RuntimeError, 'not a git checkout'):
            build_release.source_files(self.root)

    def test_audit_flags_personal_path(self):
        self.init()
        self.track('notes.md', 'see \x2fUsers\x2falice/x\n')
        with self.assertRaisesRegex(ValueError, 'notes.md'):
            build_release.audit(build_release.source_files(self.root), self.root)

    def test_audit_flags_private_dir(self):
        self.init()
        self.track('private/x.txt', 'data\n', force=True)
        with self.assertRaisesRegex(ValueError, 'private/x.txt'):
            build_release.audit(build_release.source_files(self.root), self.root)

    def test_audit_skips_binary_content(self):
        self.init()
        self.track('b.png', b'\xff\xfe\x00')
        build_release.audit(build_release.source_files(self.root), self.root)

    def test_audit_reports_tracked_but_missing(self):
        self.init()
        self.track('gone.py', 'x = 1\n').unlink()
        with self.assertRaisesRegex(ValueError, 'gone.py: tracked but missing'):
            build_release.audit(build_release.source_files(self.root), self.root)

    def test_source_files_explains_missing_git(self):
        with unittest.mock.patch.object(build_release.subprocess, 'run', side_effect=FileNotFoundError):
            with self.assertRaisesRegex(RuntimeError, 'git is not installed'):
                build_release.source_files(self.root)

    def test_source_files_includes_git_stderr(self):
        with self.assertRaisesRegex(RuntimeError, '(?i)not a git repository'):
            build_release.source_files(self.root)

    def test_check_reports_runtime_error_without_traceback(self):
        with unittest.mock.patch.object(build_release, 'source_files', side_effect=RuntimeError('not a git checkout: x')):
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(build_release.main(['--check']), 1)
        self.assertIn('not a git checkout', out.getvalue())

    def test_audit_scans_non_utf8_text(self):
        self.init()
        self.track('gbk.txt', '路径 \x2fUsers\x2falice/x'.encode('gbk'))
        with self.assertRaisesRegex(ValueError, 'gbk.txt'):
            build_release.audit(build_release.source_files(self.root), self.root)

    def test_audit_flags_linux_and_windows_home_paths(self):
        self.init()
        self.track('linux.md', '\x2fhome\x2falice/x\n')
        self.track('win.md', 'C:\\\\Users\\\\alice\\\\x\n'.replace('\\\\', '\\'))
        with self.assertRaises(ValueError) as caught:
            build_release.audit(build_release.source_files(self.root), self.root)
        self.assertIn('linux.md', str(caught.exception))
        self.assertIn('win.md', str(caught.exception))

    def test_audit_flags_personal_email_only(self):
        self.init()
        self.track('personal.md', 'mail alice' + '@' + 'gmail.com\n')
        self.track('company.md', 'hr' + '@' + 'token.im and a' + '@' + 'example.invalid\n')
        with self.assertRaises(ValueError) as caught:
            build_release.audit(build_release.source_files(self.root), self.root)
        self.assertIn('personal.md', str(caught.exception))
        self.assertNotIn('company.md', str(caught.exception))

    def test_check_returns_zero_on_clean_repo(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(build_release.main(['--check']), 0)
        self.assertIn('tracked files', out.getvalue())


if __name__ == '__main__':
    unittest.main()
