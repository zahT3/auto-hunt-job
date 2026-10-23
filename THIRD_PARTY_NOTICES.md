# 依赖与设计参考

本项目自身代码采用 MIT。以下依赖通过包管理器安装，不把第三方源码或字体重新打包进源码发布包；各依赖的许可证以所安装版本自带文本为准。

| 依赖 | 用途 | 上游 |
| --- | --- | --- |
| pypdf | 本地 PDF 文字提取 | https://github.com/py-pdf/pypdf |
| ReportLab | 本地简历 PDF 输出 | https://www.reportlab.com/ |
| Playwright（可选） | 独立浏览器和本地夹具测试 | https://github.com/microsoft/playwright-python |

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
