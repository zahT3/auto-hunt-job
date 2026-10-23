# 公司官网发现与申请入口

这是有限来源的只读扫描。内置目录不代表每家公司都有当前适合你的岗位，也不代表国内公司所有职位都在中国大陆。

工作台 → 求职目标 → 高级搜索设置，可分别加入「国内 AI / Agent 官网」「Web3 官网」。保存后运行一轮。保持真实提交额度为 0，可独立验收发现与材料准备。

## 接入与实际边界

| 公司 | 公开来源 | 读取方式与限制 |
| --- | --- | --- |
| DeepSeek | https://talent.deepseek.com/ | 官网引用脚本中的 JSON 数据；保留原始数据快照时间，申请地址来自该数据；不执行脚本 |
| Dify | https://join.dify.ai/roles | 页面明确引用的公开岗位 JSON；只有公开招聘邮箱，单独展示，不生成假的申请表单 |
| Kimi / 月之暗面 | https://careers.kimi.com/ | 官网按钮指向 Moka；需要可选公开页面渲染；无完整正文的职位不入库 |
| 阶跃星辰 | https://www.stepfun.com/about | 官网脚本明确引用社招 Moka；需要可选公开页面渲染，不切换到校招 |
| Cobo | https://www.cobo.com/zh/careers | 官网明确引用 Moka 租户；公开岗位接口，只允许只读搜索 POST |
| OKX | https://www.okx.com/zh-hant/join-us/openings | 官网脚本明确引用 Greenhouse；列表与详情回源读取；地点可能为香港、海外 |
| HashKey | https://group.hashkey.com/en/category/roles/ | 官网角色链接 → 具体岗位正文；看到表单才标记表单可见，业务岗位也可能命中 Web3 |
| MiniMax | https://www.minimaxi.com/careers | 已定位官网，但引用的社招链接曾返回 404；未完成正文适配，不计为已接通 |
| imToken | https://careers.token.im/ | 官网列表内嵌脚本出现空的 title/department/area/link 字段，未获得有效岗位，不计为已接通 |

实测日期与轮次数字见 [v3 验收](v3-acceptance.md)。内置目录可维护于 `hunt/catalog.py`；不要根据公司名称猜招聘租户，不要将检索摘要写成岗位正文。每轮分别报告读取、保留、失败、截断、入口检查与公开渲染页数。

## 申请入口不再等于一条未检查的链接

- `form_seen`：页面出现与职位名称一致的标题，以及含简历字段的申请表单。只证明页面可见，不证明资格、登录、上传或提交成功。
- `job_page_seen`：职位页面身份匹配，尚未看到表单。
- `email_only`：官网公开的招聘邮箱，界面只展示文本，不发送邮件。
- `not_found`：HTTP 404/410，或页面标题明确显示不存在。隐藏该申请链接，不直接认定职位已关闭。
- `identity_mismatch`：入口身份不能对应当前职位，不提供该链接作为可申请入口。
- `login_required`、`captcha`、`blocked`：本人登录、验证或访问受阻；不会自动处理验证。
- `needs_browser`、`check_failed`、`budget_exhausted`：尚未完成检查，不当作职位已关闭。

只会修复到招聘页**明确出现且唯一对应同职位名称**的页面，并且再次看到同职位申请表单。来源带稳定职位 ID 时，替代页也必须包含该 ID。修复保留原地址和原检查；不会从职位名称拼接 URL、用招聘首页替代具体职位、换到另一职位。接收地址改变会使旧材料批准失效。

已检查结果按具体地址保存 24 小时。刷新取得低确定性结果时，不覆盖同地址仍新鲜的已观察结果；下一轮仍可能重新读取。不宣称缓存消除了所有重复网络请求。

Moka 的 `#/job/<id>` 是职位地址的一部分，必须保留；普通追踪锚点仍移除。公开 HTTP 请求遇到自循环重定向会停止，可选公开渲染使用全新、无个人登录状态的浏览器。它只允许 GET/HEAD 和明确列出的 Moka 只读检索 POST；其余 POST、上传、投递均阻止。

公开渲染需安装浏览器组件：

```sh
.venv/bin/python -m pip install -r requirements-executor.txt
.venv/bin/python -m playwright install chromium
.venv/bin/python -m hunt.discovery --official-only --catalog deepseek --catalog dify --catalog kimi --catalog stepfun --catalog cobo --catalog okx --catalog hashkey --official-browser --keyword AI --keyword Agent --keyword Web3 --max-jobs 14 --max-pages 3 --requests 60 --output private/official-results.json
```

常规 HTTP 发现与入口检查分别有预算。默认入口 HTTP 检查最多 12 次，每轮最多可配置 50 次；公开渲染每来源最多 `max_pages + 3` 页，正文最多读取 `max_pages` 个动态职位。达到限制后保留已取得的结果并显示部分完成。停止活动后不再发起新页面读取。这里没有全网无限扫描，也没有外部模型读取候选资料。
