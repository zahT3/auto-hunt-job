#!/bin/sh
# Rebuild hunt/data/fonts/NotoSansSC-GB2312.ttf (résumé PDF font). Source font and hash: see scripts/build_pdf_font.py.
# Download the source into $SRC (default /tmp/ahj-font-src/NotoSansSC.ttf); it is never committed. Needs fonttools.
set -e
SRC=${SRC:-/tmp/ahj-font-src}
ROOT=$(cd "$(dirname "$0")/.." && pwd)
python3 -I "$ROOT/scripts/build_pdf_font.py" --src "$SRC/NotoSansSC.ttf" --out "$ROOT/hunt/data/fonts/NotoSansSC-GB2312.ttf"
