"""python -m hunt scan: bounded read-only job search from the command line; never sends a resume or application."""
import argparse
import json
from pathlib import Path

from ..catalog import boards
from ..core import Store
from ..discovery import DEFAULT_KINDS, discover
from ..providers import REGISTRY


def main():
    parser = argparse.ArgumentParser(description='本地多渠道只读岗位搜索；不发送简历或申请')
    parser.add_argument('--source', action='append', choices=sorted(REGISTRY))
    parser.add_argument('--keyword', action='append', default=[])
    parser.add_argument('--browser-source', action='append', choices=['boss','liepin'], default=[])
    parser.add_argument('--headless', action='store_true')
    parser.add_argument('--browser', choices=('chromium', 'chrome'), default='chromium')
    parser.add_argument('--official-only', action='store_true', help='本轮只查公司招聘来源，跳过 BOSS、猎聘与网页索引')
    parser.add_argument('--catalog', action='append', help='内置公司 ID，可重复；all 表示全部')
    parser.add_argument('--official-browser', action='store_true', help='启用无登录资料的公开页面渲染，仅只读')
    parser.add_argument('--skip-entry-checks', action='store_true')
    parser.add_argument('--career-url', action='append', default=[], help='公司招聘页 HTTPS URL；可重复')
    parser.add_argument('--profile-root', type=Path)
    parser.add_argument('--data', type=Path, help='与工作台相同的数据目录')
    parser.add_argument('--max-jobs', type=int, default=12)
    parser.add_argument('--max-pages', type=int, default=2)
    parser.add_argument('--requests', type=int, default=30)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    keywords = args.keyword
    if not keywords and args.data:
        keywords = (Store(args.data).orientation() or {}).get('terms') or []
    if not keywords: parser.error('请用 --keyword 指定搜索词，或用 --data 指向已确定方向的数据目录')
    config = dict(sources=list(dict.fromkeys((args.source or DEFAULT_KINDS) + args.browser_source)), keywords=keywords,
                  source_modes={kind:'browser' for kind in args.browser_source}, max_jobs=args.max_jobs,
                  max_pages=args.max_pages, discovery_requests=args.requests)
    config.update(official_only=args.official_only, browser_channel='chrome' if args.browser == 'chrome' else None)
    config.update(check_entries=not args.skip_entry_checks, official_browser=args.official_browser)
    if args.catalog:
        config['company_boards'] = boards(None if 'all' in args.catalog else args.catalog)
        if not config['company_boards']: parser.error('没有匹配的内置公司 ID')
        config['sources'] = ['website']
    if args.career_url:
        config['company_boards'] = config.get('company_boards',[]) + [dict(type='website', url=url) for url in args.career_url]
        config['sources'] = ['website']
    profile_root = args.profile_root or (args.data / 'browser-search' if args.data else None)
    result = discover(config, browser_profile_root=profile_root, browser_headless=args.headless)
    serialized = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized)
    print(json.dumps(dict(jobs=len(result['jobs']), queries=result['queries'], sources=result['sources']),ensure_ascii=False,indent=2))


if __name__ == '__main__': main()
