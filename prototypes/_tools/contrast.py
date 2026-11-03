"""从三个原型的 style.css 读出颜色变量，按 WCAG 2.x 公式算文字对比度，输出 Markdown 表。

用法：python3 prototypes/_tools/contrast.py > research/contrast.md
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# (前景, 背景, 用途, 最低要求)。正文和小字按 4.5，18.66px 粗体 / 24px 以上和图形元素按 3。
PAIRS = {
    'final': [
        ('ink', 'paper', '正文', 4.5), ('ink-2', 'paper', '辅助文字', 4.5), ('ink-3', 'paper', '第三级文字（键帽、表头、编号）', 4.5),
        ('ink-2', 'wash', '选中行上的辅助文字', 4.5), ('ink-3', 'wash-2', '当前导航上的计数', 4.5),
        ('ok', 'paper', '状态：仍在列表 / 符合 / 有事实', 4.5), ('warn', 'paper', '状态：近几天没搜到 / 相近说法', 4.5),
        ('bad', 'paper', '不符合 / 没有', 4.5), ('pen', 'paper', '批注、AI 说的话', 4.5), ('pen', 'wash', '选中行旁的 AI 标签', 4.5),
        ('on-marker', 'marker', '荧光笔黄底上的字', 4.5), ('paper', 'ink', '主按钮文字', 4.5), ('ok', 'wash', '选中行上的状态字', 4.5),
    ],
    'a-highlighter': [
        ('ink', 'paper', '正文', 4.5), ('ink-2', 'paper', '辅助文字', 4.5), ('ink-3', 'paper', '第三级文字（键帽、表头）', 4.5),
        ('ink-2', 'wash', '选中行上的辅助文字', 4.5), ('ink-3', 'wash-2', '当前导航上的计数', 4.5),
        ('ok', 'paper', '状态：新发布 / 符合', 4.5), ('warn', 'paper', '状态：可能下线 / 待确认', 4.5), ('bad', 'paper', '状态：失败 / 缺少', 4.5),
        ('on-marker', 'marker', '荧光笔黄底上的字', 4.5), ('paper', 'ink', '主按钮文字', 4.5),
    ],
    'b-marginalia': [
        ('ink', 'paper', '正文', 4.5), ('ink-2', 'paper', '辅助文字', 4.5), ('ink-3', 'paper', '段落编号、表头', 4.5),
        ('ink-2', 'desk', '纸外的导航文字', 4.5), ('pen', 'paper', '批注、链接、符合', 4.5), ('red', 'paper', '缺少、失败', 4.5),
        ('amber', 'paper', '风险、待确认', 4.5), ('pen', 'pen-soft', '选中项文字', 4.5),
    ],
    'c-postal': [
        ('ink', 'paper', '正文', 4.5), ('ink-2', 'paper', '辅助文字', 4.5), ('ink-3', 'paper', '第三级文字', 4.5),
        ('ink-2', 'table', '桌面底上的辅助文字', 4.5), ('green-text', 'paper', '状态：在招 / 符合', 4.5), ('red', 'paper', '失败、缺少', 4.5),
        ('amber', 'paper', '风险、待确认', 4.5), ('#ffffff', 'green', '绿色顶栏和格口上的白字', 4.5), ('#dcebe2', 'green', '顶栏上的次要文字', 4.5),
        ('ink', 'green-soft', '选中框里的字', 4.5),
    ],
}
DARK_OVERRIDES = {}
DARK_EXTRA = {}


def lum(hexc):
    hexc = hexc.lstrip('#')
    if len(hexc) == 3:
        hexc = ''.join(c * 2 for c in hexc)
    r, g, b = (int(hexc[i:i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def ratio(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def tokens(css):
    light_block = re.search(r':root\s*\{(.*?)\n\}', css, re.S).group(1)
    dark_m = re.search(r'prefers-color-scheme:\s*dark\)\s*\{(.*?)\n\}', css, re.S)
    grab = lambda s: dict(re.findall(r'--([\w-]+):\s*(#[0-9a-fA-F]{3,6})', s))
    light = grab(light_block)
    dark = dict(light)
    if dark_m:
        dark.update(grab(dark_m.group(1)))
    return light, dark


def main():
    print('# 文字对比度（WCAG 2.x）\n')
    print('由 `prototypes/_tools/contrast.py` 从各原型 `style.css` 的颜色变量算出。要求：正文与小字 ≥ 4.5:1。\n')
    for name, pairs in PAIRS.items():
        css = (ROOT / name / 'style.css').read_text(encoding='utf-8')
        light, dark = tokens(css)
        dark.update(DARK_OVERRIDES.get(name, {}))
        print(f'## {name}\n')
        print('| 用途 | 前景 / 背景 | 浅色 | 深色 |')
        print('| --- | --- | --- | --- |')
        worst = []
        for fg, bg, use, need in pairs + DARK_EXTRA.get(name, []):
            cells = []
            for mode in (light, dark):
                f = fg if fg.startswith('#') else mode.get(fg)
                b = bg if bg.startswith('#') else mode.get(bg)
                if not f or not b:
                    cells.append('—')
                    continue
                r = ratio(f, b)
                ok = '' if r >= need else ' 未达标'
                if r < need:
                    worst.append(use)
                cells.append(f'{r:.2f}:1{ok}')
            print(f'| {use} | `{fg}` / `{bg}` | {cells[0]} | {cells[1]} |')
        print(f'\n未达标：{"、".join(worst) if worst else "无"}\n')


if __name__ == '__main__':
    main()
