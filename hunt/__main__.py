"""One local CLI for the web workbench and its preparation workflow."""
import argparse
import base64
import importlib
import json
import os
from pathlib import Path
import sqlite3
import sys

from .catalog import CATALOG, boards
from .core import Error, Store, synthetic_profile

DEFAULT_DATA = Path(__file__).resolve().parent.parent / 'private' / 'app'
FORWARD = {
    'web': ('run', '启动本地网页工作台；其余参数同 run.py'),
    'scan': ('hunt.discovery', '只读搜索岗位；其余参数同 hunt.discovery'),
    'verify': ('hunt.moka_session', '本人登录后的 Moka 入口核验；不填写、不投递'),
    'prepare': ('run', '发现岗位并准备一轮本地材料；其余参数同 run.py --once'),
}


def parser():
    result = argparse.ArgumentParser(prog='python -m hunt', description='本地求职助手：找岗位、核对事实、准备材料。')
    commands = result.add_subparsers(dest='command', required=True)
    for name, (_, help_text) in FORWARD.items():
        commands.add_parser(name, help=help_text, add_help=False)
    catalog = commands.add_parser('catalog', help='列出支持的公司官网和标识')
    catalog.add_argument('--json', action='store_true')
    seeds = commands.add_parser('companies', help='列出大范围搜索将扫描的公司')
    seeds.add_argument('--terms', nargs='+', default=[], metavar='TERM', help='搜索词，用于给公司排序')
    seeds.add_argument('--limit', type=int, default=300, help='最多列出的公司数，默认 300')
    seeds.add_argument('--data', type=Path, default=None, help='提供时，把该数据目录里遇到过的公司排在种子之后')
    seeds.add_argument('--json', action='store_true')
    status = commands.add_parser('status', help='查看候选资料、岗位 ID 和申请尝试数')
    resume = commands.add_parser('resume', help='本地导入 PDF/DOCX，生成待核对事实')
    resume.add_argument('path', type=Path, metavar='PATH')
    resume.add_argument('--real', action='store_true', help='明确标记为真实资料；仍仅用于本地草稿')
    confirm = commands.add_parser('confirm', help='确认明确选中的简历事实，未选中项继续待确认')
    confirm.add_argument('--draft', required=True, metavar='ID', help='resume 返回的草稿 ID')
    confirm.add_argument('--fact', action='append', required=True, metavar='ID', help='事实 ID，可重复；没有全选默认值')
    config = commands.add_parser('configure', help='保存官网搜索范围；提交额度保持 0')
    config.add_argument('--catalog', action='append', choices=['all'] + [r['id'] for r in CATALOG], help='公司 ID，可重复；提供时替换公司范围')
    config.add_argument('--keyword', action='append', help='搜索词，可重复；提供时替换搜索词')
    config.add_argument('--official-browser', action='store_true', default=None, help='开启独立的公开页面渲染')
    for command in (status, resume, confirm, config):
        command.add_argument('--data', type=Path, default=DEFAULT_DATA, help='与网页相同的本地数据目录')
        command.add_argument('--json', action='store_true', help='输出结构化 JSON')
    return result


def summary(store):
    state = store.state()
    candidate = state['candidate']
    facts = candidate.get('facts', [])
    draft = state.get('candidate_draft')
    rows = []
    for job in state['jobs']:
        raw = job.get('raw') if isinstance(job.get('raw'), dict) else {}
        route = raw.get('application_route', {})
        rows.append(dict(id=job['id'], title=job['title'], company=job.get('company'),
                         status=job['status'], entry_status=route.get('entry_check', {}).get('status'),
                         availability=job.get('availability'), availability_note=raw.get('availability_note'),
                         listing_status=raw.get('source_listing_status')))
    return dict(schema_version=1, data_dir=str(store.root), synthetic=synthetic_profile(candidate),
                facts=dict(total=len(facts), confirmed=sum(f.get('status') == 'confirmed' for f in facts)),
                jobs_count=len(rows), attempts_count=sum(len(j.get('attempts', [])) for j in state['jobs']), jobs=rows,
                draft=dict(id=draft['id'], status=draft['status'], facts_count=len(draft['candidate']['facts'])) if draft else None,
                submission_limit=state['config']['submission_limit'], targets_confirmed=state['config']['targets_confirmed'])


def print_summary(result):
    print(('合成候选人' if result['synthetic'] else '真实候选资料') +
          ' · 事实 {confirmed}/{total} · 岗位 {jobs} · 申请尝试 {attempts}'.format(
              **result['facts'], jobs=result['jobs_count'], attempts=result['attempts_count']))
    if result['draft']:
        print('待核对草稿：' + result['draft']['id'])
    for job in result['jobs']:
        state = job['entry_status'] or job['status']
        if job['listing_status'] == 'unavailable': state += ' · 在招待确认'
        print('{id}  {title} · {company} · {state}'.format(**job, state=state))


def configure(store, args):
    config = dict(store.state()['config'])
    if args.catalog is not None:
        config['company_boards'] = boards(None if 'all' in args.catalog else args.catalog)
    if not any(b.get('type') == 'website' for b in config['company_boards']):
        raise Error('请选择官网来源，例如 --catalog minimax --catalog imtoken')
    if args.keyword is not None:
        config['keywords'] = args.keyword
    if args.official_browser is not None:
        config['official_browser'] = args.official_browser
    config.update(sources=['website'], official_only=True, submission_limit=0)
    # Legacy explicit source rows override sources in discovery; remove that
    # override so this command's selected official scope is actually honored.
    config.pop('discovery_sources', None)
    state = store.action(dict(action='config', config=config))
    return dict(schema_version=1, data_dir=str(store.root), config=state['config'])


def dispatch(command, arguments):
    module, _ = FORWARD[command]
    previous = sys.argv
    sys.argv = ['python -m hunt ' + command] + (['--once'] if command == 'prepare' else []) + list(arguments)
    try:
        result = importlib.import_module(module).main()
        return result if isinstance(result, int) else 0
    finally:
        sys.argv = previous


def main(argv=None):
    os.umask(0o077)
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] in FORWARD:
        return dispatch(arguments[0], arguments[1:])
    args = parser().parse_args(arguments)
    try:
        if args.command == 'catalog':
            result = dict(schema_version=1, companies=CATALOG)
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                for row in CATALOG:
                    print('{id:10} {company} · {category} · {adapter}'.format(**row))
            return 0
        if args.command == 'companies':
            from . import companies
            if not 1 <= args.limit <= 1000:
                raise Error('--limit 必须是 1 至 1000')
            extra = []
            if args.data:
                with Store(args.data).tx() as c:
                    extra = companies.encountered(c)
            result = dict(schema_version=1, companies=companies.select(args.terms, args.limit, extra))
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                for row in result['companies']:
                    print('{:8} {} · {}'.format(row['kind'], row['company'], row.get('url') or row['careers_url']))
            return 0
        store = Store(args.data)
        # Only the existing runner owns recovery and its OS lock. These local
        # commands must never reinterpret an active process as a crashed send.
        if args.command == 'status':
            result = summary(store)
        elif args.command == 'resume':
            if not args.path.is_file():
                raise Error('请选择一个 PDF 或 DOCX 简历文件')
            with args.path.open('rb') as source:
                content = source.read(10 * 1024 * 1024 + 1)
            if len(content) > 10 * 1024 * 1024:
                raise Error('简历文件最大 10 MiB')
            state = store.upload_resume(dict(filename=args.path.name,
                content_base64=base64.b64encode(content).decode('ascii'), synthetic=not args.real))
            draft = state['candidate_draft']
            result = dict(schema_version=1, draft_id=draft['id'], status=draft['status'],
                          synthetic=synthetic_profile(draft['candidate']), warnings=draft.get('warnings', []),
                          facts=[dict(id=f['id'], text=f['text'], status=f['status']) for f in draft['candidate']['facts']])
        elif args.command == 'confirm':
            store.confirm_resume(dict(draft_id=args.draft, confirmed_fact_ids=args.fact))
            result = dict(summary(store), confirmed_fact_ids=args.fact)
        elif args.command == 'configure':
            result = configure(store, args)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.command in ('status', 'confirm'):
            print_summary(result)
        elif args.command == 'resume':
            print('待核对草稿：' + result['draft_id'] + ' · ' + ('合成资料' if result['synthetic'] else '真实资料'))
            print('解析状态：' + result['status'])
            for warning in result['warnings']:
                print('提示：' + warning)
            for fact in result['facts']:
                print(fact['id'] + '  ' + fact['text'])
        else:
            cfg = result['config']
            print('已保存官网范围：' + '、'.join(b.get('company') or b.get('url', '') for b in cfg['company_boards'] if b.get('type') == 'website'))
            print('搜索词：' + '、'.join(cfg['keywords']) + ' · 提交额度 0')
        return 0
    except (Error, OSError, ValueError, sqlite3.Error) as error:
        if args.json:
            print(json.dumps(dict(schema_version=1, error=str(error)), ensure_ascii=False))
        else:
            print('错误：' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
