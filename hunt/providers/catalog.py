"""Curated employer entry points; listing is not a promise of current vacancies."""
CATALOG = [
    dict(id='deepseek', company='DeepSeek', category='AI / Agent', url='https://talent.deepseek.com/', adapter='embedded_json', region='北京 / 杭州，以岗位为准'),
    dict(id='dify', company='Dify', category='AI 应用 / Agent', url='https://join.dify.ai/roles', official_url='https://dify.ai/zh/about-us', adapter='public_json', region='中国 / 海外，以岗位为准'),
    dict(id='kimi', company='Kimi / 月之暗面', category='AI / Agent', url='https://careers.kimi.com/', adapter='moka_browser', region='以岗位地点为准'),
    dict(id='stepfun', company='阶跃星辰', category='AI / Agent', url='https://www.stepfun.com/about', adapter='moka_browser', region='以岗位地点为准'),
    dict(id='cobo', company='Cobo', category='Web3', url='https://www.cobo.com/zh/careers', adapter='moka_public', region='亚洲 / 海外，以岗位为准'),
    dict(id='okx', company='OKX', category='Web3 / Agent', url='https://www.okx.com/zh-hant/join-us/openings', adapter='greenhouse', region='香港 / 海外，以岗位为准'),
    dict(id='imtoken', company='imToken', category='Web3', url='https://careers.token.im/', adapter='imtoken_public', region='杭州 / 新加坡 / 台北 / 远程，以岗位为准', note='可读取官方岗位页；官网列表异常，在招状态待确认，邮箱申请'),
    dict(id='hashkey', company='HashKey', category='Web3', url='https://group.hashkey.com/en/category/roles/', adapter='html', region='香港 / 海外，以岗位为准'),
    dict(id='minimax', company='MiniMax', category='AI / Agent', url='https://www.minimaxi.com/careers', adapter='feishu_browser', region='以岗位地点为准', note='需公开页面渲染；社招正文可读，后续申请表需核验'),
]


def boards(ids=None):
    return [dict(type='website', url=r['url'], company=r['company']) for r in CATALOG if ids is None or r['id'] in ids]


def lookup(url):
    return next((r for r in CATALOG if r['url'].rstrip('/') == url.rstrip('/')), None)
