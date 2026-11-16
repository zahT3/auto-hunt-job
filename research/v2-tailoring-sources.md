# v2 简历定制：调研来源

调研时间 2026-11-16。方法：浅克隆或 `gh api` 取文件，只读源码，没有运行任何一个项目的代码。克隆在 `~/Developer/_Bench/v2-tailoring-research/`（不进 git）。设计文档见 [docs/v2-tailoring-design.md](../docs/v2-tailoring-design.md)。

许可证取自各仓库 LICENSE 文件首部或 GitHub API 的 `license.spdx_id`。星标数没有核对，不写。

## 1. ai-job-search-dev/ai-job-search

- 许可：MIT（LICENSE，版权人 Mads Lorentzen）
- 固定提交：`0d0d1a907a21454affa1b694acc4e2c5008a0d21`
- 读了：
  - [`.claude/commands/apply.md`](https://github.com/ai-job-search-dev/ai-job-search/blob/0d0d1a907a21454affa1b694acc4e2c5008a0d21/.claude/commands/apply.md)：Step 0 取岗位并把岗位当不可信数据；Step 1 适配评估；Step 2 起草；Step 3 审稿人（固定 prompt，返回 Part A 结构化 edits 与 Part B 叙述建议，每条 edit 带 `reason`，事实不符的标 `grounding`）；Step 4 起草者应用；Step 5d 对 PDF 文字层做关键词覆盖表（covered / synonym-only / missing(have it) / missing(gap)）。
  - [`.claude/agents/application-reviewer.md`](https://github.com/ai-job-search-dev/ai-job-search/blob/0d0d1a907a21454affa1b694acc4e2c5008a0d21/.claude/agents/application-reviewer.md)：审稿人只有读和查的工具，没有编辑和写文件的工具。
  - [`tools/posting_guard.py`](https://github.com/ai-job-search-dev/ai-job-search/blob/0d0d1a907a21454affa1b694acc4e2c5008a0d21/tools/posting_guard.py)：岗位文本进入流程前的确定性扫描（隐藏 HTML、零宽字符、Unicode tag 字符、面向 agent 的指令句、混合文字的仿冒词）。
  - [`tools/verify_pdf.py`](https://github.com/ai-job-search-dev/ai-job-search/blob/0d0d1a907a21454affa1b694acc4e2c5008a0d21/tools/verify_pdf.py)：导出 PDF 后重新抽取文字层、查页数、查乱码和日期。
  - [`.claude/skills/job-application-assistant/05-cv-templates.md`](https://github.com/ai-job-search-dev/ai-job-search/blob/0d0d1a907a21454affa1b694acc4e2c5008a0d21/.claude/skills/job-application-assistant/05-cv-templates.md)：「ATS Parseability」与「Relevance-weighted cutting」两节。
- 没读：`verify_layout.py`、`security_guards.py`、求职信模板的正文。

## 2. career-ops-hq/career-ops

- 许可：MIT（版权人 Santiago Fernández de Valderrama）
- 固定提交：`c687a6f89aa766de468d41402df1ce24bdd86315`
- 读了：
  - [`modes/pdf.md`](https://github.com/career-ops-hq/career-ops/blob/c687a6f89aa766de468d41402df1ce24bdd86315/modes/pdf.md)：定制流程步骤 4（技能缺口先查）、13、14（「Inject keywords naturally into existing achievements (NEVER invent)」）、17a（标题一致性）、19（事实闸门）、21a（ATS 变体）、22（关键词覆盖）。
  - [`modes/ats.md`](https://github.com/career-ops-hq/career-ops/blob/c687a6f89aa766de468d41402df1ce24bdd86315/modes/ats.md)：确定性、只读的 ATS 友好度检查，分「渲染前改 payload」和「渲染后查 HTML」两段。
  - [`jd-skill-gap.mjs`](https://github.com/career-ops-hq/career-ops/blob/c687a6f89aa766de468d41402df1ce24bdd86315/jd-skill-gap.mjs) 文件头：三类 existing / supportedByResume / gap，注明借鉴了 Resume-Matcher。
  - [`verify-cv-facts.mjs`](https://github.com/career-ops-hq/career-ops/blob/c687a6f89aa766de468d41402df1ce24bdd86315/verify-cv-facts.mjs)（4503 行）：只读了文件头和函数清单，没有逐行读。
  - [`lib/cv-payload-facts.mjs`](https://github.com/career-ops-hq/career-ops/blob/c687a6f89aa766de468d41402df1ce24bdd86315/lib/cv-payload-facts.mjs)、[`lib/cv-payload-schema.mjs`](https://github.com/career-ops-hq/career-ops/blob/c687a6f89aa766de468d41402df1ce24bdd86315/lib/cv-payload-schema.mjs)：渲染前的结构化记录与事实审计面。
- 没读：`generate-pdf.mjs`（2844 行）、`modes/cover.md`、`keyword-match.mjs`。

## 3. srbhr/Resume-Matcher

- 许可：Apache-2.0（LICENSE 首部）
- 固定提交：`e2a32b6823bb7f5996cafdf007b6ba6f0efd8f98`
- 读了（`apps/backend/app/` 下）：
  - [`services/improver.py`](https://github.com/srbhr/Resume-Matcher/blob/e2a32b6823bb7f5996cafdf007b6ba6f0efd8f98/apps/backend/app/services/improver.py)：`_ALLOWED_PATH_PATTERNS` / `_BLOCKED_FIELD_NAMES`（路径白名单与黑名单）、`apply_diffs`（四道闸）、`verify_diff_result`（段落数、身份字段、字数比 1.8、`_METRIC_RE` 新增数字）、`verify_skill_target_plan`（existing / jd_added / supported_by_resume / unsupported）、`_sanitize_user_input`（`_INJECTION_PATTERNS` 八条正则）。
  - [`prompts/templates.py`](https://github.com/srbhr/Resume-Matcher/blob/e2a32b6823bb7f5996cafdf007b6ba6f0efd8f98/apps/backend/app/prompts/templates.py)：`CRITICAL_TRUTHFULNESS_RULES_TEMPLATE`、按强度分的四档 prompt、`DIFF_IMPROVE_PROMPT`（输出 `changes[{path, action, original, value, reason}]`）。
  - [`services/refiner.py`](https://github.com/srbhr/Resume-Matcher/blob/e2a32b6823bb7f5996cafdf007b6ba6f0efd8f98/apps/backend/app/services/refiner.py) 的 `validate_master_alignment`、[`schemas/refinement.py`](https://github.com/srbhr/Resume-Matcher/blob/e2a32b6823bb7f5996cafdf007b6ba6f0efd8f98/apps/backend/app/schemas/refinement.py)。
- 没读：前端 diff 预览组件、`COVER_LETTER_PROMPT` 的正文、`inject_keywords` 的实现。

## 4. AmruthPillai/Reactive-Resume

- 许可：MIT（GitHub API 的 `spdx_id`；没有读 LICENSE 文件正文）
- 固定提交：`ac22d622d701bd114d97f11c99a5ce660c72a663`
- 读了：[`docs/guides/using-the-patch-api.mdx`](https://github.com/AmruthPillai/Reactive-Resume/blob/ac22d622d701bd114d97f11c99a5ce660c72a663/docs/guides/using-the-patch-api.mdx)（JSON Patch RFC 6902，`expectedUpdatedAt` 防覆盖）、[`docs/guides/tailoring-a-resume-for-a-job.mdx`](https://github.com/AmruthPillai/Reactive-Resume/blob/ac22d622d701bd114d97f11c99a5ce660c72a663/docs/guides/tailoring-a-resume-for-a-job.mdx)（为一个岗位复制一份简历，与该岗位绑定）。
- 没读：`packages/resume/src/patch.ts` 等源码、AI 助手的 prompt。只凭文档下结论的部分在设计文档里标了。

## 5. xitanggg/open-resume

- 许可：AGPL-3.0（GitHub API）。只能当思路，不复制代码。
- 固定提交：`4f8255a2c763479837f69f1dccf2a3338730cd79`
- 读了：[`src/app/lib/parse-resume-from-pdf/group-lines-into-sections.ts`](https://github.com/xitanggg/open-resume/blob/4f8255a2c763479837f69f1dccf2a3338730cd79/src/app/lib/parse-resume-from-pdf/group-lines-into-sections.ts)（用「整行是章节标题」这一规律把行归到章节）和 `parse-resume-from-pdf/` 的文件清单。
- 没读：其余解析器文件。

## 6. 本仓库 `rewoven` 分支

- 固定提交：`4fb0e4b60fe5500bf1c6d4b6dc5042591c10a375`
- 读了：`docs/rewoven.md`、`hunt/rewoven.py` 的函数清单、`static/rewoven.js`、`static/spider.js` 文件头。
- `spider.js` 文件头写明借鉴 `zahT3/web-crawlers`（上游 `cyohei9907/web-crawlers`），`docs/rewoven.md` 记录在上游树里没找到 LICENSE。

## 7. 没拿到的

- 没有核对任何项目的星标数。
- 没有运行任何项目；各项目的行为描述来自源码和文档，不是实测。
- Reactive-Resume 用 `git clone` 失败（连接超时），改用 `gh api` 只取了文档。
