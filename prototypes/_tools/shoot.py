"""截图并检查原型：控制台错误、横向溢出、外部请求、字体是否加载。

用法：先在 prototypes/ 下起服务 `python3 -m http.server 8777 --bind 127.0.0.1`，再运行
    python3 prototypes/_tools/shoot.py a-highlighter [route ...]
截图写到 prototypes/screenshots/，检查结果写到 prototypes/screenshots/checks-<方向>.json。
"""
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = 'http://127.0.0.1:8777'
OUT = Path(__file__).resolve().parent.parent / 'screenshots'
ROUTES = ['search', 'job/j1', 'orient', 'triage', 'settings']
SIZES = {'desktop': (1440, 900), 'mobile': (390, 844)}


def check(page):
    return page.evaluate("""() => ({
        overflowX: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
        fonts: [...document.fonts].filter(f => f.status === 'loaded').map(f => f.family + ' ' + f.weight),
        reducedMotion: matchMedia('(prefers-reduced-motion: reduce)').matches,
        dark: matchMedia('(prefers-color-scheme: dark)').matches,
    })""")


def main():
    name = sys.argv[1]
    routes = sys.argv[2:] or ROUTES
    OUT.mkdir(exist_ok=True)
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome')  # 用本机已装的 Chrome，不另下载浏览器
        # 第四项是地址参数：?fonts=windows 在 Mac 上模拟没有苹方以外中文字体的 Windows 回退（只截详情页）。
        variants = [('desktop', 'light', 'no-preference', ''), ('mobile', 'light', 'no-preference', ''),
                    ('desktop', 'dark', 'no-preference', ''), ('desktop', 'light', 'reduce', ''),
                    ('mobile', 'dark', 'no-preference', ''), ('desktop', 'light', 'no-preference', '?fonts=windows')]
        for size, scheme, motion, query in variants:
            w, h = SIZES[size]
            ctx = browser.new_context(viewport={'width': w, 'height': h}, device_scale_factor=1,
                                      color_scheme=scheme, reduced_motion=motion)
            page = ctx.new_page()
            errors, external = [], []
            page.on('console', lambda m: m.type in ('error', 'warning') and errors.append(m.text))
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.on('request', lambda r: not r.url.startswith(BASE) and not r.url.startswith('data:') and external.append(r.url))
            for route in routes:
                if query and not route.startswith('job/'):
                    continue
                if (size, scheme) == ('mobile', 'dark') and route not in ('search',) and not route.startswith('job/'):
                    continue
                page.goto(f'{BASE}/{name}/index.html{query}#/{route}')
                page.wait_for_timeout(500)
                page.evaluate('document.fonts.ready')
                tag = route.replace('/', '-')
                suffix = '-winfonts' if query else '' if (scheme, motion) == ('light', 'no-preference') else ('-dark' if scheme == 'dark' else '-reduced')
                # 只给每页的桌面和手机留全套图；深色和减少动态只截首页和详情，够看出差别。
                if suffix and route != 'search' and not route.startswith('job/'):
                    shot = None
                else:
                    shot = OUT / f'{name}-{tag}-{size}{suffix}.png'
                    page.screenshot(path=str(shot), full_page=(size == 'mobile'))
                results.append(dict(route=route, size=size, scheme=scheme, motion=motion,
                                    shot=shot.name if shot else None, **check(page)))
            results.append(dict(variant=f'{size}-{scheme}-{motion}{query}', errors=errors, external=external))
            ctx.close()
        browser.close()
    (OUT / f'checks-{name}.json').write_text(json.dumps(results, ensure_ascii=False, indent=1))
    bad = [r for r in results if r.get('errors') or r.get('external') or r.get('overflowX')]
    print(json.dumps(bad, ensure_ascii=False, indent=1) if bad else 'ok: no errors, no external requests, no horizontal overflow')


if __name__ == '__main__':
    main()
