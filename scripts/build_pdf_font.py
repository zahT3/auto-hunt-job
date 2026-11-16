"""Build the résumé PDF font subset: Noto Sans SC, wght=400, GB2312 + ASCII + common symbols, TrueType outlines.

Source font (not in the repository):
  https://github.com/google/fonts/raw/main/ofl/notosanssc/NotoSansSC%5Bwght%5D.ttf
  SHA-256 a3041811a78c361b1de50f953c805e0244951c21c5bd412f7232ef0d899af0da  (variable font, downloaded 2026-11-15)
Usage:  python3 -I scripts/build_pdf_font.py --src /tmp/ahj-font-src/NotoSansSC.ttf --out hunt/data/fonts/NotoSansSC-GB2312.ttf
Needs fonttools (pip install fonttools); it is not a runtime dependency.
"""
import argparse
import hashlib
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

SOURCE_SHA256 = 'a3041811a78c361b1de50f953c805e0244951c21c5bd412f7232ef0d899af0da'
BUDGET_BYTES = 3 * 1024 * 1024
# ASCII, Latin-1 supplement, general punctuation, arrows and a few symbols résumés use.
EXTRA = (set(range(0x20, 0x7F)) | set(range(0xA0, 0x100)) | set(range(0x2010, 0x2028)) | set(range(0x2030, 0x203B))
         | set(range(0x2190, 0x2194)) | {0x20AC, 0x2122, 0x2022, 0x25CF, 0x25A0, 0x2713, 0x2605, 0x2606})


def gb2312_chars():
    """Every character GB2312 encodes: 6763 hanzi plus its symbol rows (full-width punctuation, kana, Greek, Cyrillic)."""
    chars = set()
    for lead in range(0xA1, 0xF8):
        for trail in range(0xA1, 0xFF):
            try:
                chars.add(ord(bytes((lead, trail)).decode('gb2312')))
            except UnicodeDecodeError:
                pass
    return chars


def hanzi():
    return {c for c in gb2312_chars() if 0x4E00 <= c <= 0x9FFF}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', required=True)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    data = Path(a.src).read_bytes()
    if hashlib.sha256(data).hexdigest() != SOURCE_SHA256:
        raise SystemExit('source font hash mismatch')
    font = TTFont(a.src)
    font = instancer.instantiateVariableFont(font, {'wght': 400})
    options = subset.Options()
    options.layout_features = ['kern', 'locl']
    options.name_IDs = [0, 1, 2, 3, 4, 5, 6, 13, 14]
    options.notdef_outline = True
    options.glyph_names = False
    options.hinting = False
    sub = subset.Subsetter(options)
    sub.populate(unicodes=sorted(gb2312_chars() | EXTRA))
    sub.subset(font)
    font.flavor = None
    # The default instance of the variable font is named "Thin"; this one is the 400 instance.
    for record in font['name'].names:
        if record.nameID in (1, 4, 16): record.string = 'Noto Sans SC'
        elif record.nameID == 3: record.string = '2.004;ADBO;NotoSansSC-Regular;ADOBE'
        elif record.nameID == 6: record.string = 'NotoSansSC-Regular'
    font['OS/2'].usWeightClass = 400
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    font.save(a.out)
    size = Path(a.out).stat().st_size
    print(f'{a.out}: {size} bytes ({size / 1024 / 1024:.2f} MiB), hanzi {len(hanzi())}')
    if size > BUDGET_BYTES:
        raise SystemExit('over the 3 MB budget: narrow the symbol set')


if __name__ == '__main__':
    main()
