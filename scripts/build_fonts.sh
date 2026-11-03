#!/bin/sh
# Rebuild the interface font subset in static/fonts/ from the UI text actually shipped in static/.
# Run it after adding or changing fixed Chinese UI text; tests/test_frontend.cjs fails when a character is missing.
#
# Source fonts are not in the repository. Download them from google/fonts into $SRC (default /tmp/ahj-font-src):
#   ofl/notosanssc/NotoSansSC[wght].ttf  -> $SRC/NotoSansSC.ttf  (SHA-256 starts a3041811)
# The Inter subset (static/fonts/inter.woff2) holds Latin only and does not depend on the UI text.
# Needs fonttools and brotli (pip install fonttools brotli).
set -e
SRC=${SRC:-/tmp/ahj-font-src}
ROOT=$(cd "$(dirname "$0")/.." && pwd)
OUT=$ROOT/static/fonts
python3 -I "$ROOT/prototypes/_tools/subset_fonts.py" --src "$SRC/NotoSansSC.ttf" --out "$OUT/sans-ui.woff2" \
  --scan "$ROOT/static/index.html" $(find "$ROOT/static/js" -name '*.js' | sort) --wght 400:700
du -ch "$OUT"/*.woff2 | tail -1
