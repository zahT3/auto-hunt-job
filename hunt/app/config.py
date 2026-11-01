"""The saved search and activity config: defaults and the checks a new config must pass."""
import re

from ..base import Error
from ..net.network import validate_url

DEFAULT_CONFIG = dict(keyword='', keywords=[], cities=[], salary_min=None, max_jobs=20,
                      interval_minutes=60, submission_limit=0, targets_confirmed=False,
                      sources=['anker', 'greenhouse', 'lever', 'ashby'],
                      company_boards=[dict(type='greenhouse', slug='anthropic', company='Anthropic'),
                                      dict(type='lever', slug='binance', company='Binance'),
                                      dict(type='ashby', slug='cursor', company='Cursor')], max_pages=2,
                      source_modes={'boss': 'public', 'liepin': 'public'}, search_provider=None,
                      official_only=False, browser_channel=None, check_entries=True, official_browser=False, liepin_cards=False)


def validate_config(payload):
    """The config to save from a submitted one, filled from the defaults; Error names the first bad field."""
    cfg=dict(DEFAULT_CONFIG,**payload)
    if not isinstance(cfg['cities'],list) or len(cfg['cities'])>20 or any(not isinstance(x,str) or len(x)>100 for x in cfg['cities']) or not 1<=int(cfg['max_jobs'])<=50 or not 1<=float(cfg['interval_minutes'])<=10080 or not 0<=int(cfg['submission_limit'])<=5:
        raise Error('每轮准备 1-50 岗、间隔至少 1 分钟、提交额度 0-5')
    cfg['max_jobs']=int(cfg['max_jobs']);cfg['submission_limit']=int(cfg['submission_limit'])
    if type(cfg['targets_confirmed']) is not bool: raise Error('需要明确确认目标')
    if type(cfg.get('official_only', False)) is not bool: raise Error('官网模式必须为明确的开关')
    if any(type(cfg.get(k, False)) is not bool for k in ('check_entries', 'official_browser')): raise Error('入口核验与公开渲染必须为开关')
    if type(cfg.get('liepin_cards', False)) is not bool: raise Error('猎聘只读卡片必须为开关')
    if type(cfg.get('sweep', False)) is not bool: raise Error('大范围搜索必须为开关')
    for key, low, high in (('sweep_max_companies', 1, 1000), ('sweep_max_jobs', 1, 5000), ('sweep_requests', 1, 10000),
                           ('sweep_deadline_seconds', 30, 3600), ('sweep_prepare', 0, 200), ('sweep_max_pages', 1, 50)):
        if key in cfg and (type(cfg[key]) is not int or not low <= cfg[key] <= high):
            raise Error('大范围搜索参数 %s 必须是 %d 至 %d 的整数' % (key, low, high))
    if cfg.get('browser_channel') not in (None, 'chrome'): raise Error('仅支持默认 Chromium 或 Google Chrome')
    if not isinstance(cfg.get('keyword'),str) or len(cfg['keyword'])>100:
        raise Error('岗位关键词最长 100 字符')
    keywords=cfg.get('keywords',[])
    if not isinstance(keywords,list) or len(keywords)>8 or any(not isinstance(q,str) or not q.strip() or len(q)>100 for q in keywords):
        raise Error('设置 0-8 个岗位搜索词，每个不超过 100 字符')
    sources=cfg.get('sources',[])
    if not isinstance(sources,list) or not sources or any(not isinstance(s,str) for s in sources) or len(sources)!=len(set(sources)) or set(sources)-{'boss','liepin','anker','greenhouse','lever','ashby','website'}:
        raise Error('请选择支持的搜索渠道')
    boards=cfg.get('company_boards',[])
    if not isinstance(boards,list) or len(boards)>20:
        raise Error('公司官网配置最多 20 个')
    sources=cfg.get('discovery_sources')
    if sources is not None:
        cap=cfg.get('sweep_max_companies',300) if cfg.get('sweep') else 20
        if not isinstance(sources,list) or len(sources)>cap or any(not isinstance(s,dict) for s in sources):
            raise Error('搜索来源 discovery_sources 必须是对象数组，最多 %d 个' % cap)
    for board in boards:
        if isinstance(board,dict) and board.get('type')=='website':
            validate_url(board.get('url'))
            continue
        if not isinstance(board,dict) or board.get('type') not in ('greenhouse','lever','ashby') or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',str(board.get('slug',''))) or len(str(board.get('company','')))>200:
            raise Error('官网需填写平台、公司标识和名称')
    cfg['max_pages']=int(cfg.get('max_pages',2))
    if not 1<=cfg['max_pages']<=5:
        raise Error('每渠道每关键词最多 1-5 页')
    cfg['keywords']=list(dict.fromkeys(q.strip() for q in keywords))
    modes=cfg.get('source_modes',{})
    if not isinstance(modes,dict) or set(modes)-{'boss','liepin'} or any(v not in ('public','browser') for v in modes.values()):
        raise Error('采集模式仅支持公开读取或独立浏览器')
    provider=cfg.get('search_provider')
    if provider:
        if not isinstance(provider,dict) or provider.get('provider')!='searxng':
            raise Error('通用搜索目前支持 SearXNG JSON 接口')
        validate_url(provider.get('url'))
    # Local profile roots are fixed by the runner, never accepted from requests.
    cfg.pop('browser_profile_root',None)
    return cfg
