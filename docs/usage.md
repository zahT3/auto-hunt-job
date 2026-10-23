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
