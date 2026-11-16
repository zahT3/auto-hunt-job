# 依赖与设计参考

本项目自身代码采用 MIT。以下依赖通过包管理器安装，不把第三方源码重新打包进源码发布包；各依赖的许可证以所安装版本自带文本为准。网页界面随包分发两个字体子集，见下文「随网页界面分发的字体」。

| 依赖 | 用途 | 上游 |
| --- | --- | --- |
| pypdf | 本地 PDF 文字提取 | https://github.com/py-pdf/pypdf |
| ReportLab | 本地简历 PDF 输出 | https://www.reportlab.com/ |
| Playwright（可选） | 独立浏览器和本地夹具测试 | https://github.com/microsoft/playwright-python |
| cryptography（可选） | 解密 `app.mokahr.com` 响应信封（`requirements-sources.txt`） | https://github.com/pyca/cryptography |

PDF 字体使用用户本机已安装的字体或 `HUNT_PDF_FONT` 指定文件。发布包不包含 macOS 字体。

设计参考（未整合这些项目的整套实现，不代表获得其全部渠道能力）：

- [ai-job-search](https://github.com/MadsLorentzen/ai-job-search)：事实建档、复核和 PDF 检查。
- [JobPilot](https://github.com/suxrobGM/jobpilot)：目标活动、数量预算和防重。
- [JobSpy](https://github.com/speedyapply/JobSpy)：统一岗位结构与采集状态；当前未作为运行依赖。
- [jobhunter-ai](https://github.com/jolie-z/jobhunter-ai)：规则优先与物料检查；没有复制其 GPL 实现。
- [BossHunter](https://github.com/shengjidaguai-china/BossHunter)：成果边界、受控发送和渠道能力声明；其 PolyForm 非商业代码未复制进本 MIT 项目。
- [JobNavigator](https://github.com/vesaias/JobNavigator)：公司官网适配器与聚合搜索组合；本轮仅参考公开架构说明。

公开招聘接口文档：

- [Greenhouse Job Board API](https://docs.greenhouse.io/job-board.html)
- [Lever Postings API](https://github.com/lever/postings-api)
- [Ashby Public Job Posting API](https://developers.ashbyhq.com/docs/public-job-posting-api)
- [SearXNG Search API](https://docs.searxng.org/dev/search_api.html)

本轮白屏诊断还查阅 [boss-zhipin-scraper](https://github.com/eatmoreduck/boss-zhipin-scraper) 的 MIT 实现及 Issue，以及 [boss-agent](https://github.com/Douyh123/boss-agent) 的浏览器实现与 Issue。未复制其代码、注入脚本或运行第三方程序；实际采用的独立改动见 [调查](docs/boss-white-screen.md)。

## 随网页界面分发的字体

`static/fonts/` 里的两个文件是子集化后的修改版，按 SIL Open Font License 1.1 分发，许可证原文放在同一目录。运行时只从本机加载。

| 文件 | 来源字体 | 版权 | 内容 | 许可证 |
| --- | --- | --- | --- | --- |
| `inter.woff2` | Inter（google/fonts `ofl/inter/Inter[opsz,wght].ttf`） | The Inter Project Authors | 基本拉丁、拉丁补充、常用标点和符号；wght 300–700，保留 opsz | `static/fonts/OFL-inter.txt` |
| `sans-ui.woff2` | Noto Sans SC（google/fonts `ofl/notosanssc/NotoSansSC[wght].ttf`） | Adobe，保留字体名 "Source" | 界面代码里出现的汉字和 ASCII；wght 400–700 | `static/fonts/OFL-notosanssc.txt` |

下载日期 2026-11-02。子集由 `scripts/build_fonts.sh` 调用 `prototypes/_tools/subset_fonts.py`（fontTools）生成，字表取自 `static/` 里的界面文字。按 OFL 的保留字体名规定，修改版的文件名和 CSS 字体族名（`AH Inter`、`AH Sans`）都不使用 "Source"。

## 移植代码

下列文件移植或派生自两个 MIT 许可的开源项目。每个文件头写明来源仓库、commit 与 MIT；改写为 Python 或改为发往本项目的本地收件箱，未复制其运行时或依赖。

### career-ops

- 仓库：<https://github.com/career-ops-hq/career-ops>
- commit：`f4d7477c8d25f81e6e4a952b724378913ea8c86e`
- 许可：MIT。版权行：Copyright (c) 2026 Santiago Fernández de Valderrama（取自该仓库 GitHub 许可证接口）。

| 本项目文件 | 来自上游 | 移植内容 |
| --- | --- | --- |
| `hunt/providers/tencent.py` | `providers/tencent.mjs` | 请求参数、翻页规则、字段映射 |
| `hunt/providers/alibaba.py` | `providers/alibaba.mjs` | 请求体、XSRF 双提交令牌、翻页规则、字段映射 |
| `hunt/providers/meituan.py` | `providers/meituan.mjs` | 请求体（嵌套分页）、空页重试规则、字段映射 |
| `hunt/providers/feishu.py` | `providers/feishu-jobs.mjs` | 主机校验、macOS Chrome User-Agent 与同源 Referer、请求体、详情链接规则、字段映射；不含并发分页 |
| `hunt/providers/mokahr.py` | `providers/mokahr.mjs` | 主机与租户路径校验、robots 排除路径、AES-128-CBC 响应信封解密（密钥随响应下发，IV 固定）、请求体、翻页规则、字段映射 |

以上均改写为 Python 并接入本项目的来源注册表。`mokahr.py` 的解密依赖可选包 `cryptography`（`requirements-sources.txt`），未安装时 `app.mokahr.com` 租户报告 `not_configured`。

### boss-helper（只借思路）

- 仓库：<https://github.com/Ocyss/boss-helper>，参考的 commit：`00b1e13655da711492b08a9ed3fc04eb88d21670`
- 许可：MIT（Copyright 2024 Ocyss）。该项目 README 另写"仅供学习交流，禁止用于商业用途"；本项目没有复制它的代码或注释。
- 借用的思路：`static/bookmarklets/boss-zhipin.js` 从 BOSS 页面 Vue 2 组件（`__vue__`）上读 `jobList` 和 `jobDetail`，并包住这两个属性的 setter 来被动接收新数据；列表容器选择器 `#wrap .page-job-wrapper,.job-recommend-main,.page-jobs-main` 和这些属性、字段名取自该项目。代码由本项目自己写。它代替用户点卡片、自动翻页、轮询和请求 `/wapi/` 接口的做法没有采用。

### career-ops-china

- 仓库：<https://github.com/shuheng-mo/career-ops-china>（career-ops 的中国大陆定制衍生项目，不是 GitHub 上的 fork）
- commit：`bef1e7122d2d84a0bf7137a9d5ffb88808d05c5c`
- 许可：MIT。版权行：Copyright (c) 2026 Santiago Fernández de Valderrama (original career-ops)；Copyright (c) 2026 Mo Shuheng (China mainland customization)（取自该仓库 GitHub 许可证接口）。

| 本项目文件 | 来自上游 | 移植内容 |
| --- | --- | --- |
| `static/bookmarklets/boss-zhipin.js`、`liepin.js`、`lagou.js`、`mokahr.js`、`universal.js` | `tools/bookmarklets/` 同名脚本 | 页面字段选择器、BOSS 公司名纠偏、Mokahr 信息块解析、登录墙检测 |
| `static/bookmarklets/_deliver.js` | `tools/bookmarklets/*.js` 的发送部分 | 请求与载荷形状（改写） |
| `hunt/data/companies.cn.json`（由 `scripts/build_company_seeds.py` 生成） | `templates/portals-china.example.yml` | 其中 31 家公司的名称与招聘页链接 |

书签脚本的本项目改动：改为发到带令牌的本地收件箱，用 3 秒页面提示代替 `alert`，发送前截短正文。`companies.cn.json` 共 53 家：上游 31 家、本项目内置公司目录 `hunt/catalog.py` 9 家、本项目自选 13 家（文件内每条记录的 `source` 字段标明）。其中 31 家带本项目加的 `status` 字段（`dead` 或 `needs_adapter`，2026-10-26 实测结果），不是上游数据。

## v2 简历定制的来源与依赖

设计见 [docs/v2-tailoring-design.md](docs/v2-tailoring-design.md) 第 11 节，调研记录见 [research/v2-tailoring-sources.md](research/v2-tailoring-sources.md)。下面的 commit 都是调研时固定的提交；"移植"指改写逻辑并保留署名，"思路"指没有复制代码。

### Resume-Matcher（移植，Apache-2.0）

- 仓库：<https://github.com/srbhr/Resume-Matcher>，commit：`e2a32b6823bb7f5996cafdf007b6ba6f0efd8f98`
- 许可：Apache-2.0（许可证全文见上游 `LICENSE`；该提交的树里没有 `NOTICE` 文件，也没有逐文件的版权行）。

| 本项目文件 | 来自上游 | 移植内容与改动 |
| --- | --- | --- |
| `hunt/profile/tailor.py`（`apply_edits`） | `apps/backend/app/services/improver.py` 的 `apply_diffs`、`_BLOCKED_FIELD_NAMES` | 逐条过闸的顺序（操作在允许集合、目标不是身份字段、原文必须相符、reorder 须保持同一集合）。改为对事实 id 和修改记录操作，不用 JSON 路径；不移植 `add_skill`、`append` 和技能目标。 |
| `hunt/profile/tailor.py`（`check_result`） | 同文件的 `verify_diff_result`、`_METRIC_RE` | 章节数、身份字段、字数比、新出现的数字四项检查。字数比由 1.8 改为单行 1.5；数字正则扩到中文量词（万、亿、个月、年、人、家、次、倍、Top N 等）。 |
| `hunt/ai/tailor.py`（任务 3） | `apps/backend/app/prompts/templates.py` 的 `CRITICAL_TRUTHFULNESS_RULES_TEMPLATE` | 真实性规则译成中文并按本项目规则收紧。 |

文件头保留来源、commit、许可并注明已修改。不移植：`jd_added` 路径、`inject_keywords`、`heavy` 档。

### ai-job-search（移植，MIT）

- 仓库：<https://github.com/ai-job-search-dev/ai-job-search>，commit：`0d0d1a907a21454affa1b694acc4e2c5008a0d21`
- 许可：MIT。版权行：Copyright (c) 2026 Mads Lorentzen（取自该仓库 GitHub 许可证接口）。

| 本项目文件 | 来自上游 | 移植内容 |
| --- | --- | --- |
| `hunt/ai/tailor.py`（任务 3，岗位文本清理） | `tools/posting_guard.py` | 零宽字符、Unicode tag 字符、双向控制符、面向 agent 的指令句的扫描；不含 HTML 部分。 |
| `hunt/ai/tailor.py`（任务 3，审稿人 prompt） | `.claude/commands/apply.md` Step 3 Part A | 输出结构借用，内容自写。 |

### career-ops（只借思路，MIT）

- 仓库：<https://github.com/career-ops-hq/career-ops>，本节涉及的 commit：`c687a6f89aa766de468d41402df1ce24bdd86315`（上文「移植代码」一节引用的是另一个 commit，用于采集适配器）。
- 许可：MIT（Copyright (c) 2026 Santiago Fernández de Valderrama）。
- `hunt/profile/claims.py`（任务 3）借用 `verify-cv-facts.mjs` 的断言类别（数字、工具、雇主、奖项）和"动词漂移"的做法；规则和词表按中文自己写，没有复制代码。

### Reactive-Resume（只借思路，MIT）

- 仓库：<https://github.com/AmruthPillai/Reactive-Resume>，commit：`ac22d622d701bd114d97f11c99a5ce660c72a663`
- 许可：MIT（Copyright (c) 2026 Amruth Pillai）。
- 借用：修改列表、`expectedUpdatedAt` 对应本项目的事实版本号和 `stale` 状态、每个岗位一份的做法。只读了文档，没有读源码，没有复制代码。

### OpenResume（只当思路，AGPL-3.0，不移植）

- 仓库：<https://github.com/xitanggg/open-resume>，commit：`4f8255a2c763479837f69f1dccf2a3338730cd79`
- AGPL-3.0 会传染，所以不复制、不改写其代码。借用的只是"整行是章节标题"这一规律和"用解析器读回导出文件检查"的想法，由本项目的 `hunt/profile/intake.py` 和 `hunt/profile/structure.py` 自己实现。

### rewoven 分支的 `spider.js`（第二阶段，自有代码）

- 本仓库 `rewoven` 分支，commit：`4fb0e4b60fe5500bf1c6d4b6dc5042591c10a375`。`spider.js` 是本项目自己的重写，只借鉴上游 `zahT3/web-crawlers`（上游 `cyohei9907/web-crawlers`）的思路；上游树里没找到 LICENSE，所以不带入上游任何代码。第二阶段才会合入，合入时再列出文件。

### 新增运行时依赖与字体（任务 2 登记，合并时核对）

| 名称 | 用途 | 许可 | 状态 |
| --- | --- | --- | --- |
| python-docx 1.2.0 | DOCX 写出（`hunt/profile/resume_render.py`，惰性导入） | MIT（已验证：PyPI 元数据，见设计 8.4） | 作为依赖安装，不复制源码 |
| lxml 6.1.3 | python-docx 的依赖，含 C 扩展 | BSD-3-Clause（已验证：已安装包的元数据，2026-11-16） | 作为依赖安装，不复制源码 |
| typing_extensions 4.16.0 | python-docx 的依赖 | PSF-2.0（已验证：已安装包的元数据，2026-11-16） | 作为依赖安装，不复制源码 |
| Noto Sans SC（google/fonts `ofl/notosanssc`）的 GB2312 子集 | PDF 中文字体，`hunt/data/fonts/NotoSansSC-GB2312.ttf` | SIL OFL 1.1，许可证原文随字体放在同一目录 | 以 `scripts/build_pdf_font.sh` 头部记录的哈希为准；子集即衍生字体，字体族名按 OFL 保留字体名规定处理（任务 2 核对） |
