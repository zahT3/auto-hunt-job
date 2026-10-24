"""Check tracked files for private data, and optionally build a reviewable source archive from them.

The archive packs the working-tree content of tracked files, so commit first when it should match HEAD."""
import hashlib
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = [r'\x2f(?:Users|home)\x2f[^/\s]+/', r'[A-Za-z]:\\Users\\[^\\\s]+\\',
            r'gh[pousr]_[A-Za-z0-9]{30,}', r'-----BEGIN (?:RSA |OPENSSH )?PRIVATE KEY-----',
            r'sk-[A-Za-z0-9_-]{32,}',
            # Company and example addresses are expected; personal mailboxes are not.
            r'[A-Za-z0-9._%+-]+@(?:gmail|qq|163|126|outlook|hotmail|icloud|yahoo|foxmail|sina)\.(?:com|cn)\b']


def source_files(root=ROOT):
    """Everything git tracks is what gets published; ignored files never reach the check."""
    try:
        result = subprocess.run(['git', '-C', str(root), 'ls-files', '-z'], capture_output=True)
    except FileNotFoundError:
        raise RuntimeError('git is not installed; install git to list tracked files') from None
    if result.returncode != 0:
        detail = result.stderr.decode('utf-8', 'replace').strip()
        raise RuntimeError('not a git checkout: ' + str(root) + ('\n' + detail if detail else ''))
    return sorted(root / name for name in result.stdout.decode('utf-8').split('\0') if name)


def audit(paths, root=ROOT):
    issues = []
    for path in paths:
        relative = path.relative_to(root).as_posix()
        if not path.exists() and not path.is_symlink():
            issues.append(relative + ': tracked but missing')
            continue
        if path.is_symlink() or not path.is_file():
            issues.append(relative + ': symlink or not a regular file')
            continue
        if any(p in {'private', '.venv', '.env', '__pycache__', '.git'} for p in path.relative_to(root).parts):
            issues.append(relative + ': private path')
        # Paths, keys and emails are ASCII, so lossy decoding still finds them in GBK or binary files.
        text = path.read_bytes().decode('utf-8', 'replace')
        for pattern in PATTERNS:
            if re.search(pattern, text):
                issues.append(relative + ': personal path or credential-like content')
    if issues:
        raise ValueError('\n'.join(issues))


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        paths = source_files()
        audit(paths)
    except (RuntimeError, ValueError) as issues:
        print(issues)
        return 1
    if '--check' in argv:
        print('checked ' + str(len(paths)) + ' tracked files')
        return 0
    out = ROOT / 'private' / 'release'
    out.mkdir(parents=True, exist_ok=True)
    manifest = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    # Content-addressed archive preserves previous reviewable versions.
    version = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()[:12]
    archive = out / ('auto-hunt-job-' + version + '.zip')
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as package:
        for path in paths:
            package.write(path, 'auto-hunt-job/' + path.relative_to(ROOT).as_posix())
        package.writestr('auto-hunt-job/SOURCE_MANIFEST.json', json.dumps(manifest, indent=2))
    result = dict(archive=str(archive), files=len(paths), sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
                  source='git ls-files (exclusions come from .gitignore)')
    (out / 'latest.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
