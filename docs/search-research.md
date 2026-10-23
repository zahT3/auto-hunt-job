# 多渠道搜索：实现与证据边界

日期：2026-10-22。这个项目的“全网”是一组持续扩展的公开来源与索引，不是一个平台可以保证完整的全集。实现独立运行，不依赖 Codex 搜索、CUA、账号或插件。

## 研究决定

1. 公司官网优先使用招聘系统公开读接口。Greenhouse 官方明确 GET 不需认证；Lever 有 published postings 和 skip/limit；Ashby 的 posting API 返回当前发布职位并可附薪资。接口正文比搜索摘要更适合作为匹配依据。我们分别实现了适配器，没有复制其他项目代码。
2. 中文招聘平台使用公开 HTML 与用户可选的独立浏览器。列表必须提取到真实岗位链接，再获取详情；网页需要 JS、登录、验证码或拒绝访问时，报告相应状态。没有代理轮换、stealth、验证码处理、Cookie 导出或个人 Chrome 接管。
3. 独立浏览器实验发现：猎聘网页的搜索是两个 POST 读接口驱动，全部禁止 POST 会制造“空列表”。因此仅放行 `api-c.liepin.com/api/com.liepin.searchfront4c.pc-search-job` 与 `...pc-search-job-cond-init`，其他 POST 仍被阻止。这是网页正常发起的读取；不调用投递、聊天、订阅或账号修改接口。
4. 索引扩展使用可选 SearXNG JSON 搜索端点。没有已配置端点时不能宣称全网搜索已经发生。搜索结果只作线索，必须再从目标页取得 JobPosting 正文；摘要不会伪装成 JD。
5. 借鉴 JobSpy 的统一岗位模型和失败记录，但没有把“安装 JobSpy”当成 BOSS/猎聘支持。其官方支持列表与当前变更说明并不提供这两个中文平台的即用适配。

## 实现范围

- 原始关键词只来自明确的搜索配置。简历、姓名、联系方式不会作为候选人全文自动送往搜索站。
- AI 应用开发、Agent 开发、RAG 工程师等中文方向在**本地官网过滤**中使用可检查的同义词展开，输出 `queries` 与 `expanded_terms` 分开记录。这是扩召回，不是胜任结论。
- Greenhouse 先拿 metadata，再读取匹配标题的少量详情；大公司完整 content feed 可能超过安全响应上限。Ashby 全板返回；Lever 分页读取。每轮请求总预算、每渠道公平配额、每关键词页数、保留岗位数全部有上限。
- 稳定平台 ID 去重。ATS ID 加公司 board 前缀。相同公司同名岗位但不同 ID 保留；跨渠道相似正文仅可提示重复，不能自动丢弃。
- 官网通用适配支持 JobPosting JSON-LD 和同域招聘页链接；其他系统明确报 `parse_error`。不根据页脚推荐岗位臆造公司招聘需求。
- 来源状态保留 `empty`、`filtered_empty`、`blocked`、`login_required`、`captcha`、`parse_error`、`fetch_error`、`budget_exhausted`、`cancelled`。部分成功保留正文，同时记录失败。用户停止后，在下一次请求前检查 `should_continue`，当前 HTTP 请求仍受25秒总超时约束；浏览器导航最多25秒、列表渲染额外最多20秒，均无无限等待。
- 岗位读取不包含投递。现有集中审核与快照授权继续约束后续申请动作。

## 真实验收与局限

原始证据只放本地 `private/verification/v2/`，不打包到开源项目。

| 来源 | 2026-10-22 真实结果 | 边界 |
|---|---|---|
| Greenhouse / Anthropic | 678条列表，保留5条含正文岗位 | 本轮按标题召回，响应及数量有上限 |
| Lever / Binance | 17条本轮列表，保留5条含正文岗位 | 非全公司/全网站覆盖承诺 |
| Ashby / Cursor | 133条列表，保留5条含正文岗位 | 仅这家公开看板 |
| 安克官网 | 已读40条，保留3条；一条详情缺可用正文，明确记录部分失败 | 没有掩盖为完整成功 |
| BOSS | 公开页只有 JS 外壳；独立浏览器未登录时曾明确跳转 `/web/user/` | 已实现采集与闸门，登录后端到端尚未验证，不能宣称已取到真实BOSS岗位 |
| 猎聘 | 公开列表需JS；独立浏览器只读搜索取得41个岗位链接，首个详情可解析为真实JD | 后续完整CLI多轮未成功：列表可读，但详情后来跳转wow.liepin.com非岗位页。已明确blocked并停止，不保证持续可用 |

全公开HTTP轮次记录：`discovery-public-live.json`，18条岗位，73.31秒（当次测量）。猎聘浏览器列表和真实首条正文：`liepin-browser-readonly-live.json`；纯应用 CLI 后续轮次使用 `discovery-liepin-*-live.json`。失败轮次同样保留，不删改为成功。后续定位记录 `liepin-detail-diagnosis.raw` 显示真实详情跳转到了平台的非岗位页面 `https://wow.liepin.com/t1012695/4410f519.html`；不能把这解释为岗位下线、空结果或已成功采集。读取器已改为检测这种跳转后立即停止，不再逐个重试详情。扫描不含登录、上传、投递、发送、关注或订阅。

## 可复现方式

```sh
# 公共源与公司官网（只读）
python -m hunt.discovery --keyword AI --keyword Agent --keyword Web3 --max-jobs 20 --max-pages 2 --output private/discovery.json

# 猎聘浏览器只读搜索（独立、无Codex依赖，可无登录先尝试）
python -m hunt.discovery --source liepin --keyword AI --browser-source liepin --headless --max-jobs 3 --output private/liepin.json

# BOSS确需登录时，用户在独立窗口自行操作
python -m hunt.sources_browser --login boss --data private/app
```

浏览器模式需 `requirements-executor.txt` 和 Playwright Chromium。应用服务端可传 `browser_profile_root=store.root/'browser-search'` 隔离数据目录；手动登录的 `--data` 要与工作台一致。不能把登录后的完整 DOM、浏览器会话、用户资料或验证输出放入公开仓库。

## 主要来源

- [Greenhouse Job Board API](https://docs.greenhouse.io/job-board)：公开 GET、job ID、content、详情、投递与读取认证区别。
- [Lever 官方 postings-api](https://github.com/lever/postings-api)：published postings、字段、skip/limit，以及非全文搜索的边界。
- [Ashby Job Postings API](https://developers.ashbyhq.com/docs/public-job-posting-api)：job board feed、descriptionPlain、薪资与 isListed。
- [SearXNG Search API](https://docs.searxng.org/dev/search_api.html)：JSON 输出需要实例启用、参数与分页。
- [JobSpy 官方 README](https://github.com/speedyapply/JobSpy/blob/main/README.md)：统一字段、错误与零结果区别、支持来源。
- [猎聘公开搜索](https://www.liepin.com/zhaopin/?key=AI&scene=input&inputFrom=www_index) 与 [BOSS 公开搜索](https://www.zhipin.com/web/geek/job?query=AI&city=100010000)：本地独立应用现场只读观察；平台未提供本项目专用或保证稳定的公开接口契约。

后续提高覆盖应增加更多公司 seed 与 ATS 系统、维护已验证来源目录和刷新时间、接入用户选定的搜索索引、记录来源命中/失效/重复率。不能靠扩大一个搜索词的页数实现“全网完整”。

## 2026-10-23 增量

公司招聘页可发现明确关联的 Greenhouse/Lever/Ashby 看板，包括 Next.js 内嵌 HTTPS 招聘 URL；再读取公开接口正文，保存关联引用。`official_only` 在预算分配前排除 BOSS/猎聘/网页索引。实际 UI 轮次保留 9 个岗位、3 重复、9 本地准备、0 申请。入口另外逐项核验：Anthropic Multi-Agent 表单可见，Cursor RL Data applyUrl 为 Page not found，安克要求登录。来源发布与入口可用分别记录，详情见 [调查与路径](boss-white-screen.md)。
