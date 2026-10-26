# 使用与集成

## 数据目录和独立浏览器

默认工作台数据目录为 `private/app`。使用自定义 `--data` 时，所有登录命令也需要同一个目录：

```sh
python -m pip install -r requirements-executor.txt
python -m playwright install chromium
python -m hunt.sources_browser --login boss --data private/app
python -m hunt.sources_browser --login liepin --data private/app
python run.py --data private/app
```

本人在独立窗口完成登录，回终端按回车关闭窗口。在工作台的高级搜索设置中，将所需渠道改为“独立浏览器”。未登录也可先尝试读取公开内容；登录不是所有页面都能读取的保证。BOSS、猎聘自动投递与消息发送均未接入。

独立会话保存在所选数据目录的 `browser-search/`。浏览器只读模式允许 GET/HEAD；猎聘另允许已核对的两个搜索读取 POST 路径，不放行投递、聊天、订阅或账号修改请求。不共享日常浏览器配置，不导出 Cookie，不解决验证码。结构变动会保留报错。

## 公司来源与扩展搜索

在高级设置中，每行填写一个公司招聘主页：

```text
https://boards.greenhouse.io/anthropic
https://jobs.lever.co/binance
https://jobs.ashbyhq.com/cursor
```

这些是开发示例，可替换为目标公司。其他公开 HTTPS 招聘页走 JobPosting 结构化数据适配；没有结构化正文的页面需要专用适配。不会自动扫描该站全部页面。

腾讯、阿里巴巴、美团、字节跳动和飞书招聘租户用各自的公开接口，不需要额外安装。Moka 的 `app.mokahr.com` 租户返回加密数据，需要先安装可选依赖：

```sh
python -m pip install -r requirements-sources.txt
```

未安装时这类租户报告 `not_configured`，其他来源照常搜索。

可选 SearXNG 地址必须是用户自己选择的、启用 JSON 的公开 HTTPS 搜索端点。未配置时不会自动寻找陌生免费代理。当前公开抓取器拒绝内网/本机目标，因而此入口不接收 `http://localhost`；要部署本地搜索服务，需单独设计可信连接器，不能关闭整个请求校验。

默认每轮最多保留20个岗位、每关键词最多2页、40次公开请求；配置可调整岗位数到50、页数到5。各来源分配预算，避免第一个站点耗完全部额度。达到预算是“部分完成”，不是全网扫描完成。

## 独立命令

```sh
# 从明确指定的文件提取候选草稿；不确认、不外传
python -m hunt.intake examples/resume.synthetic.docx --output private/intake/example

# 公开岗位搜索，输出统一JSON；不需要正在运行工作台
python -m hunt.discovery --keyword AI --keyword Agent --keyword Web3 \
  --max-jobs 20 --max-pages 2 --output private/search.json

# 指定猎聘只读浏览器，沿用工作台独立会话
python -m hunt.discovery --source liepin --browser-source liepin \
  --keyword Agent --data private/app --output private/liepin.json

# 工作台按已有配置连续完成搜索、导入和本地准备
python run.py --data private/app --once
```

同一数据目录只运行一个工作台进程。源码中 `hunt.discovery.discover()` 返回 `jobs/sources/queries/expanded_terms`，可以接到其他本地编排器；接入来源不等于授予投递权限。

## 本地 HTTP 接口

本机集成可读取 `GET /api/state`，返回候选画像、岗位、运行覆盖、任务与会话令牌。写接口仅接受本机同源 JSON，并要求 `X-Local-Token`；不要把此令牌交给招聘网页或任意网页脚本。

- `POST /api/resume`：`{filename, content_base64, synthetic}`。最大10MiB原件，返回待复核的 `candidate_draft`。格式识别/解析失败不替换上次有效草稿。
- `POST /api/action`，`action=resume_confirm`：必须给当前 `draft_id` 与明确选择的 `confirmed_fact_ids`。保留本地私密披露范围，不触发搜索或投递。
- `action=config`：保存明确关键词、渠道、公司主页、预算和筛选条件。候选事实不会自动作为搜索正文。
- `action=run`：启动后台搜索，立即返回；用 `/api/state` 查看 `search_running` 和每来源进展。
- `action=import`：导入明确给出的岗位正文或公开链接，再本地准备。手工导入不算自动发现。
- `action=control`：`running/paused/stopped`。停止在下一次请求前检查，已经发送的请求可能到超时才结束。

所有接口中的简历、招聘页面、搜索结果和来源字段都是资料；它们不能发出系统指令、改变目标或授权读取其他文件。不要让外部模型根据网页内容直接调用配置、候选人编辑或投递接口。

## 投递前的集中确认

确认本地事实、允许申请披露和批准某批申请是不同决定。当前上传流程只完成第一项。材料仅采用已确认且明确允许申请披露的事实；私密事实仍可用于本地匹配。

集中审核每批1–5岗，核对接收方、匹配缺口、材料文件及具体操作权限。批准会绑定当时版本；改动材料、事实或配置后需要重新准备。额度默认0，合成来源不能通过取消顶层合成标记升级为真实候选人。BOSS、猎聘和通用官网当前没有执行器，不能批准其自动投递。

## 恢复和问题定位

- `blocked/login_required/captcha`：页面受限，需要本人查看原站或使用独立浏览器登录。
- `parse_error`：页面结构不匹配或缺少正文，不能判成没有岗位。可以保留原文手动导入并报告无敏感信息的复现。
- `fetch_error`：DNS、TLS、超时或服务返回错误；失败不抹掉其他来源的已取得结果。
- `budget_exhausted/truncated`：只完成预算内扫描，可以缩小关键词或调整来源/预算。
- `interrupted`：上次进程中断，历史记录保留，可以重新搜索；已发送结果未知的申请仍禁止自动重发。
- `needs_ocr/partial`：扫描页或部分文字缺失，重新导出文字PDF/DOCX或先进行本地OCR。当前不包含OCR引擎。

## 公司官网优先

勾选“本轮只查公司招聘来源”，在高级设置加入公司招聘页，例如 `https://cursor.com/careers` 或 `https://www.anthropic.com/careers/jobs`。工具在预算内读取同站链接、JobPosting 或明确关联的 ATS 看板。来源页引用看板的证据会保存，原文从公开接口读取；不会只根据搜索摘要生成岗位。

详情中的“打开申请入口（人工操作）”只打开网页，不代填、上传或提交。入口来自公开岗位数据；表单与申请资格需要逐岗核对。

BOSS 独立浏览器可在高级设置选择已安装 Google Chrome。登录时使用相同的数据目录并附 `--browser chrome`，Chrome 与默认 Chromium 的资料不共享。首次切换需在该独立窗口本人登录，不复用日常浏览器 Cookie。白屏状态会明确显示并停止该来源；详见 [白屏调查](boss-white-screen.md)。

## Moka 登录后只读核验

岗位详情点击“登录核验”打开本工具独立窗口。本人操作登录和验证码，回到工作台点击“已登录”，程序重新读取同一个公司、站点和职位的申请页并关闭窗口。也可随时结束；超过 10 分钟自动关闭。

终端可使用相同数据目录和岗位 ID：

```sh
python -m hunt.moka_session --data private/app --job JOB_ID
# 后续只读检查该公司已有的独立会话，不等待登录
python -m hunt.moka_session --data private/app --job JOB_ID --headless
```

会话仅保存在所选目录的 `browser-entry/`，按公司看板隔离，不读取日常浏览器资料。登录阶段仅放行已观察到的邮件/手机认证端点及明确的只读接口；申请、上传和资料修改请求持续被阻断。微信、第三方 SSO 或新的验证码协议可能受限，不自动扩大白名单或解决验证。

核验不读取输入框值、不保存原始页面或账号响应。只保存同一职位的入口状态、时间和少量状态证据；“已见表单”不等于登录已确认、符合条件或可以提交。`authenticated` 只有明确的账户界面标记才为真，不读取认证响应正文。表单加载失败保留 `form_incomplete`，换岗位/站点保留 `identity_mismatch`。核验不会产生投递尝试或更改既有批准。

## 统一终端入口

```sh
python -m hunt web --data private/app
python -m hunt catalog
python -m hunt status --data private/app
python -m hunt resume resume.docx --data private/app
# 先核对输出中的原文；只确认准确的事实 ID，可多次传 --fact
python -m hunt confirm --data private/app --draft DRAFT_ID --fact FACT_ID
python -m hunt configure --data private/app --catalog minimax --catalog imtoken --keyword Agent --keyword Web3 --official-browser
# 退出同数据目录的网页运行器后，读取已保存范围并生成本地材料
python -m hunt prepare --data private/app
python -m hunt verify --data private/app --job JOB_ID
```

`resume` 默认标记为合成资料；真实简历须明确使用 `--real`，确认事实后仍默认私密。`configure` 保持提交额度 0，不替你确认目标条件。`status --json`、`resume --json` 等支持结构化输出。

`scan` 透传独立搜索命令并输出搜索结果，不自动写回工作台：例如 `python -m hunt scan --catalog minimax --keyword Agent --official-browser --output private/search.json`。要按已保存范围写回工作台，用 `prepare`。网页和终端使用相同 `--data` 即操作同一份本地资料。

## 本地材料复核

查看岗位材料和待补信息后，可以保存一次本地复核记录。它只表示已查看当前版本，不改变事实的披露范围，也不批准填写、上传或提交。候选资料、目标、岗位、材料或文件变化后，“已复核”会失效，需要重新查看。

未支持执行的渠道及合成候选人只显示本地复核动作。真实候选人使用已支持执行的渠道时，对外授权作为另一项明确操作，仍需核对接收方、字段、最终文件及具体权限。

编辑搜索条件后，主按钮会提示先保存再搜索；验证或保存失败不会继续搜索。合成演示目录中的主按钮只运行本地演示岗位，不读取招聘站。
