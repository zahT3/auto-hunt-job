"""Build a reviewable source archive from an explicit, privacy-bounded allowlist."""
import hashlib
import json
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = ['README.md', 'LICENSE', 'SECURITY.md', 'CONTRIBUTING.md',
         'THIRD_PARTY_NOTICES.md', '.gitignore', 'requirements.txt',
         'requirements-executor.txt', 'run.py', 'setup.sh', 'Start.command',
         'docs/official-sources.md', 'docs/v3-acceptance.md', 'docs/search-research.md', 'docs/boss-white-screen.md', 'docs/discovery-api.md', 'docs/usage.md', 'docs/v2-acceptance.md']
PATTERNS = ['hunt/*.py', 'static/*.js', 'static/*.css', 'static/*.html',
            'tests/test_*.py', 'tests/test_*.cjs', 'tests/fixtures/*.html', 'tests/fixtures/*.json',
            'examples/*.json', 'examples/*.txt', 'examples/*.py',
            'scripts/build_release.py', '.github/workflows/*.yml']


def source_files():
    paths = {ROOT / name for name in FILES if (ROOT / name).is_file()}
    for pattern in PATTERNS:
        paths.update(ROOT.glob(pattern))
    return sorted(paths)


def audit(paths):
    issues = []
    for path in paths:
        relative = path.relative_to(ROOT).as_posix()
        if path.is_symlink() or not path.is_file():
            issues.append(relative + ': symlink or not a regular file')
            continue
        if any(p in {'private', '.venv', '.env', '__pycache__', '.git'} for p in path.relative_to(ROOT).parts):
            issues.append(relative + ': private path')
        text = path.read_text(encoding='utf-8')
        patterns = [r'\x2fUsers\x2f[^/\s]+/', r'gh[pousr]_[A-Za-z0-9]{30,}',
                    r'-----BEGIN (?:RSA |OPENSSH )?PRIVATE KEY-----',
                    r'sk-[A-Za-z0-9_-]{32,}']
        for pattern in patterns:
            if re.search(pattern, text):
                issues.append(relative + ': personal path or credential-like content')
    if issues:
        raise ValueError('\n'.join(issues))


def main():
    paths = source_files()
    audit(paths)
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


if __name__ == '__main__':
    main()
