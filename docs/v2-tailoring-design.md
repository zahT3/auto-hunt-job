# v2 设计：为一个岗位定制简历

状态：待用户确认，未实现。证据和固定提交见 [research/v2-tailoring-sources.md](../research/v2-tailoring-sources.md)。

## 1. 结论

- 做什么：在岗位页加「为这个岗位改简历」，产出一份**只由已确认事实组成**的定制版简历，逐条审核，导出 PDF、DOCX、Markdown，并用本工具自己的解析器把导出文件读回来检查。
- 怎么保证不编造：定制版不是一份新写的文字，而是**原始事实上的一串修改**。每条修改写明引用哪些事实（id 和版本）、服务哪一条岗位要求。不引用事实的文字不能进入导出文件。
- 不用模型也能用：规则路径只做三件事：同一职责内按相关度调序、同义词换成岗位原词（限一张很短的白名单）、列出缺口。AI 路径在这之上多一步「改写措辞」，要过一道本地确定性检查，模型自己说了不算。
- 复用方式：按已定的决定，不用别的语言重写。MIT / Apache-2.0 的做法用 Python 移植并署名；非商用许可只当思路。实际能直接搬的**代码很少**，主要搬的是门槛的设计：Resume-Matcher 的修改应用闸门和校验（Apache-2.0）、ai-job-search 的审稿人分工和岗位文本扫描（MIT）。
- 最大风险：现有「事实」是简历按段落切出来的一行行文字，没有「公司 / 职位 / 时间 / 要点」的结构。调序和删减需要条目结构。已定方案：程序预填，用户在定制页确认一次（第 4.3 节），没确认就不能定制。

## 2. 调研

### 2.1 各项目做了什么

| 项目 | 许可 | 机制 | 防编造 |
|---|---|---|---|
| ai-job-search `/apply` | MIT | 起草者写 CV 和求职信，审稿人（只读工具）返回结构化 edits `{file, old_string, new_string, reason}` 加叙述建议，起草者应用，再编译 PDF、抽文字层、查关键词覆盖 | 起草前后各做「事实核对」：日期、职位、数字必须出现在三份来源（档案、主简历、CLAUDE.md）之一；关键词缺口「不堆砌」；用户新说的事实要在同一轮写回档案，否则下次会被当编造删掉 |
| career-ops `pdf` | MIT | 抽 15–20 个关键词，先跑零模型的技能缺口检查，再生成 JSON 载荷、渲染 HTML、事实闸门、PDF、再核关键词覆盖 | `verify-cv-facts.mjs` 是渲染前的硬闸门，查量化数字、工具名、雇主、奖项；「动词漂移」检查（来源写「Used」，成品写「Led」就报）；换动词只能由用户在 `allow_swaps` 里声明 |
| Resume-Matcher | Apache-2.0 | 模型只返回 `changes[{path, action, original, value, reason}]`，本地逐条应用 | 路径白名单、字段黑名单、`original` 必须与原文逐字相符、reorder 必须是同一批元素；事后查段落数、身份字段、字数比 1.8、新出现的数字；prompt 里九条「真实性规则」 |
| Reactive-Resume | MIT | 简历是 JSON，修改走 JSON Patch；每个岗位复制一份简历并与该岗位绑定 | 不处理「是否编造」，这是编辑器；只取「版本号防覆盖」和「一岗一份」两个做法（只读了文档，没读源码） |
| OpenResume | AGPL-3.0 | 在浏览器里解析 PDF：行分组、按整行章节标题分段、特征打分 | 无；思路是「用解析器读回来看你的简历能不能被读对」 |
| 本仓库 `rewoven` | 自有代码 | 上传简历后，用写死的修改建议演示一个蜘蛛爬过文字并改写的动效 | 无：编辑是写死的，不对应岗位 |

### 2.2 能搬什么、不能搬什么

| 来源 | 可以直接移植（带署名） | 只当思路 | 与我们的规则冲突 |
|---|---|---|---|
| Resume-Matcher | `apply_diffs` 的闸门逻辑；`verify_diff_result` 的 2–5 项检查；真实性规则文字（译成中文） | `verify_skill_target_plan` 的四分类 | `jd_added`：允许把岗位里有、简历里没有的技能加进去，只靠用户在预览里看。我们不允许。`heavy` 档整篇重写。`_sanitize_user_input` 只有八条英文正则，挡不住我们要防的东西 |
| ai-job-search | `posting_guard.py` 里零宽字符、Unicode tag 字符、双向控制符、指令句的扫描；审稿人 prompt 的 Part A 结构 | 起草者与审稿人分开、审稿人没有写权限；覆盖表四个状态；按「相关度 × 唯一性 × 叙事负载」裁剪；标准流程里「写回事实」的规则 | 「Overall fit score」（我们不打分）；审稿人联网研究公司（我们不向外发岗位以外的内容）；自动追加投递记录（工作台已冻结）；LaTeX 工具链 |
| career-ops | 无整段移植。`verify-cv-facts.mjs` 有 4500 行，大量正则针对英文，换成中文等于重写 | 事实闸门的断言类别（数字 / 工具 / 雇主 / 奖项）；动词漂移；`allow_swaps` 由用户声明；`locked_sections`；把标签式技能合并成一行用顿号隔开，解析器才读得对；缺口先告诉用户再动手 | 在摘要里「注入关键词加出场叙事」，摘要是新写的，无法追溯；扫描门户、自动流水线；「HM 审计」联网研究面试官 |
| Reactive-Resume | 无 | JSON Patch 式的修改列表；`expectedUpdatedAt` 防覆盖，我们对应「基准版本」 | 无 |
| OpenResume | **不移植**（AGPL 会传染） | 读回导出文件检查的思路；用本工具自己的 `intake` 实现 | 无 |
| rewoven | `static/spider.js` 作可选动效（见 7.3） | PDF 逐页渲染依赖 Poppler，预览不需要，不取 | 写死的编辑；`rewoven.py` 与活动候选人分离的做法保留成原则：预览不写候选人 |

`spider.js` 的授权要单独说一句：它自述是独立实现，只借鉴了上游 `web-crawlers` 的思路，没打包上游代码；但上游树里没找到 LICENSE。只要不带入上游代码就没有授权问题，需要用户确认这一点（第 14 节第 8 题）。

## 3. 不变的规则与本设计加的硬规则

沿用 AGENTS.md：只用已确认的事实；AI 不补写经历；不打分、不预测；发送内容前要有同意记录并计入预算；岗位原文是不可信输入；工作台冻结，真实提交额度保持 0。

本设计新增：

1. 导出文件里每一行，要么与某条已确认事实逐字相同，要么带一条已接受的修改，并且修改引用的事实仍是已确认且版本未变。导出前由 `trace()` 检查，不通过就不写文件。
2. 岗位里有、事实里没有的词，不会进入简历。缺口只列在侧栏，由用户决定要不要「补充事实」，走现有的确认流程。
3. 不新写摘要、自我评价、「求职意向」。只有用户自己确认过的摘要类事实才会出现。
4. 模型只能提议修改，不能直接改简历。它的输出必须通过本地检查才会出现在审核界面，通过了也默认「待审核」，不会自动进入导出。
5. 导出只写本机文件，不发送、不投递。

## 4. 数据模型

### 4.1 一份定制版

定制版 = 基准 + 修改列表。简历正文不单独存，由「已确认事实 + 已接受的修改」算出来。

```json
{
  "schema_version": 1,
  "id": "tl-<job_id>-v3",
  "job_id": "…",
  "version": 3,
  "created_at": "2026-11-16T10:00:00+08:00",
  "by": "rules | ai",
  "model": {"host": "…", "model": "…"},
  "base": {
    "facts": [{"id": "intake-…", "version": 2}],
    "jd_digest": "…",
    "match_digest": "…"
  },
  "layout_version": 1,
  "edits": [Edit],
  "gaps": [Gap],
  "rejected_by_gate": [{"edit": {…}, "reason": "new_term"}],
  "checks": {"trace": "pass", "export": null}
}
```

`Edit`：

```json
{
  "id": "e7",
  "op": "reorder | hide | alias | rephrase",
  "fact_ids": [{"id": "intake-…", "version": 2}],
  "requirement": {"type": "keyword | duty | hard", "value": "Kubernetes",
                  "jd_evidence": "熟悉 Kubernetes 容器编排", "ref": "k3"},
  "before": "逐字取自事实的原文",
  "after": "修改后的文字；reorder 为新顺序，hide 为 null",
  "why": "一句话，规则路径由程序填，AI 路径取模型的 why",
  "by": "rules | ai",
  "status": "accepted | pending | rejected | stale",
  "checks": {"claims": "pass", "reviewer": "ok | unsupported | overstated | off_topic | null"}
}
```

`Gap`：`{type: absent | related | hard_not_met | hard_unknown, requirement, jd_evidence, related_terms, fact_ids}`。直接来自 `job_match` 的 `keywords[coverage != explicit]` 和 `hard[status != met]`，不另算。

`requirement.ref` 对应 `job_match` 返回行的序号（`k3` 是 `keywords[3]`，`d1` 是 `evidence[1]`，`h0` 是 `hard[0]`）。`match_digest` 是这些行的哈希，岗位结构或事实变了就能发现修改已过期。

### 4.2 版本

- 每个岗位一串版本，从 1 起，只增不改。重新生成得到 v+1；用户在审核界面的接受和撤销是**同一版本内**的状态变化。
- 一条修改引用的事实被改过（`version` 变了）或不再是已确认状态，这条修改变为 `stale`，不进导出，界面提示「事实已变，需重新审核」。借自 Reactive-Resume 的 `expectedUpdatedAt`。
- 导出时记下当时的版本号和文件哈希，文件名带版本：`<公司>-<岗位>-v3.pdf`。

### 4.3 版面（layout）：由用户确认的条目结构

事实是 `intake.analyze_resume` 按段落切出的行，每行带 `source.reference = upload://<sha>#page=1&paragraph=12`，没有条目结构。调序和隐藏需要知道「哪些行属于同一段经历」，所以让用户确认一次，之后不再靠猜。

**数据。** 候选人记录里加一个 `layout`，与 `facts` 分开存，所以事实的 id 和版本不受影响：

```json
{"layout": {"version": 1, "confirmed": true, "facts_digest": "…",
  "sections": [{"key": "work", "title_fact": "intake-…",
    "entries": [{"head": "intake-…", "lines": ["intake-…", "intake-…"]}]}]}}
```

`layout` 只引用事实 id，不含任何文字。每个事实最多出现一次；没有被放进任何条目的行归入「未归类」，不会进入定制版。

**怎么得到。**
1. 程序先给一个建议版面：章节标题 = 整行短（≤12 字）且命中章节词（教育、工作经历、项目经历、专业技能、证书、自我评价等）；条目头 = 章节内含日期区间的行（`2021.07–2023.03`、`2021年7月至今`），到下一个条目头之间的行归入该条目。章节标题的思路来自 OpenResume 的「整行是章节标题」，规则自己写。
2. 用户在定制页第一次进入时看到「整理结构」：左边是原行，右边是章节和条目，可以拖行、拆分和合并条目、改章节归属。建议版面只是预填。
3. 用户点「确认结构」后 `confirmed = true`。没有确认的版面不用于定制：页面停在「整理结构」。
4. 事实被新增、删除或重新确认导致 `facts_digest` 变了，只把受影响的行标成「未归类」，其余条目保留，让用户补一步，不整体作废。

这一步放在定制页里，不改工作台的「确认事实」流程（工作台冻结）。

**规则。** 调序只在一个条目内部发生，条目之间的顺序不动（经历保持新到旧，career-ops 也强制这一点）。条目头所在行不参与调序，也不参与隐藏。

### 4.4 放在哪一层

不新增层，`tests/test_dependencies.py` 不用改：

| 文件 | 层 | 内容 | 允许的依赖 |
|---|---|---|---|
| `hunt/profile/tailor.py` | profile | 版面建议与校验、规则路径、`apply_edits`、`trace` | 标准库 |
| `hunt/profile/resume_render.py` | profile | Markdown / PDF / DOCX 写出、读回检查 | `profile.intake`、reportlab、pypdf |
| `hunt/profile/claims.py` | profile | 改写后文字的事实核对（见 6.3） | 标准库 |
| `hunt/ai/tailor.py` | ai | 起草者、审稿人、prompt、缓存 | `ai.llm`、`ai.orient`、`profile.*` |
| `hunt/app/tailor.py` | app | Store 的 `TailorActions`、SQLite 表、导出目录、CLI | 所有层 |
| `static/js/tailor/` | 前端 | 审核页 | `shared/` |

规则路径要用 `job_match` 的结果，但 profile 层不能导入 `ai.match`。解决：`profile.tailor` 的函数把 `match` 的返回值作为**参数**接收，不导入；由 app 层把两边接起来。同义词白名单（5.1）放在 profile 层，不依赖 `match.RELATED`，因为 `RELATED` 把「相近」和「同义」混在一起（`TypeScript` 与 `JavaScript`、`深度学习` 与 `机器学习`），不能拿来改写。

存储：Store 的 SQLite 加一张表 `tailored(id TEXT PRIMARY KEY, job_id TEXT, version INTEGER, data TEXT, created TEXT, UNIQUE(job_id, version))`。不碰工作台的 `packages` 表，不复用 `hunt/workbench/export.py`（冻结）。导出文件放 `<data>/tailored/<job_id>/v<N>/`，目录 0700、文件 0600，沿用 `export.write_package` 的做法。

## 5. 生成

### 5.1 规则路径（不用模型）

输入：已确认事实、已确认的版面（4.3）、`job_match` 的结果。输出：一组 `by: "rules"` 的修改和缺口。

1. **相关度。** 每条事实服务几条岗位要求：关键词行里 `coverage == explicit` 且 `fact_ids` 含它；职责行 `status` 为 supported 或 related；硬条件行 `met`。这个数只用来排序，界面不显示，也不叫分数。
2. **reorder。** 块内按相关度降序，同相关度保持原顺序。技能类的一行（「技能：Python、SQL、Docker」）按顿号拆开，把岗位点名的项提前，项的集合不变。
3. **alias。** 关键词行 `coverage == related`，且 `related_terms` 里某个词与关键词在白名单中同义，才提议把事实里的那个词换成岗位原词。白名单初版只放真正同义的：`Kubernetes/k8s`、`PostgreSQL/Postgres`、`Go/Golang`、`自然语言处理/NLP`、`大模型/LLM/大语言模型`、`用户研究/用研`。`容器编排`、`深度学习`、`TypeScript` 这类「相近但不同」的不在白名单，只进缺口。这是为了让 ATS 的字面匹配认得，ai-job-search 的「用岗位原词」规则也是这个意思。
4. **hide。** 只在导出超过页数上限时发生（默认不限）：按「相关度 × 唯一性」从相关度为 0 的最旧块里的末行开始提议隐藏，直到够页数。借 ai-job-search 的「按相关度裁剪」。隐藏只在这一版里，事实本身不动。
5. **缺口。** `coverage` 是 `absent` 或非白名单的 `related`，以及未满足或不明的硬条件，原样放进 `gaps`，每条带岗位原文引用和「我有这项，去补充事实」的入口。

规则路径的修改默认 `accepted`：它们不新增任何文字，只调序和替换同义词，随时可撤销。AI 路径的修改默认 `pending`。

### 5.2 AI 路径

前提：`orient.model_mode` 返回可用（有简历同意、有密钥、有已确认事实），且有岗位原文同意（`job_text`）。不需要新的同意类别：发出去的内容仍然是这两类。同意仍绑定服务主机和模型。

**发送的内容。** 已确认事实（脱敏模式下过 `redact.redact_facts`）；岗位要求列表（关键词值、职责条目及其原文引用），不发整篇岗位原文。脱敏改过的事实不参与改写（`redact` 后文字与原文不等就跳过），避免把占位符带回简历。

**岗位原文当不可信输入。**
- 进入 prompt 前走从 `posting_guard.py` 移植的清理：去零宽字符、Unicode tag 字符、双向控制符；面向 agent 的指令句只标记不发送。
- 要求项放进带分隔标记的数据块，system 提示明说块里是数据。
- 模型只能返回固定 schema 的 JSON，没有工具、没有联网、没有文件权限。
- 最后一道防线是第 6 节的本地检查：注入最多让模型写出一条改写，这条改写还得过检查才出现在界面，还默认待审核。

**起草者。** 一次调用，输出：

```json
{"edits": [{"op": "rephrase", "fact_ids": ["intake-…"], "requirement_ref": "k3",
            "after": "…", "why": "…"}], "notes": ""}
```

prompt 规则取自 Resume-Matcher 的真实性规则，译成中文并按我们的规则收紧：不加事实里没有的技能、工具、数字；不升级职级和职责强度；不改日期；每条只改一行；`after` 必须用事实里已有的内容；允许把事实里的说法换成岗位里同义的说法；没有可改的就返回空列表。

**审稿人。** 第二次调用，换一份 prompt，输入是通过了本地检查的修改、事实原文、岗位要求引用。每条返回 `ok | unsupported | overstated | off_topic` 和一句话。审稿人**只能降级，不能改文字**（对应 ai-job-search 里审稿人没有编辑权限）。非 `ok` 的修改仍显示，带红色标记。

**预算。** 起草者 + 审稿人共 2 次调用，用现有 `Meter` 和 `chat_json`；每次调用前按最坏情况（`Meter.projected`）检查，超出本轮上限就不调用。界面点击前显示：「将向 <host> / <model> 发送 N 条已确认事实和 M 条岗位要求，最坏花费约 ¥x」。结果按 `(jd_digest, 事实摘要, 模型, prompt 版本)` 缓存，重复点击不再花钱（与 `jd_extract` 的缓存同一做法）。

**失败。** 无同意、无密钥、预算不足、模型输出不合格：回退为只有规则路径的结果，并在界面写明原因，不静默。

## 6. 事实核对（两条路径共用）

### 6.1 应用修改

`apply_edits(facts, layout, edits)` 逐条过四道闸，移植自 Resume-Matcher 的 `apply_diffs`：

1. 操作在允许集合内（`reorder / hide / alias / rephrase`），目标是已确认事实。
2. 不碰身份行：姓名、联系方式、公司名、学校、学位、日期所在的行不允许 `rephrase`，只允许 reorder 和 hide（黑名单思路来自 `_BLOCKED_FIELD_NAMES`）。
3. `before` 与事实原文逐字相等（NFKC 折叠后比较）。
4. `reorder` 的新顺序必须与原集合相同；`hide` 不能把一个块隐藏到没有头。

不过的进 `rejected_by_gate`，界面可展开看，不丢。

### 6.2 事后检查

移植 `verify_diff_result` 的第 2–5 项，逐版本检查：块数不变；身份行不变；单行改写后字数不超过原行的 1.5 倍；新出现的数字和量词。中文的量词要补：`%`、`倍`、`万`、`亿`、`个月`、`年`、`人`、`家`、`次`，以及 `\d+[+＋]`。

### 6.3 改写核对（AI 的 `rephrase` 专用，`profile/claims.py`）

借鉴 career-ops 事实闸门的断言类别，规则自己写，针对中文。每条 `rephrase` 都要全部通过：

1. **新词。** `after` 里所有拉丁词、数字、专有名词，必须出现在引用的事实里；或者与事实里某个词在同义白名单里等价，并且正好是该条要求的关键词。否则 `new_term`。这条是「岗位有、简历没有的词不进简历」的执行点。
2. **数字与量词。** `after` 的数字集合与 `before` 相同。
3. **职责强度。** 开头动词的等级不能上升。初版等级：了解 < 参与 < 协助 < 负责 < 主导 / 牵头 / 带领；对应 career-ops 的「动词漂移」。换动词要用户自己在设置里加白名单，借鉴 `allow_swaps`，默认空。
4. **内容重合。** 去掉虚词后，`after` 的中文 3-gram 至少九成出现在「引用事实 + 该条要求原文」中；英文词同理。阈值要用夹具调，保守起见失败即丢弃。
5. **不抄岗位。** `after` 中连续 12 个字以上与岗位某一行相同、而事实里没有，判为 `copied_from_jd`。这是针对「把岗位要求直接贴进简历」和注入的。
6. **没有新载体。** 不含链接、邮箱、手机号。

这套检查是启发式的：它挡得住加词、加数字、升级职责，挡不住「措辞不变但语义被改」的微妙情况，例如否定变肯定。所以修改必须经用户逐条看到 before / after（第 7 节），审稿人的意见也只是辅助。

## 7. 审核界面

入口：岗位页的匹配区下方加按钮「为这个岗位改简历」，路由 `#/job/<id>/tailor`。没有已确认事实时，页面只说明原因和去确认事实的链接。

### 7.1 布局

左右两栏，窄屏上下叠放：

- 左：已确认事实，按已确认的版面分章节和条目，原样显示。
- 右：定制版，同样的章节和块。被修改的行显示逐字 diff（删除线和下划线）；hide 的行折叠成一行「已隐藏 1 条，展开」。
- 每条被修改的行下方一行：操作类型、`对应岗位要求：Kubernetes`（点开跳到岗位原文引用并高亮）、`来源：intake-…（第 1 页第 12 段）`（点开显示事实原文）、接受 / 撤销按钮。
- 右侧或下方一个窄栏「缺口」：未覆盖的关键词和未满足的硬条件，各带岗位引用和「补充事实」。没有分数、没有进度条。
- 底部：待审核条数、预检结果、导出按钮。有待审核修改时，导出按钮写「导出（不含 N 条待审核）」。

键盘：`j/k` 下一条/上一条修改，`a` 接受，`u` 撤销，借 Linear Triage「一个决定一个键」的做法（`AGENTS.md` 里的标杆）。

AI 被拒绝的提议（`rejected_by_gate`）折叠在页面底部，写明被拒原因，让用户知道模型提过什么。

### 7.2 与现有界面的衔接

- 版本下拉：`v3（规则 · 今天）`，可切换看旧版，旧版只读。
- 「用 AI 改写措辞」是一个单独的按钮，点之前显示 5.2 里的发送说明和最坏花费。没有同意或密钥时按钮置灰并写原因。
- 界面新增固定中文，要跑 `scripts/build_fonts.sh`，前端测试检查子集不缺字。
- 遵守 `docs/DESIGN.md`；页面文案只留字段标签、状态和操作后果，不加口号。

### 7.3 Rewoven 动效（可选）

默认关。设置里一个开关「播放修改过程」。打开后，进入页面时用 `spider.js` 沿右栏文字走一遍，到达被修改的行时触发改写动画。它只读同一份 `edits`，不决定内容；系统设置「减少动态效果」时强制关闭；不阻塞接受和撤销。写死的示例编辑全部丢弃。这一项放在第二阶段，不影响主流程。

## 8. 导出与自检

### 8.1 格式

- **Markdown**：最先做，纯文本，也是自检的基准。
- **PDF**：reportlab（已是依赖）。单栏、纯文本层、不用图标和标签栏、页眉页脚不放正文。中文需要内嵌字体，沿用 `hunt/workbench/export.py` 的做法（`HUNT_PDF_FONT` 或系统字体），找不到就明确报错，不降级成乱码。
- **DOCX**：用标准库 `zipfile` 写最小的 OOXML（段落、粗体标题），不加新依赖。`intake` 已能读 DOCX，往返可测。
- 技能写成一行用顿号隔开，不做标签栏；这是 career-ops `ats-payload.mjs` 实测出的坑（标签之间只有 CSS 间距，文字层会粘成一个词）。
- 同时写 `trace.json`：每一行对应的事实 id、版本、修改 id。

### 8.2 自检：读回导出文件

用 `profile.intake.analyze_resume(filename, bytes)` 读刚导出的 PDF / DOCX，和渲染前的行对比：

1. 每一行（空白折叠、NFKC 之后）能在读回的文字里找到；找不到的行数列出来。
2. 读回时的乱码、`(cid:…)`、替换字符告警原样显示（`intake` 已有）。
3. 章节标题出现的顺序与渲染时一致，防止多栏把阅读顺序打乱。
4. 页数不超过上限（默认 2 页）。
5. **关键词覆盖对照**：把读回的行当作临时事实，再调用一次 `match.explain(structure, 读回的行)`，列出每个岗位关键词在导出文件里是「原词 / 相近 / 没有」，并与导出前对比。这是给用户看的清单，不汇总成百分比。

界面写明：「这是用本工具自己的解析器重读，不代表任何招聘系统的实际结果。」（我们只做了读回，没有对接过任何真实招聘系统。）自检不通过时不阻止导出，但在界面上方显示，并写进 `trace.json`。

## 9. 求职信（可选，第二阶段）

规则相同：求职信是**段落列表**，每段引用事实和岗位要求，同样存成修改和事实的关系，同样过 6.3 的检查。

- 规则路径：模板 + 槽位。岗位名和公司名取自岗位记录；中段把 2–3 条 `supported` 的职责对照逐字引用事实原句；落款取自事实里的姓名。不写缺口，缺口留给用户在侧栏决定要不要补充事实。
- AI 路径：同 5.2，只多一类输出（段落），且每句必须引用事实。
- 不联网查公司、不引用岗位记录以外的公司信息（与 ai-job-search 的审稿人联网研究不同）。
- 称呼用「您好」，不猜收件人。
- 导出 Markdown / PDF，文件名和简历同一版本号。

## 10. CLI 与 agent 模式

动作名一经加入就要稳定，同步 `docs/agent-mode.md`。

| CLI | `/api/action` | 说明 |
|---|---|---|
| `hunt tailor JOB_ID [--ai]` | `tailor` | 生成新版本，返回完整结构 |
| `hunt layout [--set FILE]` | `layout_get` / `layout_save` | 读取建议版面，或保存用户确认的版面 |
| `hunt tailor_get JOB_ID [--version N]` | `tailor_get` | 读某一版 |
| `hunt tailor_review JOB_ID --accept e1,e2 --reject e3` | `tailor_review` | 改修改状态 |
| `hunt tailor_export JOB_ID --format pdf,docx,md [--version N]` | `tailor_export` | 导出并返回自检结果 |

五个动作都加入 `RESULT_ACTIONS`。`--ai` 在没有同意时返回规则路径的结果加明确原因，退出码不变，由调用方读 `ai.used` 字段判断。外部 agent 可以不开界面完成整个流程；agent 不能绕过检查：`tailor_review` 接受一条 AI 改写前，服务端会重新跑 6.3。

## 11. 移植清单与署名

署名统一写进 `THIRD_PARTY_NOTICES.md`（仓库已有）：来源、固定提交、许可、移植到哪个文件。Apache-2.0 另需在文件头保留版权声明并注明修改。

| 目标文件 | 来源 | 固定提交 | 许可 | 方式 |
|---|---|---|---|---|
| `hunt/profile/tailor.py` 的 `apply_edits` | Resume-Matcher `services/improver.py:apply_diffs` | `e2a32b6` | Apache-2.0 | 移植逻辑，改为对事实 id 操作；文件头署名并注明已修改 |
| 同上 `check_result` | Resume-Matcher `verify_diff_result`、`_METRIC_RE` | `e2a32b6` | Apache-2.0 | 移植 2–5 项，补中文量词 |
| `hunt/ai/tailor.py` 的真实性规则 | Resume-Matcher `prompts/templates.py:CRITICAL_TRUTHFULNESS_RULES_TEMPLATE` | `e2a32b6` | Apache-2.0 | 译成中文并收紧 |
| `hunt/ai/tailor.py` 的岗位文本清理 | ai-job-search `tools/posting_guard.py`（零宽、tag 字符、双向控制符、指令句） | `0d0d1a9` | MIT | 只移植字符类和指令句部分，不移植 HTML 部分（岗位已经转成文本） |
| 审稿人 prompt 的输出结构 | ai-job-search `.claude/commands/apply.md` Step 3 Part A | `0d0d1a9` | MIT | 结构借用，内容自写 |
| `hunt/profile/claims.py` | career-ops `verify-cv-facts.mjs` | `c687a6f` | MIT | 只借断言类别和动词漂移的做法，代码不移植 |
| 版本与「基准」 | Reactive-Resume 补丁接口文档 | `ac22d62` | MIT | 思路 |
| 读回自检 | OpenResume `parse-resume-from-pdf` | `4f8255a` | AGPL-3.0 | 只当思路，不看更多代码，不移植 |
| 动效 | 本仓库 `rewoven:static/spider.js` | `4fb0e4b` | 自有，见 2.2 的授权提示 | 作为可选效果取回；只取 `spider.js`，不取 `rewoven.js` 里的写死编辑 |

不移植的：Resume-Matcher 的 `jd_added` 路径、`inject_keywords`、`heavy` 档；career-ops 的摘要注入；ai-job-search 的打分和联网研究。

## 12. 实施拆分

四个任务，文件范围互不重叠，都依赖第 4 节的数据结构作为共同合同。任务 4 最后合并。

**任务 1：核心与规则路径**
- 文件：`hunt/profile/tailor.py`、`tests/test_tailor.py`、`tests/fixtures/tailor/*`、`THIRD_PARTY_NOTICES.md`（本任务负责写全部条目）
- 内容：版面建议与校验（`suggest_layout`、`validate_layout`）、规则路径五步、`apply_edits`、`check_result`、`trace`、同义词白名单
- 完成标准：合成简历夹具上，建议版面在夹具上与手工标注一致，`validate_layout` 拒绝重复引用和不存在的事实；规则路径生成的修改应用后 `trace` 通过；`apply_edits` 拒绝四类越权修改；`test_dependencies` 通过

**任务 2：导出与读回自检**
- 文件：`hunt/profile/resume_render.py`、`tests/test_resume_render.py`
- 内容：输入「渲染结构」（章节、行、行对应的事实 id），写 Markdown / PDF / DOCX / `trace.json`；`check_export` 读回检查
- 完成标准：三种格式写出后，`intake` 读回的行与渲染行一致；故意打乱阅读顺序或换掉字体时，检查能报出来；缺字体给出明确错误

**任务 3：AI 路径与事实核对**
- 文件：`hunt/profile/claims.py`、`hunt/ai/tailor.py`、`tests/test_claims.py`、`tests/test_ai_tailor.py`（用现有 `tests/test_llm.py` 的假 transport）
- 内容：6.3 的六项检查；起草者、审稿人、prompt、清理、缓存、预算
- 完成标准：对一组「加词 / 加数字 / 升级动词 / 抄岗位 / 注入句」的恶意模型输出，全部被拒；合法同义改写通过；无同意、无密钥、超预算时不发请求

**任务 4：Store、CLI、接口文档、前端**
- 文件：`hunt/app/tailor.py`、`hunt/app/store.py`（只加 mixin 和 `ACTIONS` 条目）、`hunt/app/cli.py`、`static/js/tailor/*`、`static/js/job/page.js`（只加入口按钮）、`static/style.css`、`docs/agent-mode.md`、`tests/test_frontend.cjs`、字体子集
- 内容：SQLite 表、`layout` 存取、五个动作、导出目录、「整理结构」页、审核页、键盘操作
- 完成标准：`--demo` 下从岗位页走完「生成 → 逐条接受 → 导出 → 自检」；CLI 五个命令输出与 `agent-mode.md` 的结构一致；`node --test`、全量 `unittest`、`build_release.py --check` 通过
- 合并顺序：任务 1–3 合并后再合并，接口以任务 1–3 的实际签名为准

**第二阶段（单独立项）**：求职信（`hunt/ai/cover.py` 及 UI），Rewoven 动效（`static/js/tailor/effect.js`）。

## 13. 风险

- **版面整理增加一步操作。** 用户第一次用要手动核对条目；预填减轻负担，但简历越乱越费事。不确认就不能定制。最坏结果是用户嫌麻烦，不会引入新内容。
- **改写核对是启发式。** 6.3 挡得住加词、加数字、升级职责强度，挡不住否定变肯定等语义改动。缓解：AI 改写默认待审核，必须显示 before / after 和来源；审稿人只降级。不会声称「保证无编造」。
- **审稿人和起草者同一模型家族，错误可能相关。** 所以确定性检查才是依据，审稿人只是附加。
- **PDF 中文字体可移植性。** 当前靠系统字体或 `HUNT_PDF_FONT`，换机器可能缺。见第 14 节。
- **自检不等于真实 ATS。** 界面要明确写；只有 `intake` 一个解析器，对不同招聘系统的行为没有验证。
- **事实变化导致修改过期。** 用 `stale` 状态处理；若用户频繁改事实，会看到很多过期提示。
- **隐私。** `trace.json` 和导出文件含简历全文，放在 0700 目录；AI 路径发出的内容与 `job_match` 同级别，受同一份同意约束；设计文档和夹具只用合成资料。
- **花费。** 每次 AI 生成最多两次调用，按预算上限拦截；缓存避免重复点击。

## 14. 需要用户决定的问题

按影响从大到小：

1. 版面结构：已按你的选择定为方案 B（用户确认条目结构，程序只预填），见 4.3。
2. **改写的尺度。** 现在设计很保守：规则路径只换白名单里的同义词；AI 只能换成同义说法，不能加词。这会让多数简历的「改写」条数很少，主要价值在调序和缺口清单。你是否接受？如果希望 AI 更自由地重写句子，要先放宽 6.3 的第 1、4 项，风险随之上升，需要你明确同意。
3. **页数上限和隐藏。** 默认不限页数、不自动隐藏，只在你设了上限时才建议隐藏。是否合适？
4. **DOCX。** 用标准库手写最小 OOXML（不加依赖，版式简单），还是接受 `python-docx` 这个新依赖（版式更好）？
5. **PDF 字体。** 继续依赖系统字体加 `HUNT_PDF_FONT`，还是把一个开源授权的中文字体子集随仓库发布？后者要核对字体许可。
6. **英文简历。** 现在默认输出语言跟事实一致。岗位是英文、简历是中文时，是否需要「英文版」？按现有规则，AI 翻译会产生新文字，必须过同样的检查，工作量不小；建议放到 v3。
7. **求职信**放第二阶段是否可以？
8. **`spider.js` 的授权。** 它自述独立实现，上游无 LICENSE。你是否同意把它作为可选动效收回？不同意就只做静态审核页。
9. **自检的措辞。** 「不代表任何招聘系统」这样写够不够，还是希望更突出？
