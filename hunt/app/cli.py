"""One local CLI for the web workbench and its preparation workflow."""
import argparse
import base64
import getpass
import importlib
import json
import os
from pathlib import Path
import sqlite3
import sys

from ..ai import llm
from ..search.sources.catalog import CATALOG, boards
from .store import Store
from ..base import Error
from ..profile.profile import synthetic_profile

DEFAULT_DATA = Path(__file__).resolve().parents[2] / 'private' / 'app'
FORWARD = {
    'web': ('run', '启动本地网页工作台；其余参数同 run.py'),
    'scan': ('hunt.app.scan', '只读搜索岗位；其余参数同 hunt.app.scan'),
    'verify': ('hunt.app.verify', '本人登录后的 Moka 入口核验；不填写、不投递'),
    'prepare': ('run', '发现岗位并准备一轮本地材料；其余参数同 run.py --once'),
}


KIND_LABELS = dict(resume_redacted='脱敏简历', resume_full='完整简历', job_text='岗位原文')


def choose_kinds():
    """Arrow-key menu on a real terminal; typed numbers when output is not a terminal or curses cannot start."""
    from . import menu
    items = ['%s（%s）' % (label, kind) for kind, label in KIND_LABELS.items()]
    if sys.stdout.isatty():
        try:
            picked = menu.pick('选择要同意发送给模型服务的内容', items)
        except menu.Unavailable:
            pass  # e.g. TERM unset or unknown: ask for numbers below
        else:
            if picked is None: raise Error('已取消，未做任何更改')
            return [list(KIND_LABELS)[n] for n in picked]
    for n, item in enumerate(items, 1): print('%d. %s' % (n, item))
    typed = input('选择要同意发送的内容，填编号，可用逗号分隔：').replace('，', ',').split(',')
    if not all(x.strip() in ('1', '2', '3') for x in typed): raise Error('编号须是 1、2、3，未做任何更改')
    return [list(KIND_LABELS)[int(x) - 1] for x in typed]


def ai_consent(store, args):
    """Show where content would go, then write consent bound to exactly that host and model."""
    settings, tty = llm.load_settings(store.root), sys.stdin.isatty()
    kinds = args.kind
    if not kinds:
        if not tty: raise Error('请用 --kind 指定内容类别：' + '、'.join('%s（%s）' % kv for kv in KIND_LABELS.items()))
        kinds = choose_kinds()
    host = llm.host(settings)
    print('将发往：%s（模型 %s）' % (host, settings['model']))
    print('内容：' + '、'.join(KIND_LABELS[k] for k in llm.KINDS if k in kinds))
    if 'resume_full' in kinds: print('注意：「完整简历」不脱敏，姓名和联系方式会原样发送。')
    if not llm.load_key(store.root, host): print('提示：还没有保存这个主机的 API key；同意会记下，但在保存 key 之前不会发送任何内容。')
    if not args.yes:
        if not tty: raise Error('非交互环境请加 --yes 确认；未做任何更改')
        if input('确认同意吗？输入 yes 继续：').strip().lower() not in ('yes', 'y'): raise Error('未同意，未做任何更改')
    # Passing what was shown makes the store refuse if settings changed in between.
    store.grant_ai_consent(dict(kinds=kinds, host=host, model=settings['model']))
    print('已同意。可随时用 python -m hunt ai revoke 撤销。')


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
    benchmark = commands.add_parser('benchmark', help='对照人工标准答案计算岗位召回率')
    benchmark.add_argument('--truth', type=Path, required=True, help='人工核对的标准答案 JSON')
    benchmark.add_argument('--data', type=Path, default=DEFAULT_DATA, help='与网页相同的本地数据目录')
    benchmark.add_argument('--direction', help='仅比较此方向 ID 的岗位')
    benchmark.add_argument('--since', help='仅比较此时间及之后采集的岗位，须为带时区的 ISO 8601 时间')
    benchmark.add_argument('--output', type=Path, help='报告路径，默认写到标准答案同目录')
    benchmark.add_argument('--json', action='store_true', help='输出结构化 JSON')
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
    ai = commands.add_parser('ai', help='模型服务：保存 API key、查看设置与同意（不显示 key）')
    ai.set_defaults(json=False)
    ai_commands = ai.add_subparsers(dest='ai_command', required=True)
    for name, text in (('key', '保存 API key；终端里隐藏输入，非终端时从标准输入读一行'), ('show', '显示模型设置、key 末 4 位与同意记录'),
                       ('consent', '同意向当前模型服务发送所选内容；先显示主机和模型，确认后写入'), ('revoke', '撤销对模型服务的全部同意')):
        command = ai_commands.add_parser(name, help=text)
        command.add_argument('--data', type=Path, default=DEFAULT_DATA, help='与网页相同的本地数据目录')
        if name == 'consent':
            command.add_argument('--kind', action='append', choices=llm.KINDS, metavar='KIND',
                                 help='内容类别，可重复：' + '、'.join('%s=%s' % kv for kv in KIND_LABELS.items()))
            command.add_argument('--yes', action='store_true', help='不再询问，直接同意（用于脚本）')
    for command in (status, resume, confirm, config):
        command.add_argument('--data', type=Path, default=DEFAULT_DATA, help='与网页相同的本地数据目录')
        command.add_argument('--json', action='store_true', help='输出结构化 JSON')
    # Agent mode (docs/agent-mode.md): an external agent reads, decides and writes back; every command prints JSON.
    agent = [commands.add_parser('profile', help='agent 模式：脱敏后的确认事实与画像（不含联系方式）')]
    for name, help_text, children in (
            ('directions', 'agent 模式：方向参考表与写入方向', (('list', '列出全行业方向参考表'), ('set', '从 JSON 文件写入方向（记为 agent）'))),
            ('jobs', 'agent 模式：导出岗位', (('export', '导出岗位（id、标题、公司、正文前 4000 字）'),)),
            ('classify', 'agent 模式：写回归类', (('import', '从 JSON 文件写回 [{job_id, direction_id|null, reason}]（记为 agent）'),))):
        group = commands.add_parser(name, help=help_text).add_subparsers(dest='sub', required=True)
        for child, child_help in children:
            agent.append(group.add_parser(child, help=child_help))
            if child in ('set', 'import'): agent[-1].add_argument('file', type=Path, metavar='FILE')
            if child == 'export':
                agent[-1].add_argument('--unclassified', action='store_true', help='只导出规则不明确或尚未归类的岗位')
                agent[-1].add_argument('--limit', type=int, default=100, help='最多导出条数，1–1000，默认 100')
    agent.append(commands.add_parser('summary', help='agent 模式：各方向概况'))
    agent[-1].add_argument('--direction', metavar='ID', help='只看这个方向')
    for command in agent:
        command.add_argument('--data', type=Path, default=DEFAULT_DATA, help='与网页相同的本地数据目录')
        command.add_argument('--json', action='store_true', help='保留参数；本组命令总是输出 JSON')
        command.set_defaults(json=True)
    return result


def read_json(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except ValueError:
        raise Error('文件不是有效的 JSON：' + path.name) from None


def agent_profile(store):
    """Confirmed facts and the local profile with contact details and the name redacted; unconfirmed facts never leave."""
    from ..profile import directions, redact
    from ..ai import orient
    from ..profile.profile import build_profile
    candidate = store.state()['candidate']
    names = orient.candidate_names(candidate)
    profile = build_profile(candidate, confirmed_only=True)
    shown = dict(skills=[dict(name=s['name'], fact_ids=s['fact_ids']) for s in profile['skills']],
                 experience=[dict(text=redact.redact(r['text'], names), fact_ids=r['fact_ids']) for r in profile['experience']],
                 education=[dict(text=redact.redact(r['text'], names), fact_ids=r['fact_ids']) for r in profile['education']],
                 years_experience=profile['years_experience'], unknowns=profile['unknowns'],
                 suggested_directions=directions.suggest_from_profile(profile))
    return dict(schema_version=1, facts=redact.redact_facts(orient.confirmed_facts(candidate), names), profile=shown,
                directions=(store.orientation() or {}).get('directions') or [], notice='已去掉姓名与联系方式；只含已确认事实')


def chosen(store):
    return (store.orientation() or {}).get('directions') or []


def agent_command(store, args):
    from ..ai import classify, orient
    from ..profile import directions
    if args.command == 'profile':
        return agent_profile(store)
    if args.command == 'directions' and args.sub == 'set':
        payload = read_json(args.file)
        payload = dict(directions=payload) if isinstance(payload, list) else payload
        if not isinstance(payload, dict): raise Error('方向文件须是对象或数组')
        return dict(schema_version=1, **store.directions_set(dict(payload, source='agent')))
    if args.command == 'jobs':
        if not 1 <= args.limit <= 1000: raise Error('--limit 必须是 1 至 1000')
        ids = [d['id'] for d in chosen(store)]
        jobs = [j for j in store.state()['jobs']
                if not args.unclassified or classify.stale(j, ids) or (j.get('direction') or {}).get('unclear')]
        return dict(schema_version=1, directions=[dict(id=d['id'], name=d['name']) for d in chosen(store)],
                    jobs=[dict(id=j['id'], title=j['title'], company=j.get('company'), jd=str(j.get('jd') or '')[:4000],
                               direction=j.get('direction')) for j in jobs[:args.limit]])
    if args.command == 'classify':
        return dict(schema_version=1, imported=store.classify_many(read_json(args.file), 'agent'))
    dirs = chosen(store)
    if args.direction is not None and args.direction not in [d['id'] for d in dirs]: raise Error('--direction 须是当前所选方向之一')
    state = store.state()
    facts = orient.confirmed_facts(state['candidate'])
    _, other = classify.report(dirs, state['jobs'])
    return dict(schema_version=1, other_count=other,
                directions=[dict(id=d['id'], name=d['name'], **classify.summarize(d['id'], state['jobs'], facts))
                            for d in dirs if args.direction in (None, d['id'])])


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
            from ..search.sources import companies
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
        if args.command == 'benchmark':
            from ..search import benchmark
            result = benchmark.run(args.truth, args.data, lambda data: Store(data).state()['jobs'], direction=args.direction, since=args.since, output=args.output)
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                benchmark.print_summary(result)
            return 0
        if args.command == 'ai':
            store = Store(args.data)
            if args.ai_command == 'key':
                key = getpass.getpass('API key（输入不显示）：') if sys.stdin.isatty() else sys.stdin.readline()
                llm.save_key(store.root, key.strip(), llm.host(llm.load_settings(store.root)))
                print('已保存 API key，末 4 位：' + llm.key_hint(store.root))
            elif args.ai_command == 'consent':
                ai_consent(store, args)
            elif args.ai_command == 'revoke':
                store.revoke_ai_consent()
                print('已撤销对模型服务的全部同意；之后不会再发送任何内容，直到重新同意。')
            else:
                ai = store.ai_settings()
                ai['status'] = '已配置，可向所同意的内容发送' if ai['active'] else '未使用 AI（需要 key 与当前服务、模型下的同意）'
                print(json.dumps(dict(schema_version=1, data_dir=str(store.root), **ai), ensure_ascii=False, indent=2))
            return 0
        if args.command == 'directions' and args.sub == 'list':
            from ..profile import directions
            rows = [dict(id=r['id'], name=r['name'], family=r['family'], titles=r['titles']) for r in directions.load()]
            print(json.dumps(dict(schema_version=1, directions=rows), ensure_ascii=False, indent=2))
            return 0
        store = Store(args.data)
        if args.command in ('profile', 'directions', 'jobs', 'classify', 'summary'):
            print(json.dumps(agent_command(store, args), ensure_ascii=False, indent=2))
            return 0
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
