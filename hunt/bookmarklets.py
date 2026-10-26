"""Bookmarklet sources, their javascript: URLs, and the same-origin install page."""
import html
import re
from pathlib import Path
from urllib.parse import quote

DIR = Path(__file__).resolve().parent.parent / 'static' / 'bookmarklets'
# (file stem, button label, when to use). The universal one comes first: it works on most sites.
ITEMS = (('universal', '通用岗位页', '多数官网招聘页、内推页和其他没有专用书签的站点；只有它能用于白名单之外的网站。'),
         ('boss-zhipin', 'BOSS直聘', 'zhipin.com 岗位详情页，需要自己先登录。'),
         ('liepin', '猎聘', 'liepin.com 岗位详情页，需要自己先登录。'),
         ('lagou', '拉勾', 'lagou.com 岗位详情页，需要自己先登录。'),
         ('mokahr', 'Moka', 'mokahr.com 上的岗位页；页面把岗位放在跨域 iframe 里时，先在新标签页单独打开它。'))
URL_FIELD, TOKEN_FIELD = '__INBOX_URL__', '__INBOX_TOKEN__'


def source(name):
    if name not in {n for n, _, _ in ITEMS}:
        raise KeyError(name)
    return (DIR / (name + '.js')).read_text(encoding='utf-8')


def prelude():
    return (DIR / '_deliver.js').read_text(encoding='utf-8')


def assemble(name):
    """The script with the shared delivery code spliced in at its "// @deliver" line."""
    text = source(name)
    if len(re.findall(r'^ *// @deliver$', text, re.M)) != 1:
        raise ValueError(name + ' needs exactly one "// @deliver" line')
    return re.sub(r'^ *// @deliver$', lambda _: prelude(), text, flags=re.M)


def minify(text):
    """Drop whole-line comments and indentation; lines stay separate so automatic semicolon insertion behaves as written."""
    lines = (line.strip() for line in text.splitlines())
    return '\n'.join(line for line in lines if line and not line.startswith('//'))


def build(name):
    """The javascript: URL with the two placeholders still in it; render() fills them."""
    return 'javascript:' + quote(minify(assemble(name)), safe="!()*'~")


def render(name, inbox_url, token):
    # Both values land inside a JS string literal, so anything outside this shape is refused rather than escaped.
    if not re.fullmatch(r'http://127\.0\.0\.1:\d{1,5}/api/inbox', inbox_url) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', token):
        raise ValueError('收件地址或令牌的格式不能写入书签')
    return build(name).replace(URL_FIELD, quote(inbox_url, safe='')).replace(TOKEN_FIELD, quote(token, safe=''))


def page(port, inbox_token, csrf):
    inbox_url = 'http://127.0.0.1:%d/api/inbox' % port
    cards = []
    for name, label, hint in ITEMS:
        cards.append('<li class="bm-card"><a class="bm-link" draggable="true" href="%s">%s</a><p>%s</p></li>'
                     % (html.escape(render(name, inbox_url, inbox_token), quote=True), html.escape(label), html.escape(hint)))
    return PAGE % dict(cards='\n'.join(cards), port=port, csrf=html.escape(csrf, quote=True))


PAGE = '''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light"><title>安装书签 · auto-hunt-job</title>
<link rel="stylesheet" href="/style.css">
</head>
<body>
<header class="app-header">
  <a class="brand" href="/" aria-label="回到求职工作台"><span>auto-hunt-job</span><span class="local-tag">本地</span></a>
  <div class="header-actions"><a href="/">回到工作台</a></div>
</header>
<main class="install-page">
<h1>岗位书签</h1>
<p class="lead">在 BOSS、猎聘、拉勾这类要登录的网站上，你自己打开岗位页，点一下书签，页面上的文字就发到本机的工作台。书签不会替你登录、翻页或投递。</p>
<h2>安装</h2>
<ol class="steps">
<li>显示浏览器书签栏（Chrome、Edge、Safari 都是 Command+Shift+B）。</li>
<li>把下面的按钮<strong>拖</strong>到书签栏。在本页点按钮没有用。</li>
<li>打开岗位详情页，需要登录的站点先自己登录，再点书签栏里的书签。</li>
<li>页面右下角出现 3 秒提示：绿色是已收下，红色是没收下，提示里写了原因。成功后回工作台的机会列表查看。</li>
</ol>
<ul class="bm-list">
%(cards)s
</ul>
<h2>发送什么，发到哪里</h2>
<p>点击时只发送当前页的网址、标题和页面文字（过长会截短），发到这台电脑的 127.0.0.1:%(port)d，不经过其他服务器。不读 Cookie，不保存密码。收到的文字只当资料保存，不会被当作指令执行。</p>
<p>端口或令牌变了，已装的书签就不能用，需要回到本页重新拖一次。个别网站的安全策略禁止页面向外发请求，浏览器也可能询问是否允许访问本地网络；这两种情况下书签会显示红色提示。</p>
<h2>重置令牌</h2>
<p>令牌写在书签里，书签靠它才能往工作台添加岗位。你点书签的那个网站，页面里的脚本能看到令牌。拿到令牌的人只能往工作台里添加岗位资料，不能读取或操作工作台里已有的内容。拿不准有没有泄露，就重置。<strong>重置后，已经安装在浏览器里的书签立即全部失效</strong>，要回到本页重新拖一次。</p>
<form method="post" action="/bookmarklets/reset">
<input type="hidden" name="csrf" value="%(csrf)s">
<button class="secondary" type="submit">重置令牌</button>
</form>
</main>
</body>
</html>
'''
