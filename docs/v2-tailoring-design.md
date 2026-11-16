# v2 设计：为一个岗位定制简历

状态：第 14 节的问题用户已决定，未实现。证据和固定提交见 [research/v2-tailoring-sources.md](../research/v2-tailoring-sources.md)。

## 1. 结论

- 做什么：在岗位页加「为这个岗位改简历」，产出一份**只由已确认事实组成**的定制版简历，逐条审核，导出 PDF、DOCX、Markdown，并用本工具自己的解析器把导出文件读回来检查。
- 怎么保证不编造：定制版不是一份新写的文字，而是**原始事实上的一串修改**。每条修改写明引用哪些事实（id 和版本）、服务哪一条岗位要求。不引用事实的文字不能进入导出文件。
- 不用模型也能用：规则路径只做三件事：同一职责内按相关度调序、同义词换成岗位原词（限一张很短的白名单）、列出缺口。AI 路径在这之上允许重写句子：改句式、调语序、合并或拆句、换成岗位原文的说法。事实里没有的数字、工具名、雇主学校项目名、职位、奖项证书一律被本地检查拒绝，审核放行不了；职责强度升级和否定变肯定标红，默认待审核。
- 复用方式：按已定的决定，不用别的语言重写。MIT / Apache-2.0 的做法用 Python 移植并署名；非商用许可只当思路。实际能直接搬的**代码很少**，主要搬的是门槛的设计：Resume-Matcher 的修改应用闸门和校验（Apache-2.0）、ai-job-search 的审稿人分工和岗位文本扫描（MIT）。
- 最大风险：现有「事实」是简历按段落切出来的一行行文字，没有「公司 / 职位 / 时间 / 要点」的结构。调序和删减需要条目结构。已定方案：确认事实时规则预填，用户纠正，存成「简历结构」，之后每个岗位复用（第 4.3 节）。

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

`spider.js` 是本仓库自己的重写实现，只借鉴了上游 `web-crawlers` 的思路；上游树里没找到 LICENSE，所以不带入上游任何代码。已决定作为第二阶段的可选动效。

## 3. 不变的规则与本设计加的硬规则

沿用 AGENTS.md：只用已确认的事实；AI 不补写经历；不打分、不预测；发送内容前要有同意记录并计入预算；岗位原文是不可信输入；工作台冻结，真实提交额度保持 0。

本设计新增：

1. 导出文件里每一行，要么与某条已确认事实逐字相同，要么带一条已接受的修改，并且修改引用的事实仍是已确认且版本未变。导出前由 `trace()` 检查，不通过就不写文件。
2. 岗位里有、事实里没有的词，不会进入简历。缺口只列在侧栏，由用户决定要不要「补充事实」，走现有的确认流程。
3. 不新写摘要、自我评价、「求职意向」。只有用户自己确认过的摘要类事实才会出现。
4. 模型只能提议修改，不能直接改简历。它的输出必须通过本地硬检查才会出现在审核界面；通过了也默认「待审核」，不会自动进入导出。
5. 硬检查（6.3）拒绝的内容，审核界面没有「接受」按钮，用户也放行不了：事实里没有的数字和量化、工具和技术名、雇主、学校、项目名、职位或头衔、奖项和证书。要放行只有一条路：先把这一项补充为已确认事实。
6. 软检查（6.3）命中的内容标红，默认待审核：职责强度升级、否定变肯定。
7. 导出只写本机文件，不发送、不投递。

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
  "structure": {"version": 4},
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
  "after": "修改后的文字（rephrase 可为多行，对应拆句）；reorder 为新顺序，hide 为 null",
  "why": "一句话，规则路径由程序填，AI 路径取模型的 why",
  "by": "rules | ai",
  "status": "accepted | pending | rejected | stale",
  "checks": {"hard": "pass", "flags": ["strength_up", "negation_dropped", "close_to_jd"], "reviewer": "ok | unsupported | overstated | off_topic | null"}
}
```

`Gap`：`{type: absent | related | hard_not_met | hard_unknown, requirement, jd_evidence, related_terms, fact_ids}`。直接来自 `job_match` 的 `keywords[coverage != explicit]` 和 `hard[status != met]`，不另算。

`requirement.ref` 对应 `job_match` 返回行的序号（`k3` 是 `keywords[3]`，`d1` 是 `evidence[1]`，`h0` 是 `hard[0]`）。`match_digest` 是这些行的哈希，岗位结构或事实变了就能发现修改已过期。

### 4.2 版本

- 每个岗位一串版本，从 1 起，只增不改。重新生成得到 v+1；用户在审核界面的接受和撤销是**同一版本内**的状态变化。
- 一条修改引用的事实被改过（`version` 变了）或不再是已确认状态，这条修改变为 `stale`，不进导出，界面提示「事实已变，需重新审核」。借自 Reactive-Resume 的 `expectedUpdatedAt`。
- 导出时记下当时的版本号和文件哈希，文件名带版本：`<公司>-<岗位>-v3.pdf`。

### 4.3 简历结构：确认事实时预填，用户纠正

事实是 `intake.analyze_resume` 按段落切出的行，每行带 `source.reference = upload://<sha>#page=1&paragraph=12`，没有条目结构。调序和隐藏需要知道「哪些行属于同一段经历」，所以结构在**确认事实这一步**一次性建立，之后每个岗位的定制都复用，定制页和审核页不再还原结构。

**数据。** 「简历结构」与 `facts` 分开存（Store 的 meta 表，键 `resume_structure`），所以事实本身不动：

```json
{"version": 4, "status": "prefilled | confirmed", "confirmed_at": "…",
 "facts_digest": "…",
 "sections": [{"id": "s1", "key": "work", "title_fact": {"id": "intake-…", "version": 2},
   "entries": [{"id": "n3", "status": "ok | stale",
     "head": {"id": "intake-…", "version": 2},
     "fields": {"company": {"span": [0, 6], "confidence": "ok"},
                "title": {"span": [8, 14], "confidence": "uncertain"},
                "start": {"span": [16, 23], "confidence": "ok"},
                "end": {"span": [24, 26], "confidence": "ok"}},
     "bullets": [{"id": "intake-…", "version": 2}]}]}],
 "unassigned": [{"id": "intake-…", "version": 2}]}
```

要点：
- 每个条目引用条目头事实和其下要点行的 **事实 id + 版本**，不含自己写的文字。
- 公司、职位、起止时间是条目头事实原文里的**片段位置**（`span`），不是另存的文字。用户纠正时只能在原文里重新选片段，或者留空，不能自由输入新文字，所以结构本身也不会引入原文里没有的内容。
- `confidence` 记录规则对每个字段有多大把握，`uncertain` 的字段在界面高亮。
- 没被放进任何条目的已确认事实进 `unassigned`，不进定制版。

**预填规则**（`hunt/profile/structure.py` 的 `build`）：
1. 章节标题：整行短（≤12 字）且命中章节词（教育、工作经历、项目经历、专业技能、证书、自我评价等）。思路来自 OpenResume 的「整行是章节标题」，规则自己写。
2. 条目头：章节内含日期区间的行（`2021.07–2023.03`、`2021年7月至今`）。从中切出起止时间；剩下的片段里，带公司后缀（公司、集团、有限、大学等）的当公司，带职位后缀（工程师、经理等）的当职位。切不出来或有多种切法的字段标 `uncertain`。
3. 要点：条目头到下一个条目头之间的行。
4. 章节里没有日期行、行序被多栏 PDF 打乱的：整个章节建成一个条目，字段全部标 `uncertain`，提示用户核对。

**确认页上的界面**（见 12 节任务「简历结构」）：用户勾选要用的事实后，页面展示预填结构：章节、条目、条目头里切出的四个字段、要点行。每个条目可逐条确认或纠正（改片段、把行移到别的条目、拆分或合并条目）；`uncertain` 字段高亮，未处理完不能点「确认结构」。确认后 `status = confirmed`，`version + 1`。

**版本与过期。**
- 结构版本每次确认加一。定制版记录它所用的 `structure.version`。
- 条目里引用的事实 `version` 变了：该条目变 `stale`，字段回到 `uncertain`。引用的事实被取消确认或删除：该引用移除，条目标 `stale`。
- 新增的已确认事实不在结构里：进 `unassigned`，页面提示补一步。
- 有 `stale` 条目或 `unassigned` 事实时，定制页顶部提示「简历结构需要核对」并链到确认页。定制仍可进行：`stale` 条目按原文原顺序放进定制版，不调序、不隐藏、不改写；`unassigned` 的事实不进定制版。结构出错一律回确认页改，审核页里不改结构。

**旧数据迁移。** 已经确认过事实、还没有结构的候选人：第一次打开定制页或确认页时，程序调用 `build` 得到预填结构（`status = prefilled`，不会自动当作已确认），并引导到确认页的结构步骤。迁移不改任何事实。

**使用规则。** 调序只在一个条目内部发生，条目之间的顺序不动（经历保持新到旧，career-ops 也强制这一点）。条目头行不参与调序和隐藏。

### 4.4 放在哪一层

不新增层，`tests/test_dependencies.py` 不用改：

| 文件 | 层 | 内容 | 允许的依赖 |
|---|---|---|---|
| `hunt/profile/structure.py` | profile | 简历结构：`build` 预填、`validate`、`mark_stale`、`migrate` | 标准库 |
| `hunt/profile/tailor.py` | profile | 规则路径、`apply_edits`、`trace`；把结构当作参数读，不导入 `structure` | 标准库 |
| `hunt/profile/resume_render.py` | profile | Markdown / PDF / DOCX 写出、读回检查 | `profile.intake`、reportlab、pypdf |
| `hunt/profile/claims.py` | profile | 改写后文字的事实核对（见 6.3） | 标准库 |
| `hunt/ai/tailor.py` | ai | 起草者、审稿人、prompt、缓存 | `ai.llm`、`ai.orient`、`profile.*` |
| `hunt/app/tailor.py` | app | Store 的 `TailorActions`、SQLite 表、导出目录、CLI | 所有层 |
| `static/js/tailor/` | 前端 | 审核页 | `shared/` |

规则路径要用 `job_match` 的结果，但 profile 层不能导入 `ai.match`。解决：`profile.tailor` 的函数把 `match` 的返回值作为**参数**接收，不导入；由 app 层把两边接起来。同义词白名单（5.1）放在 profile 层，不依赖 `match.RELATED`，因为 `RELATED` 把「相近」和「同义」混在一起（`TypeScript` 与 `JavaScript`、`深度学习` 与 `机器学习`），不能拿来改写。

存储：Store 的 SQLite 加一张表 `tailored(id TEXT PRIMARY KEY, job_id TEXT, version INTEGER, data TEXT, created TEXT, UNIQUE(job_id, version))`。不碰工作台的 `packages` 表，不复用 `hunt/workbench/export.py`（冻结）。导出文件放 `<data>/tailored/<job_id>/v<N>/`，目录 0700、文件 0600，沿用 `export.write_package` 的做法。

## 5. 生成

### 5.1 规则路径（不用模型）

输入：已确认事实、已确认的简历结构（4.3）、`job_match` 的结果。输出：一组 `by: "rules"` 的修改和缺口。

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

prompt 规则取自 Resume-Matcher 的真实性规则，译成中文并按我们的规则调整：不加事实里没有的数字、工具和技术名、雇主、学校、项目名、职位、奖项、证书；不升级职责强度，不把否定改成肯定；不改日期；可以改句式、调语序、合并相邻几条事实为一句、把一条拆成几句，可以换成岗位原文里的说法，但只能用在事实已经支持的内容上；岗位有而事实没有的词一律不用；每条改写列出引用的全部事实；没有可改的就返回空列表。

**审稿人。** 第二次调用，换一份 prompt，输入是通过了本地检查的修改、事实原文、岗位要求引用。每条返回 `ok | unsupported | overstated | off_topic` 和一句话，特别要看语义有没有被改（强度、否定、因果、范围）。审稿人**只能降级，不能改文字**（对应 ai-job-search 里审稿人没有编辑权限）。非 `ok` 的修改仍显示，带红色标记。

**预算。** 起草者 + 审稿人共 2 次调用，用现有 `Meter` 和 `chat_json`；每次调用前按最坏情况（`Meter.projected`）检查，超出本轮上限就不调用。界面点击前显示：「将向 <host> / <model> 发送 N 条已确认事实和 M 条岗位要求，最坏花费约 ¥x」。结果按 `(jd_digest, 事实摘要, 模型, prompt 版本)` 缓存，重复点击不再花钱（与 `jd_extract` 的缓存同一做法）。

**失败。** 无同意、无密钥、预算不足、模型输出不合格：回退为只有规则路径的结果，并在界面写明原因，不静默。

## 6. 事实核对（两条路径共用）

### 6.1 应用修改

`apply_edits(facts, structure, edits)` 逐条过四道闸，移植自 Resume-Matcher 的 `apply_diffs`：

1. 操作在允许集合内（`reorder / hide / alias / rephrase`），目标是已确认事实。
2. 不碰身份行：姓名、联系方式、公司名、学校、学位、日期所在的行不允许 `rephrase`，只允许 reorder 和 hide（黑名单思路来自 `_BLOCKED_FIELD_NAMES`）。
3. `before` 与事实原文逐字相等（NFKC 折叠后比较）。
4. `reorder` 的新顺序必须与原集合相同；`hide` 不能把一个块隐藏到没有头。

不过的进 `rejected_by_gate`，界面可展开看，不丢。

### 6.2 事后检查

移植 `verify_diff_result` 的第 2–5 项，逐版本检查：块数不变；身份行不变；单行改写后字数不超过原行的 1.5 倍；新出现的数字和量词。中文的量词要补：`%`、`倍`、`万`、`亿`、`个月`、`年`、`人`、`家`、`次`，以及 `\d+[+＋]`。

### 6.3 改写核对（AI 的 `rephrase` 专用，`profile/claims.py`）

AI 可以重写句子，所以不再比对「字面重合度」，改为按断言类别核对：`after` 里出现的每一类断言，都要能在它引用的事实里找到。断言类别参考 career-ops `verify-cv-facts.mjs`（数字、工具、雇主、奖项等），中文规则自己写。

**硬闸门（一律拒绝，审核放行不了，进 `rejected_by_gate`）**

| 类别 | 检测 | 拒绝条件 |
|---|---|---|
| 数字与量化 | 阿拉伯数字、中文数字加量词、`%`、倍、万、亿、个月、年、人、家、次、第几名、Top N、`N+` | 出现在 `after`，而不在引用事实里 |
| 工具与技术名 | 拉丁词（含 `+ # .`、驼峰）；一张中文工具词表（来自 `profile._SKILLS`、`match.RELATED` 和方向表里的词） | 出现在 `after`，而不在引用事实里；与事实里的词在同义白名单中等价、且正是该条要求的关键词的除外 |
| 雇主、学校、项目名 | 以公司、集团、有限、大学、学院、研究院、实验室、项目、平台等收尾的片段；书名号和引号里的名称 | 不在引用事实里 |
| 职位或头衔 | 以工程师、经理、总监、主管、专员、负责人、架构师、设计师、分析师、顾问、实习生等收尾的片段 | 不在引用事实里 |
| 奖项与证书 | 含奖、证书、认证、奖学金、荣誉、专利、论文的片段；常见证书名（PMP、CPA、六级等） | 不在引用事实里 |
| 新载体 | 链接、邮箱、手机号 | 一律拒绝 |

另外：`after` 为空、引用的事实不存在或已过期，也拒绝。身份行（姓名、联系方式、公司、学校、学位、日期）本来就不允许 `rephrase`（6.1）。

「岗位有、事实没有的词不进简历」（第 3 节第 2 条）由上表的工具名、数字等类别和下面这条一起执行：`after` 里出现的岗位关键词，必须能在引用事实里找到，或在同义白名单里与事实中的词等价。

**软检查（标红，默认待审核，不拒绝）**

| 标记 | 检测 |
|---|---|
| `strength_up` 职责强度升级 | 开头动词等级上升：了解 < 参与 < 协助 < 负责 < 主导、牵头、带领（career-ops 的「动词漂移」）；`before` 没有强度动词而 `after` 有，也标 |
| `negation_dropped` 否定变肯定 | 事实里有没有、不、未、无、非、缺乏、仅，`after` 对应位置没有；或 `after` 的否定词少于引用事实 |
| `close_to_jd` 贴近岗位原句 | `after` 中连续 12 个字以上与岗位某一行相同。允许换成岗位说法，但提醒用户这句是不是只是抄了岗位 |

用户可以逐条换动词白名单（借鉴 `allow_swaps`，默认空），白名单里的换动词不标 `strength_up`。

**这套检查是启发式的。** 工具词表和名称后缀规则有漏网的可能（例如不在词表里的中文工具名、不带后缀的项目名）；强度和否定只看常见词。挡不住全部语义改动，例如因果被改、范围被放大、「做过」变成「精通」。兜底靠审核：每条 AI 改写都显示 before / after 和来源事实（第 7 节），默认待审核，不会自动进入导出。

## 7. 审核界面

入口：岗位页的匹配区下方加按钮「为这个岗位改简历」，路由 `#/job/<id>/tailor`。没有已确认事实时，页面只说明原因和去确认事实的链接。

### 7.1 布局

左右两栏，窄屏上下叠放：

- 左：已确认事实，按简历结构分章节和条目，原样显示。结构有错时，页面给一个链接回确认页改，审核页里不拖动、不改结构。
- 右：定制版，同样的章节和块。被修改的行显示逐字 diff（删除线和下划线）；hide 的行折叠成一行「已隐藏 1 条，展开」。
- 每条被修改的行下方一行：操作类型、`对应岗位要求：Kubernetes`（点开跳到岗位原文引用并高亮）、`来源：intake-…（第 1 页第 12 段）`（点开显示事实原文）、接受 / 撤销按钮。
- 右侧或下方一个窄栏「缺口」：未覆盖的关键词和未满足的硬条件，各带岗位引用和「补充事实」。没有分数、没有进度条。
- 底部：待审核条数、预检结果、导出按钮。有待审核修改时，导出按钮写「导出（不含 N 条待审核）」。

键盘：`j/k` 下一条/上一条修改，`a` 接受，`u` 撤销，借 Linear Triage「一个决定一个键」的做法（`AGENTS.md` 里的标杆）。

AI 改写显示 before / after 和引用的事实，软检查命中的标红并写明原因（职责强度升级、否定变肯定、贴近岗位原句）。被硬闸门拒绝的提议（`rejected_by_gate`）折叠在页面底部，写明被拒的类别和具体片段，没有「接受」按钮；用户想要这个内容时，入口是「补充事实」。

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
- **PDF**：reportlab（已是依赖）。单栏、纯文本层、不用图标和标签栏、页眉页脚不放正文。中文用随仓库发布的字体子集（见 8.3）；`HUNT_PDF_FONT` 指定的字体优先，其次系统字体，都没有才用内置子集。
- **DOCX**：用 `python-docx`（见 8.4）写段落和标题，样式只用内置样式。`intake` 已能读 DOCX，往返可测。
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

### 8.3 随仓库的 PDF 字体

- 字体：Noto Sans SC（SIL OFL 1.1，上游 google/fonts 的 `ofl/notosanssc`；仓库里已有 `static/fonts/OFL-notosanssc.txt`），子集为 GB2312 的 6763 个汉字，加 ASCII、全角标点和常用符号。汉字表由 Python 标准库的 `gb2312` 编码生成，不另存清单。
- 单一字重（400），标题靠字号区分，不另带粗体，体积减半。上游是可变字体，用 `fonttools` 的 instancer 固定到 `wght=400` 并输出 TrueType（reportlab 只能嵌入 TrueType 轮廓）。
- 位置：`hunt/data/fonts/NotoSansSC-GB2312.ttf` 和 OFL 文本。不放进 `static/fonts/`，也不计入界面字体的体积。
- 体积预算：单独算，上限 3 MB（推测值：6763 字单字重的 TrueType 子集大约 1.5–3 MB，未测量）。任务 2 先测，超限就收窄符号集；仍超限再回到用户商量。界面字体子集现在是 232 KB（已验证：`static/fonts` 目录实测），与这一项无关。
- 生成脚本：`scripts/build_pdf_font.sh`，调用 `prototypes/_tools/` 下的子集工具或在 `scripts/` 下新增一个 Python 脚本；源字体不进仓库，下载方式和哈希写在脚本头，沿用 `build_fonts.sh` 的做法。`fonttools` 只在运行脚本时需要，不进运行时依赖。
- 缺字：写出 PDF 前先用字体的 cmap 检查每个字。子集里没有的字（GB2312 之外的生僻字、繁体字、emoji）列出来，写进自检结果和界面提示：「这些字不在内置字体里：…。请用 `HUNT_PDF_FONT` 指定完整字体后重新导出。」不静默画成空格或方块。

### 8.4 `python-docx`

- 许可 MIT；当前版本 1.2.0，要求 Python ≥3.9（已验证：PyPI 元数据）。
- 包本身是纯 Python 的 wheel（`py3-none-any`），但它依赖 `lxml`（含 C 扩展）和 `typing_extensions`。所以**依赖链不是纯 Python**：`lxml` 在常见平台有预编译 wheel，冷门平台要本地编译。这是新增依赖的代价，写在 `setup.sh` 失败时的提示里。
- 写进 `requirements.txt`（固定版本，与现有写法一致）之前，任务 2 要核对 `lxml` 和 `typing_extensions` 的许可证与固定版本，并在 `THIRD_PARTY_NOTICES.md` 登记 python-docx、lxml、typing_extensions 和字体（Noto Sans SC，OFL）。
- 导入放在导出函数里（惰性导入）；没装时只影响 DOCX，给出明确提示，不影响 PDF 和 Markdown。

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
| `hunt structure [--set FILE]` | `structure_get` / `structure_save` | 读取预填或已确认的简历结构；保存用户确认的结构（任务 0） |
| `hunt tailor JOB_ID [--ai]` | `tailor` | 生成新版本，返回完整结构 |
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
| `hunt/profile/claims.py` | career-ops `verify-cv-facts.mjs` | `c687a6f` | MIT | 只借断言类别（数字、工具、雇主、奖项）和动词漂移的做法，中文规则自己写，代码不移植 |
| 版本与「基准」 | Reactive-Resume 补丁接口文档 | `ac22d62` | MIT | 思路 |
| 读回自检 | OpenResume `parse-resume-from-pdf` | `4f8255a` | AGPL-3.0 | 只当思路，不看更多代码，不移植 |
| 动效（第二阶段） | 本仓库 `rewoven:static/spider.js` | `4fb0e4b` | 自有的重写实现 | 只取我们自己写的 `spider.js`，不带入上游 `web-crawlers` 的任何代码；不取 `rewoven.js` 里的写死编辑 |
| DOCX 写出 | python-docx | 1.2.0（PyPI） | MIT | 作为依赖安装，不复制源码；在 `THIRD_PARTY_NOTICES.md` 登记 |
| PDF 中文字体 | Noto Sans SC（google/fonts `ofl/notosanssc`） | 以脚本头记录的哈希为准 | OFL 1.1 | 子集后随仓库发布，附 OFL 文本；子集即衍生字体，需遵守 OFL 的命名规则（子集不使用保留字体名时按 OFL 要求改名，任务 2 核对） |

不移植的：Resume-Matcher 的 `jd_added` 路径、`inject_keywords`、`heavy` 档；career-ops 的摘要注入；ai-job-search 的打分和联网研究。

## 12. 实施拆分

五个任务，文件范围互不重叠（`THIRD_PARTY_NOTICES.md` 只由任务 1 修改），都依赖第 4 节的数据结构作为共同合同，其中结构的 JSON（4.3）是任务 0 与任务 1 之间的合同。

**并行与合并顺序**
- 可同时开工：任务 0 的 profile 部分（`structure.py`）、任务 1、任务 2、任务 3。它们只通过 JSON 合同和夹具对接，互不导入。
- 任务 0 的界面和 Store 部分与上面几个也不冲突，但要改 `store.py`、`workbench/resume.js` 和前端测试，先于任务 4 合并。
- 合并顺序：任务 0、1、2、3 任意先后 → 任务 4 最后（它要读结构、调规则路径和 AI 路径，并在 `store.py`、`cli.py`、`style.css` 上接在任务 0 之后，避免冲突）。

**任务 0：简历结构**
- 文件：`hunt/profile/structure.py`、`hunt/app/structure.py`（Store 的结构存取和迁移，`StructureActions`）、`static/js/resume/structure.js`（确认页上的预填与纠正界面）、`static/js/workbench/resume.js`（只加一处挂载调用，见 14 节待确认）、`tests/test_structure.py`、`tests/fixtures/structure/*`、`tests/test_frontend.cjs`（只加结构相关用例）、字体子集（新增固定中文后重生成）
- 内容：`build` 预填、`validate`、`mark_stale`、`migrate`；动作 `structure_get`、`structure_save`；确认页上的章节、条目、字段高亮与逐条确认；旧数据第一次使用时的预填迁移
- 完成标准：合成简历夹具上 `build` 与手工标注的章节、条目、公司、职位、起止时间一致，拿不准的字段标 `uncertain`；`validate` 拒绝重复引用、不存在的事实、越界的 `span`；事实版本变化后 `mark_stale` 正确标记；已有确认事实且没有结构的候选人，第一次使用得到预填而不是已确认；`--demo` 下能走完预填、纠正、确认；`test_dependencies` 通过
- 与其他任务的关系：任务 1 读取结构，但只依赖 4.3 的 JSON 合同；`structure.py` 与任务 1、2、3 互不导入，可并行。

**任务 1：核心与规则路径**
- 文件：`hunt/profile/tailor.py`、`tests/test_tailor.py`、`tests/fixtures/tailor/*`、`THIRD_PARTY_NOTICES.md`（本任务负责写全部条目）
- 内容：规则路径五步（读取已确认的结构，结构以 4.3 的 JSON 为合同，开发时用夹具里的结构文件，不导入 `structure`）、`apply_edits`、`check_result`、`trace`、同义词白名单
- 完成标准：合成简历夹具上，`stale` 条目原样通过、不被调序；规则路径生成的修改应用后 `trace` 通过；`apply_edits` 拒绝四类越权修改；`test_dependencies` 通过

**任务 2：导出、字体与读回自检**
- 文件：`hunt/profile/resume_render.py`、`hunt/data/fonts/*`（字体子集和 OFL 文本）、`scripts/build_pdf_font.sh`（及它调用的 Python 脚本）、`tests/test_resume_render.py`、`requirements.txt`、`setup.sh`（只加依赖失败提示）
- 内容：输入「渲染结构」（章节、行、行对应的事实 id），写 Markdown / PDF / DOCX（`python-docx`）/ `trace.json`；`check_export` 读回检查；字体子集的生成脚本与缺字检查；核对并登记 `python-docx`、`lxml`、`typing_extensions`、字体的许可证（`THIRD_PARTY_NOTICES.md` 由任务 1 统一写，本任务把条目内容交给任务 1 的负责人，或在合并时补齐，不并行改同一个文件）
- 完成标准：三种格式写出后，`intake` 读回的行与渲染行一致；故意打乱阅读顺序时，检查能报出来；GB2312 全部 6763 字在子集里都能渲染；一个 GB2312 之外的字（如「𠮷」）会被自检列出并提示 `HUNT_PDF_FONT`；字体子集体积实测写进文档，超过 3 MB 上限时任务不通过；没装 `python-docx` 时 DOCX 给出明确提示、其余格式照常

**任务 3：AI 路径与事实核对**
- 文件：`hunt/profile/claims.py`、`hunt/ai/tailor.py`、`tests/test_claims.py`、`tests/test_ai_tailor.py`（用现有 `tests/test_llm.py` 的假 transport）
- 内容：6.3 的硬闸门和软检查；起草者、审稿人、prompt、清理、缓存、预算
- 完成标准：
  - 每一类硬闸门各造一个模型输出，全部被拒：新数字或量化、新工具名、新雇主、新学校、新项目名、新职位、新奖项、新证书、新联系方式。
  - 每个软检查各造一个输出：职责强度升级和否定变肯定被标红且状态为待审核，不被拒绝。
  - 合法改写全部通过：改句式、调语序、合并两条事实为一句、拆句、换成岗位原文的说法（该词事实已支持）。
  - 岗位有而事实没有的词：被拒。
  - 注入句（岗位文本里的指令）不改变输出范围；无同意、无密钥、超预算时不发请求。

**任务 4：Store、CLI、接口文档、前端**
- 文件：`hunt/app/tailor.py`、`hunt/app/store.py`（只加 mixin 和 `ACTIONS` 条目）、`hunt/app/cli.py`、`static/js/tailor/*`、`static/js/job/page.js`（只加入口按钮）、`static/style.css`、`docs/agent-mode.md`、`tests/test_frontend.cjs`、字体子集
- 内容：SQLite 表、四个动作（`tailor`、`tailor_get`、`tailor_review`、`tailor_export`）、导出目录、审核页、键盘操作、结构未确认或过期时的提示和跳转
- 完成标准：`--demo` 下从岗位页走完「生成 → 逐条接受 → 导出 → 自检」；CLI 命令输出与 `agent-mode.md` 的结构一致；`node --test`、全量 `unittest`、`build_release.py --check` 通过
- 合并顺序：任务 0–3 合并后再合并，接口以它们的实际签名为准；在 `store.py`、`cli.py`、`style.css` 上基于任务 0 的结果

**第二阶段（单独立项）**：求职信（`hunt/ai/cover.py` 及 UI），Rewoven 动效（`static/js/tailor/effect.js`）。

## 13. 风险

- **预填错了而用户没注意。** 结构预填由规则得到，条目头和字段切分会错（行序、多栏 PDF、没有日期的经历）；用户一路点确认可能漏看。缓解：拿不准的字段高亮，存在高亮字段时不能点「确认结构」；字段只能选原文片段，不能自由输入，所以错也只是切错位置，不会引入原文没有的内容；事实变化后条目自动标过期。最坏结果是调序或隐藏落在错的条目上。
- **AI 可以重写句子，核对是启发式。** 硬闸门按断言类别查，漏网的有：不在词表里的中文工具名、不带后缀的项目名、因果或范围的改动（「参与过」变「搭建了」之外的细微变化、「做过」变「精通」）。强度和否定只看常见词。挡不住全部语义改动，靠审核兜底：每条 AI 改写显示 before / after 和来源，默认待审核，软检查命中的标红。我们不会声称「保证无编造」。放宽改写后，用户逐条看的工作量和判断责任比保守方案更大。
- **审稿人和起草者同一模型家族，错误可能相关。** 所以确定性检查才是依据，审稿人只是附加。
- **PDF 字体覆盖。** GB2312 之外的字（生僻字、繁体、emoji）不在内置子集里，自检会报出并提示用 `HUNT_PDF_FONT`；体积上限 3 MB 是推测值，任务 2 要实测。
- **新依赖。** `python-docx` 带来 `lxml`，依赖链不是纯 Python。
- **自检不等于真实 ATS。** 界面要明确写；只有 `intake` 一个解析器，对不同招聘系统的行为没有验证。
- **事实变化导致修改过期。** 用 `stale` 状态处理；若用户频繁改事实，会看到很多过期提示。
- **隐私。** `trace.json` 和导出文件含简历全文，放在 0700 目录；AI 路径发出的内容与 `job_match` 同级别，受同一份同意约束；设计文档和夹具只用合成资料。
- **花费。** 每次 AI 生成最多两次调用，按预算上限拦截；缓存避免重复点击。

## 14. 已决定的问题和剩余问题

已决定（用户）：

1. 简历结构：方案 C，确认事实时规则预填、用户纠正，存成「简历结构」后每个岗位复用（4.3）。
2. 改写尺度：放宽，允许 AI 重写句子；硬闸门不可放行，软检查标红，全部默认待审核（6.3）。
3. DOCX：加 `python-docx`（8.4）。
4. PDF 字体：随仓库发布 Noto Sans SC 的 GB2312 子集，体积单独预算（8.3）。
5. 不限页数、不自动隐藏；英文简历放 v3；求职信放第二阶段；`spider.js` 作第二阶段的可选动效，只用我们自己的重写；自检措辞按本文 8.2。

剩余待确认：

0. **确认页在冻结目录里。** 确认事实的界面是 `static/js/workbench/resume.js`，后端是 `hunt/app/candidate.py` 的 `confirm_resume`，位于被冻结的工作台范围（只修 bug，不加功能）。设计里结构界面放在新模块 `static/js/resume/structure.js`，在 `resume.js` 里只加一处挂载调用，后端放在新的 `hunt/app/structure.py`，不改 `confirm_resume`。是否允许这一处改动？这是开工前要定的；不允许就只能把结构步骤放在定制页里，那就回到「在审核时才建结构」。

实现时处理，不阻塞开工：

1. 字体子集的实际体积是否在 3 MB 内（任务 2 实测）。
2. `lxml` 的固定版本与许可证核对结果（任务 2）。
3. 中文工具词表的来源与维护方式：初版由现有三张表合并，是否需要用户可扩展。
4. 6.3 里软检查的词表（强度动词、否定词）是否够用，用合成夹具调。
