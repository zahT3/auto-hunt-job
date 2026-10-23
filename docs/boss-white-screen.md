# BOSS 白屏调查与官网替代路径

核验日期：2026-10-23。仅搜索、读取与本地准备；未发送消息、上传简历或提交申请。

## 同类问题在哪里

- [boss-zhipin-scraper Issue #30](https://github.com/eatmoreduck/boss-zhipin-scraper/issues/30)：报告者在 Windows/CDP 环境下记录约 3–4 秒后跳转 about:blank，并见接口“环境异常”。这是第三方复现，不能证明所有 BOSS 白屏都由同一机制引起。
- [boss-agent Issue #1](https://github.com/Douyh123/boss-agent/issues/1)：建议连接用户手动登录的 Chrome；当前仍是建议，不能当作修复成功证据。
- [browser-harness 的 BOSS 搜索说明](https://github.com/browser-use/browser-harness/blob/main/agent-workspace/domain-skills/BOSS-zhipin/job-search.md)：记录了延迟空白跳转，同样不是本机诊断证据。

## 查看了哪些实现

| 项目 | 实际接入方式 | 本项目决定 |
| --- | --- | --- |
| [boss-zhipin-scraper](https://github.com/eatmoreduck/boss-zhipin-scraper) | MIT；独立 Chrome/Edge 资料目录、CDP、复用登录态读取平台接口 | 学习会话隔离与诊断；其 Issue 表明 CDP 本身并不保证免于白屏 |
| [BossHunter](https://github.com/shengjidaguai-china/BossHunter) | 用户自行启动并登录 Chrome，连接会话；区分采集、确认与执行 | 只参考流程；PolyForm Noncommercial，未复制代码进 MIT 项目 |
| [boss-agent](https://github.com/Douyh123/boss-agent) | Playwright 创建浏览器；代码包含浏览器属性模拟；CDP 改善方案是待处理 Issue | 没有采用其属性模拟，也没有将建议当作通过验收 |

研究只读取源码，没有运行这些项目、安装其脚本或导出用户 Cookie。对应研究快照的 tree SHA：boss-zhipin-scraper `b8076fceb9cb5e5e1ae28c155e8c1b894cfec7cc`，BossHunter `50bbbbe7e15932fa33b5f6b2969fae77ffa197e4`，boss-agent `2bb6a66f5a1415f85f926096c50d92f2bddc6226`。

## 本机已证实与尚未证实

此前 FlClash 实际连接显示 BOSS 主站与图片域名 DIRECT。TUN 当时仍开启，这不等于绕过整个 FlClash，也不能完全排除本地网络接管的影响。用户报告手动输入网址后可以登录；自动控制时标签页元数据、旧首页与 about:blank 出现不一致。尚未取得触发跳转的脚本调用证据，不能确定具体机制。

应用已修复一处独立问题：登录时不再在 Playwright 主线程阻塞等待终端输入，浏览器事件可继续处理。新增可选已安装 Google Chrome，使用独立于 Chromium 的资料目录；没有改变浏览器属性或禁用站点安全脚本。浏览器读取留出 4 秒观察 BOSS 延迟跳转，将空白、登录页、验证页分别报告并停止该渠道。

一次已安装 Chrome 的独立只读检查得到 9466 字节页面，地址包含 `_security_check`。这只证明收到页面，未证明得到岗位列表、登录有效或稳定采集。真实 BOSS 登录后端到端仍未验收通过。延迟 about:blank 的本地浏览器夹具已验证只请求一次、明确停止。

## 已跑通的官网路径

公司招聘页 → 明确引用的 ATS 看板 → 公开岗位正文与稳定 ID → 本地匹配 → 显示申请入口与关联来源。

支持招聘页 a/iframe 链接，以及页面脚本内明确的招聘 URL 引用。只提取允许的 Greenhouse、Lever、Ashby 主机与看板；不会执行脚本，也不会从公司名称猜 slug。Next.js 页面可识别内嵌 jobUrl/applyUrl 后回源取正文。该关联说明招聘页引用了看板，不替代公司域名的人工核对，也不代表已经通过申请表单。

本轮真实界面扫描：安克、Cursor、Anthropic 各保留 3 个岗位，共 9 个，3 个已有记录，9 个完成本地准备；申请 0。读取数与保留数不同，达到预算的看板显示“部分完成”。六个新增岗位已入队，历史岗位保留。

只读浏览器核验确认 Anthropic 的 AI Operations Engineer, Partnerships 和本轮 Staff Research Engineer, Multi-Agent Scaling 页面均包含匹配标题、简历上传区、申请表单和提交按钮，未输入任何内容。安克入口跳转到其飞书招聘登录页。Cursor 的 Software Engineer, RL Data 虽仍在 API 返回结果中，其 applyUrl 实际显示 Page not found；已记录单条入口不可用，不将其等同于岗位已下线，也不推广到 Cursor 全部职位。

本地岗位已保存这些只读核验结果，按具体申请地址绑定，24 小时内刷新来源会保留；地址变化或过期后重新待核验。失效入口不显示申请链接，仍可查看来源招聘页。这些观察不会授予填写或提交权限。

在工作台勾选“本轮只查公司招聘来源”可暂时跳过 BOSS、猎聘、网页索引，避免平台受阻影响官网发现。官网来源仍须选择或配置。

```sh
python -m hunt.discovery --official-only --career-url https://cursor.com/careers --career-url https://www.anthropic.com/careers/jobs --keyword Agent --max-jobs 6 --max-pages 2 --output private/careers.json
# 可选已安装 Chrome；登录需要本人操作，参数与采集需一致
python -m hunt.sources_browser --login boss --data private/app --browser chrome
python -m hunt.discovery --source boss --browser-source boss --browser chrome --data private/app --keyword Agent --max-jobs 3
```

BOSS 再出现白屏、登录墙或验证码时，保持受阻状态并停止，不自动循环登录。官网流程已能提供独立于 BOSS 的实际岗位与申请入口；BOSS 的浏览器兼容性仍是未完成项。

## Issue 后续评论复核（2026-10-23）

[Issue #30 的讨论](https://github.com/eatmoreduck/boss-zhipin-scraper/issues/30)中，有用户称关闭 Clash 后 `code 37` 恢复，但明确补充自己**没有**发生 `about:blank` 跳转。作者也要求区分两种现象，并未确认通用白屏修复。因而该项目可参考独立会话、就绪检查和错误诊断，但不能作为本机白屏已解决的证据；也不能修复公司官网另一招聘系统的失效接收地址。
