"""Check tracked files for private data, and optionally build a reviewable source archive from them."""
import hashlib
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def source_files(root=ROOT):
    """Everything git tracks is what gets published; ignored files never reach the check."""
    result = subprocess.run(['git', '-C', str(root), 'ls-files', '-z'], capture_output=True)
    if result.returncode != 0:
        raise RuntimeError('not a git checkout: ' + str(root))
    return sorted(root / name for name in result.stdout.decode('utf-8').split('\0') if name)


def audit(paths, root=ROOT):
    issues = []
    for path in paths:
        relative = path.relative_to(root).as_posix()
        if path.is_symlink() or not path.is_file():
            issues.append(relative + ': symlink or not a regular file')
            continue
        if any(p in {'private', '.venv', '.env', '__pycache__', '.git'} for p in path.relative_to(root).parts):
            issues.append(relative + ': private path')
        try:
            text = path.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            continue
        patterns = [r'\x2fUsers\x2f[^/\s]+/', r'gh[pousr]_[A-Za-z0-9]{30,}',
                    r'-----BEGIN (?:RSA |OPENSSH )?PRIVATE KEY-----',
                    r'sk-[A-Za-z0-9_-]{32,}']
        for pattern in patterns:
            if re.search(pattern, text):
                issues.append(relative + ': personal path or credential-like content')
    if issues:
        raise ValueError('\n'.join(issues))


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    paths = source_files()
    try:
        audit(paths)
    except ValueError as issues:
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
                  excluded=['private/', '.venv/', 'internal work journal', 'historical personal research'])
    (out / 'latest.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
