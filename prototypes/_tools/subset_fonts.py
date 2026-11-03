"""按界面实际用到的字生成 woff2 子集。

中文字体只给固定的界面文字用（导航、标题、按钮、标签），所以只扫界面代码里的字，不扫数据。
JD 原文、公司名这些动态内容继续用系统字体；万一界面字体里缺字，浏览器会逐字回退到系统字体，不会出现豆腐块。
拉丁 / 数字字体整套保留基本拉丁和常用标点。

用法：
    python3 -I subset_fonts.py --src NotoSansSC.ttf --out ui-sans.woff2 --scan app.js index.html --wght 400:700
    python3 -I subset_fonts.py --src Inter.ttf --out inter.woff2 --latin --wght 300:700 --pin opsz=14
可多次 --scan；--wght / --wdth 用 min:max 收窄可变轴，--pin 把某个轴固定成一个值。
依赖：fonttools、brotli（pip install fonttools brotli）。源字体不进仓库，从 google/fonts 的 ofl/ 目录下载。
"""
import argparse
import re
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

# 基本拉丁、拉丁补充、常用标点与符号（含 ¥、·、—、…、‘’“”、→、⌘、↵）。
LATIN = (set(range(0x20, 0x7F)) | set(range(0xA0, 0x100)) | set(range(0x2010, 0x2028))
         | set(range(0x2030, 0x203B)) | {0x20AC, 0x2122, 0x2190, 0x2191, 0x2192, 0x2193, 0x21B5, 0x2318, 0x2715, 0x2713})
CJK = re.compile(r'[　-〿㐀-䶿一-鿿＀-￯‘’“”—…·]')
FEATURES = ['kern', 'liga', 'calt', 'ccmp', 'locl', 'mark', 'mkmk', 'tnum', 'pnum', 'lnum', 'case', 'zero',
            'ss01', 'cv11', 'halt', 'palt', 'vpal', 'chws']


def scan(paths):
    chars = set()
    for p in paths:
        text = Path(p).read_text(encoding='utf-8')
        chars |= {ord(c) for c in CJK.findall(text)}
    return chars


def axis(spec):
    lo, hi = spec.split(':')
    return (float(lo), float(hi))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--scan', nargs='*', default=[])
    ap.add_argument('--latin', action='store_true', help='包含基本拉丁和常用标点')
    ap.add_argument('--wght')
    ap.add_argument('--wdth')
    ap.add_argument('--pin', action='append', default=[], help='例如 opsz=14')
    a = ap.parse_args()

    font = TTFont(a.src)
    limits = {}
    if a.wght: limits['wght'] = axis(a.wght)
    if a.wdth: limits['wdth'] = axis(a.wdth)
    for pin in a.pin:
        k, v = pin.split('=')
        limits[k] = float(v)

    unicodes = scan(a.scan)
    if a.latin:
        unicodes |= LATIN
    else:
        # 中文界面字体也带上数字和基本标点，避免一行里中文和数字来自两套字体。
        unicodes |= set(range(0x20, 0x7F))
    opts = subset.Options()
    opts.flavor = 'woff2'
    opts.layout_features = FEATURES
    opts.name_IDs = ['*']
    opts.name_legacy = True
    opts.notdef_outline = True
    sub = subset.Subsetter(opts)
    sub.populate(unicodes=unicodes)
    sub.subset(font)
    # 先子集再收窄轴：反过来做时 fontTools 会在 gvar 上报 KeyError。
    if limits:
        font = instancer.instantiateVariableFont(font, limits)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    font.flavor = 'woff2'
    font.save(a.out)
    kept = len(font.getBestCmap())
    print(f'{a.out}: {Path(a.out).stat().st_size / 1024:.1f} KB, {kept} 个字符, 轴 {limits or "全保留"}')


if __name__ == '__main__':
    main()
