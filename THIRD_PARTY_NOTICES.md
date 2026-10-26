# 依赖与设计参考

本项目自身代码采用 MIT。以下依赖通过包管理器安装，不把第三方源码或字体重新打包进源码发布包；各依赖的许可证以所安装版本自带文本为准。

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

### career-ops-china

- 仓库：<https://github.com/shuheng-mo/career-ops-china>（career-ops 的中国大陆定制分支）
- commit：`bef1e7122d2d84a0bf7137a9d5ffb88808d05c5c`
- 许可：MIT。版权行：Copyright (c) 2026 Santiago Fernández de Valderrama (original career-ops)；Copyright (c) 2026 Mo Shuheng (China mainland customization)（取自该仓库 GitHub 许可证接口）。

| 本项目文件 | 来自上游 | 移植内容 |
| --- | --- | --- |
| `static/bookmarklets/boss-zhipin.js`、`liepin.js`、`lagou.js`、`mokahr.js`、`universal.js` | `tools/bookmarklets/` 同名脚本 | 页面字段选择器、BOSS 公司名纠偏、Mokahr 信息块解析、登录墙检测 |
| `static/bookmarklets/_deliver.js` | `tools/bookmarklets/*.js` 的发送部分 | 请求与载荷形状（改写） |
| `hunt/data/companies.cn.json`（由 `scripts/build_company_seeds.py` 生成） | `templates/portals-china.example.yml` | 其中 31 家公司的名称与招聘页链接 |

书签脚本的本项目改动：改为发到带令牌的本地收件箱，用 3 秒页面提示代替 `alert`，发送前截短正文。`companies.cn.json` 共 53 家：上游 31 家、本项目内置公司目录 `hunt/catalog.py` 9 家、本项目自选 13 家（文件内每条记录的 `source` 字段标明）。
