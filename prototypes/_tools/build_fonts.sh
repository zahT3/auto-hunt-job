#!/bin/sh
# 生成三个原型用的字体子集。源字体从 google/fonts 下载到 $SRC（默认 /tmp/ahj-font-src），不进仓库：
#   ofl/inter/Inter[opsz,wght].ttf  ofl/notosanssc/NotoSansSC[wght].ttf
#   ofl/notoserifsc/NotoSerifSC[wght].ttf  ofl/archivo/Archivo[wdth,wght].ttf  以及各自的 OFL.txt
# 改了界面文字之后要重新跑一次，否则新加的字会回退到系统字体。
set -e
SRC=${SRC:-/tmp/ahj-font-src}
HERE=$(cd "$(dirname "$0")/.." && pwd)
OUT=$HERE/_shared/fonts
PY="python3 -I $HERE/_tools/subset_fonts.py"
mkdir -p "$OUT"
$PY --src "$SRC/Inter.ttf" --out "$OUT/inter.woff2" --latin --wght 300:700
$PY --src "$SRC/NotoSansSC.ttf" --out "$OUT/sans-a.woff2" --scan "$HERE/a-highlighter/app.js" "$HERE/a-highlighter/index.html" --wght 400:700
$PY --src "$SRC/NotoSerifSC.ttf" --out "$OUT/serif-b.woff2" --scan "$HERE/b-marginalia/app.js" "$HERE/b-marginalia/index.html" --wght 400:900
$PY --src "$SRC/Archivo.ttf" --out "$OUT/archivo.woff2" --latin --wght 400:900 --wdth 62:100
$PY --src "$SRC/NotoSansSC.ttf" --out "$OUT/sans-final.woff2" --scan "$HERE/final/app.js" "$HERE/final/index.html" --wght 400:700
$PY --src "$SRC/NotoSansSC.ttf" --out "$OUT/sans-c.woff2" --scan "$HERE/c-postal/app.js" "$HERE/c-postal/index.html" --wght 500:900
for f in inter notosanssc notoserifsc archivo; do cp "$SRC/OFL-$f.txt" "$OUT/OFL-$f.txt"; done
du -ch "$OUT"/*.woff2 | tail -1
