# 公司官网发现与申请入口

这是有限来源的只读扫描。内置目录不代表每家公司都有当前适合你的岗位，也不代表国内公司所有职位都在中国大陆。

工作台 → 求职目标 → 高级搜索设置，可分别加入「国内 AI / Agent 官网」「Web3 官网」。保存后运行一轮。保持真实提交额度为 0，可独立验收发现与材料准备。

## 接入与实际边界

| 公司 | 公开来源 | 读取方式与限制 | 依据页面 | 许可或条款 | 下架办法 |
| --- | --- | --- | --- | --- | --- |
| DeepSeek | https://talent.deepseek.com/ | 官网引用脚本中的 JSON 数据；保留原始数据快照时间，申请地址来自该数据；不执行脚本 | https://talent.deepseek.com/ | 未声明 | 删除 `hunt/search/sources/catalog.py` 中 `id='deepseek'` 一行，并在 `hunt/data/companies.cn.json` 把同 ID 种子的 `status` 设为 `dead` |
| Dify | https://join.dify.ai/roles | 页面明确引用的公开岗位 JSON；只有公开招聘邮箱，单独展示，不生成假的申请表单 | https://join.dify.ai/roles | 未声明 | 删除 `hunt/search/sources/catalog.py` 中 `id='dify'` 一行，并在 `hunt/data/companies.cn.json` 把同 ID 种子的 `status` 设为 `dead` |
| Kimi / 月之暗面 | https://careers.kimi.com/ | 官网按钮指向 Moka；需要可选公开页面渲染；无完整正文的职位不入库 | https://careers.kimi.com/ | 未声明 | 删除 `hunt/search/sources/catalog.py` 中 `id='kimi'` 一行，并在 `hunt/data/companies.cn.json` 把同 ID 种子的 `status` 设为 `dead` |
| 阶跃星辰 | https://www.stepfun.com/about | 官网脚本明确引用社招 Moka；需要可选公开页面渲染，不切换到校招 | https://www.stepfun.com/about | 未声明 | 删除 `hunt/search/sources/catalog.py` 中 `id='stepfun'` 一行，并在 `hunt/data/companies.cn.json` 把同 ID 种子的 `status` 设为 `dead` |
| Cobo | https://www.cobo.com/zh/careers | 官网明确引用 Moka 租户；公开岗位接口，只允许只读搜索 POST | https://www.cobo.com/zh/careers | 未声明 | 删除 `hunt/search/sources/catalog.py` 中 `id='cobo'` 一行，并在 `hunt/data/companies.cn.json` 把同 ID 种子的 `status` 设为 `dead` |
| OKX | https://www.okx.com/zh-hant/join-us/openings | 官网脚本明确引用 Greenhouse；列表与详情回源读取；地点可能为香港、海外 | https://www.okx.com/zh-hant/join-us/openings | 未声明 | 删除 `hunt/search/sources/catalog.py` 中 `id='okx'` 一行，并在 `hunt/data/companies.cn.json` 把同 ID 种子的 `status` 设为 `dead` |
| HashKey | https://group.hashkey.com/en/category/roles/ | 官网角色链接 → 具体岗位正文；看到表单才标记表单可见，业务岗位也可能命中 Web3 | https://group.hashkey.com/en/category/roles/ | 未声明 | 删除 `hunt/search/sources/catalog.py` 中 `id='hashkey'` 一行，并在 `hunt/data/companies.cn.json` 把同 ID 种子的 `status` 设为 `dead` |
| MiniMax | https://www.minimaxi.com/careers | 匿名浏览器读取官网社招 Feishu 页；普通 HTTP 404 不代表失效，需开启公开页面渲染 | https://www.minimaxi.com/careers | 未声明 | 删除 `hunt/search/sources/catalog.py` 中 `id='minimax'` 一行，并在 `hunt/data/companies.cn.json` 把同 ID 种子的 `status` 设为 `dead` |
| imToken | https://careers.token.im/ | 官网列表为空；通过 robots.txt 明示的官方 sitemap 读取岗位页和邮箱，始终保留在招待确认 | https://careers.token.im/ | 未声明 | 删除 `hunt/search/sources/catalog.py` 中 `id='imtoken'` 一行，并在 `hunt/data/companies.cn.json` 把同 ID 种子的 `status` 设为 `dead` |

## 其他内置来源（按接口类型合并）

来源以 `hunt/search/sources/` 和 `hunt/data/companies.cn.json` 为准。三列的含义：依据页面是该类来源公开岗位的官方入口；许可或条款写"未声明"表示没有在该入口找到可用于再分发的授权声明，不等于可以转载；下架办法是对方要求停用时的做法。

| 来源类型 | 接口与读取范围 | 依据页面 | 许可或条款 | 下架办法 |
| --- | --- | --- | --- | --- |
| 单家大厂公开接口：腾讯、阿里、美团、京东、网易、小红书、滴滴 | 各自招聘站的公开岗位列表接口，只读、不带 cookie（`tencent.py`、`alibaba.py`、`meituan.py`、`jd.py`、`netease.py`、`xiaohongshu.py`、`didi.py`） | careers.tencent.com、talent.alibaba.com、zhaopin.meituan.com、zhaopin.jd.com、hr.163.com、job.xiaohongshu.com、talent.didiglobal.com | 未声明 | 在 `companies.cn.json` 把对应 `provider` 的种子 `status` 设为 `dead`；用户自己在 `discovery_sources` 里加的，直接删该条 |
| 飞书招聘租户（含字节跳动） | `jobs.bytedance.com` 和 `*.jobs.feishu.cn` 租户的公开 JSON（`feishu.py`） | 各租户招聘首页，如 jobs.bytedance.com | 未声明 | 同上，按种子逐个设 `status: dead` |
| Moka 租户 | `app.mokahr.com`、`hire-r1.mokahr.com` 租户的公开岗位接口（`mokahr.py`）；加密响应需可选依赖 | 各租户 `app.mokahr.com/social-recruitment/...` 或 `/apply/...` 页面 | 未声明 | 同上；平台方要求停用时，把所有 `provider: mokahr` 种子设为 `dead` |
| 北森租户 | `*.zhiye.com` 的公开岗位列表接口（`beisen.py`） | 各租户 `/social` 页面 | 未声明 | 同上 |
| 大易租户 | `hotjob.cn`、`wintalent.cn` 下 `/wt/<租户>/` 的公开岗位列表（`dayee.py`） | 各租户 `/web/index/social` 页面 | 未声明 | 同上 |
| 海外 ATS 公开看板 | Greenhouse、Lever、Ashby 的公开看板接口（`ats.py`）；公司官网链到它们时复用 | 各看板公开页面 | 未声明 | 在配置的 `sources` 里去掉 `greenhouse` / `lever` / `ashby`，或从 `discovery_sources` 删该看板 |
| 公司官网 | 官网自带的 JobPosting 数据和链出的看板（`website.py`、`careers.py`、`domestic.py`） | 种子里的 `careers_url` | 未声明 | 种子 `status: dead`，或去掉 `sources` 里的 `website` |
| Anker | 官方公开招聘源（`anker.py`） | 其官方招聘页 | 未声明 | 在配置的 `sources` 里去掉 `anker` |
| BOSS 直聘、猎聘 | 默认关闭；公开搜索页只读，需登录的页面走书签收件箱（`platforms.py`、`inbox.py`） | zhipin.com、liepin.com | 平台条款限制自动化采集，见 `SECURITY.md`；按未获授权对待 | 在配置的 `sources` 里去掉 `boss` / `liepin`；收件箱里已有记录用界面删除 |
| 自备 SearXNG | 用户自己的 SearXNG 端点，只有雇主页面提供 JD（`websearch.py`） | 用户自己配置的端点 | 取决于所搜页面，未声明 | 清空该端点配置 |

`status: dead` 的种子被 `companies.select` 跳过（`hunt/search/sources/companies.py` 的 `FLAGGED`）；已入库的历史岗位不会因此删除，需要时在岗位库里手动清除。上表"未声明"是本次只读代码和入口得出的结论，没有逐页核对每个站点的服务条款。

实测日期与轮次数字见 [v4 验收](v4-acceptance.md)。内置目录可维护于 `hunt/catalog.py`；不要根据公司名称猜招聘租户，不要将检索摘要写成岗位正文。每轮分别报告读取、保留、失败、截断、入口检查与公开渲染页数。

## 申请入口不再等于一条未检查的链接

- `form_seen`：页面出现与职位名称一致的标题，以及含简历字段的申请表单。只证明页面可见，不证明资格、登录、上传或提交成功。
- `job_page_seen`：职位页面身份匹配，尚未看到表单。
- `email_only`：官网公开的招聘邮箱，界面只展示文本，不发送邮件。
- `not_found`：HTTP 404/410，或页面标题明确显示不存在。隐藏该申请链接，不直接认定职位已关闭。
- `identity_mismatch`：入口身份不能对应当前职位，不提供该链接作为可申请入口。
- `login_required`、`captcha`、`blocked`：本人登录、验证或访问受阻；不会自动处理验证。
- `form_incomplete`：必要表单读取失败、未完成或页面报告加载失败。不会认定为完整表单。
- `needs_browser`、`check_failed`、`budget_exhausted`：尚未完成检查，不当作职位已关闭。

只会修复到招聘页**明确出现且唯一对应同职位名称**的页面，并且再次看到同职位申请表单。来源带稳定职位 ID 时，替代页也必须包含该 ID。修复保留原地址和原检查；不会从职位名称拼接 URL、用招聘首页替代具体职位、换到另一职位。接收地址改变会使旧材料批准失效。

已检查结果按具体地址保存 24 小时。刷新取得低确定性结果时，不覆盖同地址仍新鲜的已观察结果；下一轮仍可能重新读取。不宣称缓存消除了所有重复网络请求。

Moka 的 `#/job/<id>` 是职位地址的一部分，必须保留；普通追踪锚点仍移除。公开 HTTP 请求遇到自循环重定向会停止，可选公开渲染使用全新、无个人登录状态的浏览器。它只允许 GET/HEAD 和明确列出的 Moka / MiniMax 只读检索 POST；其余 POST、上传、投递均阻止。

公开渲染需安装浏览器组件：

```sh
.venv/bin/python -m pip install -r requirements-executor.txt
.venv/bin/python -m playwright install chromium
.venv/bin/python -m hunt.discovery --official-only --catalog deepseek --catalog dify --catalog kimi --catalog stepfun --catalog cobo --catalog okx --catalog hashkey --official-browser --keyword AI --keyword Agent --keyword Web3 --max-jobs 14 --max-pages 3 --requests 60 --output private/official-results.json
```

常规 HTTP 发现与入口检查分别有预算。默认入口 HTTP 检查最多 12 次，每轮最多可配置 50 次；公开渲染通常每来源最多 `max_pages + 3` 页；MiniMax 为最多 3 个关键词列表，加预算内的详情与入口检查，最多 13 页，正文最多读取 `max_pages` 个动态职位。达到限制后保留已取得的结果并显示部分完成。停止活动后不再发起新页面读取。这里没有全网无限扫描，也没有外部模型读取候选资料。

Moka 登录后的只读核验、独立会话存放与限制见 [使用说明](usage.md#Moka-登录后只读核验)。核验绑定同公司、站点、职位和标题；必要读取的网络失败、HTTP 错误和未完成请求都会阻止表单完整的结论。
