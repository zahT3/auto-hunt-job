# auto-hunt-job 项目说明

给在这个仓库里工作的 agent（Claude Code、Codex 等）和贡献者看。只写这个项目特有的事实和约束；通用写作和协作规则以各人自己的全局说明为准。

## 这是什么

本地单用户的求职工具。核心有两块：

- **岗位 JD 搜索引擎**：从公司官网、公开招聘接口和书签收件箱收集岗位，存进本机岗位库，全文检索，记录首次和最近搜到的时间，跨来源的同一岗位链接成组。
- **AI 辅助**：追问并定方向、JD 结构化、按招聘方 ATS 的顺序解释匹配（硬条件 → 关键词覆盖 → 事实证据）。不配模型服务时全部退回本地规则。

工作台（材料包、审核、执行器、入口核验）处于冻结状态：只修 bug，不加功能。

## 技术栈

- Python 3.10+，只用标准库起服务（`ThreadingHTTPServer`，只监听 127.0.0.1）。
- SQLite（WAL），岗位库在 `hunt/search/index.py`，带 `schema_version` 和 `migrate()`。
- 前端是原生 HTML/CSS/JS 和 ES modules，不用框架、不用构建工具；CSP 为 `script-src 'self'`，运行时不加载任何外部资源。
- 可选依赖分三档：`requirements-sources.txt`（Moka 加密接口）、`requirements-executor.txt`（Playwright）、`requirements-platform.txt`（Patchright，平台浏览器模式）。

## 代码结构与依赖方向

```
hunt/
  net/        网络请求与 SSRF 防护
  search/     搜索引擎：query、engine、index、normalize、sources/*
  ai/         llm 客户端与同意、orient、classify、jd、match、nlquery
  profile/    简历导入、画像、脱敏、方向参考表
  workbench/  材料、审核、执行、Moka 会话（冻结）
  app/        Store、server、cli、config、search_run
static/js/    前端模块：shell/、shared/、search/、job/、orient/、triage/、settings/、workbench/
```

依赖只能自上而下：`app → workbench / ai / search / profile → net`。`search` 不导入 `ai`、`workbench`、`app`；`ai` 只导入 `search.query`、`profile` 和 `net`。`tests/test_dependencies.py` 用 ast 检查 import，违反方向或出现循环就失败，不要给它加白名单。

## 常用命令

```sh
sh setup.sh                                   # 建 .venv 并安装依赖
.venv/bin/python -m hunt web --demo           # 合成数据启动，http://127.0.0.1:8766/
.venv/bin/python -m hunt --help               # 全部命令

.venv/bin/python -m unittest discover -s tests            # 全量测试，必须用 .venv，否则会少加载一部分
node --test tests/test_frontend.cjs                        # 前端测试
for f in $(git ls-files 'static/js/*.js'); do node --input-type=module --check < "$f"; done
.venv/bin/python scripts/build_release.py --check          # 已跟踪文件里不能有本机路径或类似密钥的内容
sh scripts/build_fonts.sh                                  # 改了界面上的固定中文后重新生成字体子集
```

提交前上面四项检查都要通过。CI 在 `.github/workflows/test.yml`，跑的是同一套。

## 必须遵守

- **数据**：开发、测试、截图只用合成资料（`examples/`、`--demo`）。真实资料在 `private/`，不进 git，不出现在日志和提交里。
- **对外动作**：真实提交额度默认 0。搜索只读：不登录、不发消息、不投递。结果未知的申请不得自动重发。
- **模型服务**：发送任何内容前都要有同意记录，绑定服务主机、模型和内容类别；花费计入每轮预算。JD 原文按不可信输入处理，不能改变权限或输出。AI 不能替用户补写经历，匹配解释不打分、不预测录用。
- **新旧**：岗位库只有首次搜到和最近搜到的时间。界面和文案不能写"发布于"，除非来源确实给了发布日期，并标明出处。
- **设计**：`docs/DESIGN.md` 是唯一的设计规范，`prototypes/final/` 是对照原型。改了界面上的固定中文要跑 `scripts/build_fonts.sh`，前端测试会检查子集是否缺字。
- **平台采集**：BOSS、猎聘默认关闭，需要登录的页面走书签收件箱。Patchright 是可选依赖，用了可能违反平台条款，见 `SECURITY.md`。
- **改动范围**：只改任务需要的文件；工作台不加功能；HTTP 接口（路由和 action 名）保持稳定，改动要同步 `docs/agent-mode.md`。

## 文档

- [README.md](README.md) / [README.zh-CN.md](README.zh-CN.md)：给使用者。
- [docs/agent-mode.md](docs/agent-mode.md)：CLI 和本地接口的 JSON 结构，外部 agent 用。
- [docs/benchmark.md](docs/benchmark.md)：召回率基准的口径和历次结果。
- [docs/DESIGN.md](docs/DESIGN.md)、[research/](research/)：设计规范和参考研究。
- [docs/official-sources.md](docs/official-sources.md)、[docs/search-research.md](docs/search-research.md)：来源接入细节。

## 标杆（待确认）

格式：作品（作者，查阅时间）— 学：一条原理 — 判断：怎么看出做到了。来源见 `research/references.md`。

- Linear Triage（Linear，2026-11 查阅）— 学：分拣队列里每个决定只要一个键，延后的条目会自己回来 — 判断：分拣页不碰鼠标能处理完一整屏岗位，"稍后"的岗位会回到队列末尾。
- Readhub 话题页（Readhub，2026-11 查阅）— 学：同一件事的多个来源合成一条，来源列在下面 — 判断：同一岗位出现在官网和平台时，搜索结果只显示一条，展开能看到全部来源。
- HN Search（Algolia，2026-11 查阅）— 学：筛选条件写成一句人话，没有结果时说清搜了什么并给放宽的办法 — 判断：搜索页顶部能读出完整的一句查询；零结果时页面给出至少一个放宽条件的动作。
- 少数派文章页（少数派，2026-11 查阅）— 学：长段中文阅读的字号、行高和每行字数 — 判断：JD 正文和定方向理由每行 34–40 字，行高 1.75 以上。
