"""Build hunt/data/companies.cn.json from hunt/catalog.py and career-ops-china's portals template.

The upstream template lives under private/research/upstream (git-ignored), so the committed JSON is the
artifact; rerun this script only when the pinned upstream changes. Seed data is derived from
https://github.com/shuheng-mo/career-ops-china (MIT), templates/portals-china.example.yml.
"""
import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

UPSTREAM_REPO = 'shuheng-mo/career-ops-china'
TEMPLATE = 'templates/portals-china.example.yml'
DEFAULT_UPSTREAM = ROOT / 'private' / 'research' / 'upstream'
OUT = ROOT / 'hunt' / 'data' / 'companies.cn.json'
FIXED = [dict(id='tencent', name='腾讯', careers_url='https://careers.tencent.com/', provider='tencent', tags=['大厂', '互联网', 'AI', '数据']),
         dict(id='alibaba', name='阿里巴巴', careers_url='https://talent.alibaba.com/', provider='alibaba', tags=['大厂', '互联网', 'AI', '数据', '云']),
         dict(id='meituan', name='美团', careers_url='https://zhaopin.meituan.com/', provider='meituan', tags=['大厂', '互联网', '数据', '算法', '广告']),
         dict(id='bytedance', name='字节跳动', careers_url='https://jobs.bytedance.com', provider='feishu', tags=['大厂', '互联网', 'AI', '数据', '推荐'])]
# The upstream template tracks only ~44 companies, so these well-known employers are added by hand. Each URL
# answered HTTP 200 (after redirects) on the generation date; whether a page lists open roles was not checked.
EXTRA = [('huawei', '华为', 'https://career.huawei.com/reccampportal/portal5/index.html', ['大厂', '硬件', 'AI', '云']),
         ('xiaomi', '小米', 'https://hr.xiaomi.com/', ['大厂', '硬件', 'AI', '汽车']),
         ('antgroup', '蚂蚁集团', 'https://talent.antgroup.com/', ['大厂', '金融科技', 'AI', '数据']),
         ('ctrip', '携程', 'https://job.ctrip.com/', ['互联网', '旅游', '数据']),
         ('mihoyo', '米哈游', 'https://jobs.mihoyo.com/', ['游戏', 'AI']),
         ('dji', '大疆', 'https://careers.dji.com/zh-CN/', ['硬件', '机器人', '算法']),
         ('lixiang', '理想汽车', 'https://www.lixiang.com/employ.html', ['汽车', '智能驾驶', '算法']),
         ('xiaopeng', '小鹏汽车', 'https://xiaopeng.jobs.feishu.cn/', ['汽车', '智能驾驶', '算法']),
         ('nio', '蔚来', 'https://nio.jobs.feishu.cn/', ['汽车', '智能驾驶', '算法']),
         ('oppo', 'OPPO', 'https://careers.oppo.com/', ['硬件', '终端', 'AI']),
         ('pony-ai', '小马智行', 'https://pony.ai/careers', ['智能驾驶', '算法', 'AI']),
         ('weride', '文远知行', 'https://www.weride.ai/careers', ['智能驾驶', '算法', 'AI']),
         ('zhihu', '知乎', 'https://app.mokahr.com/apply/zhihu/78336', ['互联网', '内容', '社区'])]
# Result of the first real sweep (2026-10-26, keyword 'AI 产品经理'): `dead` answered HTTP 404, `needs_adapter`
# gave the generic website reader a parse_error. Sweeps skip both unless asked; the rows stay for a later recheck.
STATUS = dict.fromkeys((
    'baichuan-ai-com-careers',
    'modelbest-cn-careers',
    'manus-im-careers',
    'luchentech-com-joinus',
    'sensetime-com-cn-career',
    'langboat-com-careers',
    'talent-baidu-com-external-baidu-social-h',
    'starrocks-io-careers',
    'sensorsdata-cn-about-job-html',
), 'dead') | dict.fromkeys((
    'huawei',
    'xiaomi',
    'antgroup',
    'mihoyo',
    'oppo',
    'pony-ai',
    'zhaopin-kuaishou-cn-recruit-e',
    'jobs-bilibili-com-campus-positions',
    'hr-163-com-job-list-html',
    'zhipuai-cn-joinus',
    '01-ai-careers',
    'siliconflow-cn-zh-cn-about',
    'infini-ai-com-careers',
    '4paradigm-com-about-jobs-html',
    'ctrip',
    'dji',
    'lixiang',
    'join-jd-com-home',
    'pingcap-com-careers',
    'deepexi-com-about-us',
    'doris-apache-org',
    'apply-workable-com-huggingface',
), 'needs_adapter')
# Upstream rows for companies that already have a dedicated reader in hunt/catalog.py.
CATALOG_COVERS = ('DeepSeek', '月之暗面', 'MiniMax', '阶跃星辰')
SECTION_TAGS = (('大厂', ['大厂', '互联网']), ('大模型', ['AI', '大模型']), ('AI 应用', ['AI', '应用']),
                ('数据 &', ['数据', '数据库']), ('AI Infra', ['AI', 'Infra', '推理']), ('远程', ['远程', '海外']))
NOTE_TAGS = ('数据', '大模型', 'AI', 'Agent', '推理', '搜索', '推荐', '广告', '算法', '数据库', '云', '安全', '游戏', '多模态', 'NLP', 'OLAP')


def _value(raw):
    raw = raw.strip()
    if raw[:1] in '"\'' and raw.count(raw[0]) >= 2:
        return raw[1:raw.index(raw[0], 1)]
    return re.split(r'\s+#', raw, maxsplit=1)[0].strip()


def read_tracked_companies(text):
    """The flat `tracked_companies:` list of the upstream template; no general YAML support."""
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line.rstrip() == 'tracked_companies:'), None)
    if start is None: raise ValueError('没有找到 tracked_companies 段')
    rule = re.compile(r'\s*#\s*=+\s*$')
    rows, section = [], ''
    for i in range(start + 1, len(lines)):
        line = lines[i]
        if re.match(r'[A-Za-z_]\w*:', line): break
        if line.startswith('  # ') and not rule.match(line) and i + 1 < len(lines) and rule.match(lines[i - 1]) and rule.match(lines[i + 1]):
            section = line.strip().lstrip('#').strip()
        item = re.match(r'  - name:\s*(.+)$', line)
        field = re.match(r'    (\w+):\s*(.*)$', line)
        if item:
            rows.append(dict(name=_value(item.group(1)), section=section, enabled=True))
        elif field and rows:
            value = _value(field.group(2))
            rows[-1][field.group(1)] = (value == 'true') if field.group(1) == 'enabled' else value
    return rows


def _tags(section, name, notes):
    tags = [t for key, found in SECTION_TAGS if key in section for t in found]
    haystack = (name + ' ' + notes).lower()
    tags += [t for t in NOTE_TAGS if t.lower() in haystack]
    return list(dict.fromkeys(tags))


def _slug(url, taken):
    parts = urlsplit(url)
    base = re.sub(r'[^a-z0-9]+', '-', (re.sub(r'^www\.', '', parts.hostname or '') + parts.path).lower()).strip('-')[:40] or 'company'
    ident, n = base, 2
    while ident in taken:
        ident, n = '%s-%d' % (base, n), n + 1
    return ident


def _key(url):
    parts = urlsplit(url)
    return (parts.hostname or '').lower(), parts.path.rstrip('/')


def build(rows):
    from hunt.catalog import CATALOG
    from hunt.providers import route
    def provider_of(url):
        found = route(dict(careers_url=url))
        return found.id if found else None
    seeds = [dict(s, source='career-ops-china') for s in FIXED]
    for r in CATALOG:
        seeds.append(dict(id=r['id'], name=r['company'], careers_url=r['url'], provider=provider_of(r['url']),
                          tags=[t.strip() for t in re.split(r'/', r['category'])], source='catalog'))
    for ident, name, url, tags in EXTRA:
        seeds.append(dict(id=ident, name=name, careers_url=url, provider=provider_of(url), tags=tags, source='curated'))
    seen = {_key(s['careers_url']) for s in seeds}
    taken = {s['id'] for s in seeds}
    for row in rows:
        url = row.get('careers_url', '')
        if not row.get('enabled') or not url or any(row['name'].startswith(n) for n in CATALOG_COVERS): continue
        provider = provider_of(url)
        # The fixed rows cover these hosts; their providers search by keyword and ignore the URL path.
        if provider in ('tencent', 'alibaba', 'meituan', 'feishu') or _key(url) in seen: continue
        seen.add(_key(url))
        ident = _slug(url, taken); taken.add(ident)
        seeds.append(dict(id=ident, name=row['name'], careers_url=url, provider=provider,
                          tags=_tags(row['section'], row['name'], row.get('notes', '')), source='career-ops-china'))
    return [dict(s, status=STATUS[s['id']]) if s['id'] in STATUS else s for s in seeds]


def pinned_commit(pins):
    for line in pins.read_text(encoding='utf-8').splitlines():
        fields = line.split()
        if fields[:1] == [UPSTREAM_REPO]: return fields[1]
    raise ValueError(str(pins) + ' 中没有 ' + UPSTREAM_REPO)


def main(argv=None):
    parser = argparse.ArgumentParser(description='从上游模板和内置目录生成公司种子 JSON')
    parser.add_argument('--upstream', type=Path, default=DEFAULT_UPSTREAM, help='含 pins.txt 与 coc/ 的目录')
    parser.add_argument('--out', type=Path, default=OUT)
    args = parser.parse_args(argv)
    template = args.upstream / 'coc' / TEMPLATE
    try:
        if not template.is_file():
            raise FileNotFoundError('找不到上游模板 %s；它在 git 忽略的 private/research/upstream 下，需先取得 %s 的该文件' % (template, UPSTREAM_REPO))
        commit = pinned_commit(args.upstream / 'pins.txt')
        rows = read_tracked_companies(template.read_text(encoding='utf-8'))
        seeds = build(rows)
    except (OSError, ValueError) as error:
        print('错误：' + str(error), file=sys.stderr)
        return 1
    data = dict(schema_version=1, generated_from=dict(repo=UPSTREAM_REPO, commit=commit, file=TEMPLATE, license='MIT'), companies=seeds)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    counts = {}
    for s in seeds: counts[s['provider'] or 'website'] = counts.get(s['provider'] or 'website', 0) + 1
    skipped = sum(not r.get('careers_url') for r in rows)
    print('已写入 %s：%d 家 %s；跳过 %d 行（没有 careers_url）' % (args.out, len(seeds), counts, skipped))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
