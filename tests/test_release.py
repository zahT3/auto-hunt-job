import contextlib
import importlib.util
import io
from pathlib import Path
import subprocess
import tempfile
import unittest

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

    def test_check_returns_zero_on_clean_repo(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(build_release.main(['--check']), 0)
        self.assertIn('tracked files', out.getvalue())


if __name__ == '__main__':
    unittest.main()
