# ACS 职位正文接入

可选本地命令 `python -m hunt acs` 接收 ACS 的离线正文提取结果，调用现有 `Store.import_job` 保存职位。默认仅预览；显式提供 `--data` 才写入指定目录。没有改变工作台搜索流程，没有自动发现职位、准备材料或提交申请。

## 输入与边界

输入是 ACS schema_version=1 的 `extract` JSON 和明确指定的原始 HTML。必须 execution_status=completed、quality.status=checks_passed、kind=article；核对 HTML 和正文的 SHA-256。岗位名称、公司、可选地点由调用方从正文中选定，必须在正文中出现。该检查不等于自动理解岗位；完整性仍为 unknown。

来源 URL、网页哈希、正文哈希、引擎、提取时间、质量状态保存在岗位 raw 中。网页获取时间通过 `--fetched-at` 显式提供，不能用提取时间冒充发布时间。薪资、发布时间、申请入口未知时留空，是否仍在招始终 unverified。导入不意味着职位适合用户。

模块不联网、不读个人简历、不读取 JSON 内嵌的 source.file 路径。网络获取由已有来源适配器负责，访问规则继续适用。导入以 ACS 渠道和完整来源 URL 的哈希去重，保留 query/fragment 身份；不会自动合并既有原生渠道的同一岗位，跨渠道仍需核对。

## 使用

在 ACS 的 Python 环境中运行（仅离线提取，不发请求）：

```sh
python -m anyone_can_spider.cli extract \
  --html /absolute/path/job.html \
  --url https://careers.token.im/en/contract-engineer \
  --engine trafilatura --output /absolute/path/acs.json
```

在 auto-hunt-job 环境中预览：

```sh
python -m hunt acs \
  --result /absolute/path/acs.json --html /absolute/path/job.html \
  --title '智能合约工程师' --company 'imToken' --location '台北 | 远程'
```

核对后，附加 `--data /absolute/path/isolated-hunt-data` 导入独立数据目录。参数中的岗位身份必须对应实际输入网页，不能照搬示例用于其他职位。已有原始网页和 JSON 都不覆盖。

## 2026-11-05 本机验证

真实来源为上述 imToken 官方页面，通过 robots 明示的 sitemap 发现。网页包含智能合约工程师 JD；旧页面能读取不证明当前仍招聘。

- ACS trafilatura 提取正文755字符。
- 对照已有 imToken 专用解析器的23个非空行，23行均出现在 ACS 正文中；这不是独立人工完整性标注，也没有证明 ACS 比专用解析更好。
- 实际导入独立求职库；第二次导入 duplicate=true，仍为1行。
- 入库正文与 ACS 输出逐字相同；状态new、在招unverified；package/approval为空，申请尝试0。
- 7项接入测试通过，涵盖失败拒绝、篡改拒绝、字段原文约束、默认不写库、身份和重复导入。
- 完整 Python 回归：837 tests in 84.578s，OK。static/app.js 语法检查通过。发行扫描检查149个已跟踪文件通过；新增未跟踪文件不在该扫描范围。

证据在本机 ACS 的 `var/integrations/auto-hunt-job-2026-11-05/verification.json`。原始网页未提交进仓库。

下一步以既有读取器失败的来源做对照，证明新增可用 JD 数和人工修正时间，再决定是否接入常规搜索。当前只交付可调用接口与一个真实样本，不宣称自动搜索已经改由 ACS 驱动。
