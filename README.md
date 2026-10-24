# auto-hunt-job

少一些重复搜索，多一些合适的机会。

一个本地运行的求职工作台：上传简历，核对候选事实，搜索多个招聘来源，查看岗位与经历的关联，集中审核后再决定是否申请。

**当前为开发预览版。支持多渠道只读搜索，不承诺全网覆盖或自动投递成功。** 默认合成候选人、真实提交额度 0。简历解析和画像在本地完成，不依赖 Codex、模型密钥或付费服务。

## 快速开始

Python 3.10+，macOS 或 Linux。当前本机验收环境为 macOS/Python 3.12；Linux 自动检查由仓库 CI 执行。

```sh
git clone https://github.com/zahT3/auto-hunt-job.git
cd auto-hunt-job
sh setup.sh
.venv/bin/python -m hunt web
```

打开 <http://127.0.0.1:8766/>。macOS 也可双击 `Start.command`。

Linux 生成中文 PDF 需要中文 TrueType 字体，例如安装 `fonts-wqy-zenhei`；也可将环境变量 `HUNT_PDF_FONT` 指向有使用权限的中文 TTF/TTC。字体不包含在项目中。

## 从简历到岗位

1. 点击 **上传简历**，选择 PDF、DOCX、TXT 或 MD，最大 10 MiB。使用合成样例时保持“合成候选人”勾选。
2. 核对提取原文及页码/段落，选择准确事实。确认仅用于本地画像与匹配，默认仍为私密。
3. 采用或修改建议关键词，选择渠道与公司招聘页。城市和薪资可留空，未知条件不会自动变成符合。
4. 点击 **开始找岗位**。搜索在后台执行，按请求、页数和岗位数量预算收集、去重、准备本地记录。运行结果显示每个渠道的实际状态。
5. 查看相关技能、原文未提及项、硬条件和岗位原文。投递前集中审核具体岗位和材料，搜索过程不会发送消息或申请。

候选理解使用可解释的本地规则：提取技能提及、学历/经历线索及明确写出的整体工作年限。不会从项目时间推算资历，不把关键词命中当成熟练度，不输出录用概率。复杂排版、多语言缩写和隐含经验可能遗漏，应核对原文。

文字 PDF 支持页码来源。扫描 PDF 会提示需要 OCR；混合 PDF 会明确列出未提取页。当前未集成 OCR，不能声称支持任意简历。DOCX 正文及表格按段落提取，页眉页脚等遗漏会有提示。

## 搜索覆盖

| 来源 | 接入方式 | 边界 |
| --- | --- | --- |
| BOSS 直聘、猎聘 | 公开页面解析；可选独立浏览器只读采集 | 登录、验证码、站点结构与网络限制会影响结果，受阻单独报告 |
| 安克官网 | 官方公开接口，预算内分页和详情 | 关键词发现不代表候选人胜任 |
| Greenhouse、Lever、Ashby | 公司公开招聘 API | 仅扫描已配置的公司看板，不包含全部客户公司 |
| 其他公司官网 | 同站有限遍历、JobPosting、识别明确关联的 ATS 看板 | 不提供结构化数据或需要专用接口的网站会报告解析受限 |
| 扩展网页搜索 | 可选自有 SearXNG HTTPS JSON 端点 | 未配置时仍可搜所选渠道；索引结果须回源提取岗位正文 |

默认公司看板是可替换的开发示例，不代表你的求职偏好或匹配推荐。“全网扫描”的实现思路是**来源注册表 + 平台适配 + 搜索索引发现 + 回源核对 + 去重**。每次运行都受预算限制，不能宣称覆盖整个互联网。

可勾选 **本轮只查公司招聘来源** 暂时跳过 BOSS、猎聘和网页索引；在高级设置填写公司自己的招聘页，支持提取页面明确关联的 Greenhouse、Lever、Ashby 看板。岗位详情展示人工申请入口与关联来源。表单未核验时明确保留提示。

新增国内 AI / Agent 与 Web3 官网目录：DeepSeek、Dify、Kimi、阶跃星辰、Cobo、OKX、HashKey 已实测读取岗位正文；MiniMax 社招已通过匿名浏览器接通；imToken 通过官网站点地图恢复岗位页和邮箱读取，但官网列表异常，是否仍在招待确认。支持逐岗只读入口核验，以及有官网同职位表单证据时修复接收地址；邮箱申请单独展示。Kimi、阶跃星辰、MiniMax 需开启可选公开页面渲染。Moka 支持独立窗口本人登录后只读核验。详见 [官网来源与入口规则](docs/official-sources.md)。

BOSS 白屏调查、参考项目及官网替代路径见 [调查记录](docs/boss-white-screen.md)。源码研究、接口文档与实际限制见 [搜索方案](docs/search-research.md)。开发会话里的联网搜索工具不属于应用运行依赖。

### 可选浏览器

```sh
.venv/bin/python -m pip install -r requirements-executor.txt
.venv/bin/python -m playwright install chromium
```

在独立窗口由本人完成登录，再在高级设置里将相应来源切到浏览器模式。登录命令及数据目录见 [使用与集成](docs/usage.md)。不会复用日常 Chrome Cookie，不自动解决验证码，不打招呼、不上传简历。动态页面可能仍受阻；如实保留失败原因。

## 终端与网页

两种入口共用本地资料。`python -m hunt --help` 查看全部命令；支持 `web`、`resume`、`confirm`、`configure`、`scan`、`prepare`、`status`、`verify`。首次导入默认合成资料，确认事实需要逐项指定 ID。完整例子见 [使用说明](docs/usage.md#统一终端入口)。

界面以机会列表、判断依据和下一步为中心，支持手机列表/详情切换、键盘操作及减少动态效果。本地材料复核与对外授权分别处理；编辑搜索条件后先保存再运行。设计取舍与开源参考见 [界面说明](docs/interface-design.md)，本轮流程检查见 [v5 体验验收](docs/v5-ux-acceptance.md)。

## 独立运行与数据

```sh
# 离线合成夹具，与默认数据隔离
.venv/bin/python run.py --demo --port 8767
# 已配置来源的真实只读搜索，运行一轮退出
.venv/bin/python run.py --once
# 进程内定期搜索（电脑需保持唤醒）
.venv/bin/python run.py --periodic
# 独立数据目录
.venv/bin/python run.py --data private/my-search --port 8768
```

数据默认保存在 `private/app/`。原件、事实、岗位、材料、审批与执行记录均留在本机。备份时先退出运行器，再备份整个数据目录。暂停/停止阻止后续工作；已发出的网络请求可能需要到超时才结束。电脑睡眠或进程退出时不承诺继续运行。

上传不会自动更新活动候选人；核对后才激活。确认本地事实不等于允许对外披露。申请材料只采用已确认且允许申请披露的事实。已有申请批准绑定具体快照，资料、目标、岗位或文件变化会使批准失效。

当前仅安克有受控执行器，并且正式线上提交与回执尚未验收；其他渠道目前只读。模拟页面上的填写/上传/回执测试不代表真实投递成功。结果未知时禁止自动重发。详见 [隐私与安全](SECURITY.md)。

## 验证

```sh
.venv/bin/python -m unittest discover -s tests -v
node --check static/app.js
node --test tests/test_frontend.cjs
# 生成纯合成 PDF/DOCX 样例
.venv/bin/python examples/generate_synthetic_resume.py
# 检查已跟踪文件中没有私人目录、个人路径或类似密钥的内容
.venv/bin/python scripts/build_release.py --check
```

浏览器测试需要安装可选依赖与 Chromium，缺少时明确跳过。真实来源验证与本地夹具测试分开记录，见 [本轮验收](docs/v4-acceptance.md)。

## 开源

[MIT](LICENSE)。欢迎贡献招聘渠道、简历解析、匹配解释与无障碍体验，见 [贡献指南](CONTRIBUTING.md) 与 [依赖及设计参考](THIRD_PARTY_NOTICES.md)。请只使用合成资料提交测试和复现问题。
