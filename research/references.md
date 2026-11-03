# 参考研究笔记

研究日期 2026-11-02。每个参考都用应用内置浏览器实际打开过，视口 1440×900。英文产品 8 个、中文产品 2 个，另有中文排版的 2 个参考（少数派、W3C clreq）。下面写的机制都来自当天页面上看到的内容或文字，没有凭记忆补。

打不开、被换掉的：

- Perplexity 搜索结果页：打开后停在 Cloudflare 的人机验证。按规则不绕过，没研究。
- Google Scholar（原本想看"所有 N 个版本"的跨来源合并）：被 google.com/sorry 的异常流量页拦下，没研究。
- Read.cv：页面只显示 "This deployment is temporarily paused"，没研究。
- 换成了 HN Search（Algolia）和 GOV.UK Design System，下面有。

## 产品型界面

### 1. Linear Triage

- 网址：https://linear.app/docs/triage ，首页的产品截图 https://linear.app
- 借什么：分拣队列每个动作一个单键：接受 1、拒绝 2、标记重复 3、延后 H。延后的条目会在到期时间或"有新动静"时回到队列，以先到者为准。标记重复时，要选一个主条目来合并，附件一起转过去。
- 为什么适合：本产品的分拣是 感兴趣 / 稍后 / 跳过 三个桶，正好用 1 / 2 / 3。"延后到有新动静为止"可以直接对应"稍后"：岗位的 JD 改了、重新核验到了，就自动回到待选。"标记重复并合并到主条目"就是跨来源去重的人工兜底：自动合并错了，用户能手动把一条并到另一条，来源记录一起转过去。
- 不能照搬：深色界面和侧栏图标是 Linear 的品牌外观；Inter Display 和品牌字体不能拿。

### 2. Superhuman Mail

- 网址：帮助中心 "Speed Up With Shortcuts"、"Structure Your Inbox"、"Clear Your Inbox"（help.superhuman.com/hc/en-us/articles/46005789591693、46005793275277、46005796611341）
- 借什么：
  - Cmd+K 命令面板里，每个动作右边显示它的单键。用户第一次用面板，第二次就能直接按键。
  - 分组收件箱（Split Inbox）上显示的是总数，不是未读数，"把收件箱当待办清单"。Tab / Shift+Tab 在分组间切换。官方建议 3–7 个分组。
  - 完成（E）后条目进 Done，仍可搜索；对方回信时回到收件箱。稍后提醒（H）的条目会在设定时间回来。
- 为什么适合：分拣页的 bucket 计数应该是总数（待选 24、感兴趣 6），表达"还剩多少没分"。五个 bucket（待选、感兴趣、稍后、跳过、已有材料）落在 3–7 的范围里。面板显示快捷键这一招，可以替代一张要背的快捷键表。
- 不能照搬：营销页的紫色渐变、云朵图和 AI 聊天框跟本产品无关。

### 3. Things 3

- 网址：https://culturedcode.com/things/features/
- 借什么：打开一个待办时，它"变成一张干净的白纸"；标签、清单、日期这些字段收在右上角，用到时才展开。列表用标题（Headings）分组，整组能一起拖动、归档。Today 页把日历事件放在上面、待办放在下面，另有 This Evening 分区。
- 为什么适合：岗位详情先给 JD 正文和匹配解释，来源记录、采集时间、原始字段收起来，跟旧规范"证据按需展开"一致，只是做得更彻底。搜索结果按"同一个岗位"分组，跟 Things 用标题分组是同一种结构。
- 不能照搬：拟物图标、Apple 平台的控件外观。

### 4. Raycast

- 网址：https://www.raycast.com （首页剪贴板历史的演示画面）
- 借什么：
  - 筛选下拉框放在搜索框里面的右侧（演示里是 "Images Only"），不另占一行。
  - 左边列表、右边详情；详情底部是一张键值表（Application、Content Type、Dimensions……）。
  - 底栏固定显示当前主动作和它的键（"Copy to Clipboard ↵"），旁边是 "Actions ⌘K"；面板里每个动作都写着组合键。
- 为什么适合：搜索首页要同时放查询框和四个筛选（城市、方向、来源、新旧），筛选放进查询框能省下一整行，留给结果。分拣时底栏常驻"感兴趣 1 · 稍后 2 · 跳过 3"，手机上也能点。岗位来源记录用键值表展示（来源、首次发现、最近核验、状态）。
- 不能照搬：深色毛玻璃窗、红色品牌渐变、macOS 菜单栏外观。

### 5. Vercel Geist

- 网址：https://vercel.com/geist/introduction ，/colors ，/relative-time-card ，/empty-state
- 借什么：
  - 相对时间：列表里显示短格式（2m、5h、Yesterday），悬停显示绝对时间；超过 7 天的正文日期直接写成日期；不要在组件后面再加"ago"。
  - 灰阶按用途分档：1–3 组件背景（默认、悬停、按下），4–6 边线（默认、悬停、按下），7–8 高对比背景，9–10 文字（次要、主要）。每条边线只画一次，不叠半透明边。
  - 空状态分四类：空白、说明型、引导型、示例数据型。
- 为什么适合：岗位新旧是核心信息。列表里写"2 天"，悬停或展开显示"2026-10-31 首次发现，11-02 官网核验"；超过一周的写日期。灰阶分档能让三套原型的颜色有同一套规则。空状态分类直接用于"还没有搜索结果""还没定方向""这条岗位还没结构化"。
- 不能照搬：Geist 字体本身是 OFL 许可，可以用，但它没有中文字形，对本产品帮助有限；Vercel 的三角标志和网格背景是品牌元素。

### 6. Stripe API 参考

- 网址：https://docs.stripe.com/api/charges/object
- 借什么：左栏逐个字段写"字段名 + 类型 + nullable + 一句白话说明"，嵌套字段用"Show child attributes"展开；右栏固定显示原始对象。
- 为什么适合：JD 结构化就是一个对象：年限、学历、远程、硬技能、软技能、加分项、地点。左栏写结构化结果和"依据：原文第 2 段"，右栏是 JD 原文，依据处高亮。字段缺失时明确写"原文没提"（对应 nullable），不留空。
- 不能照搬：Stripe 的紫色、Söhne 字体（商业授权）。

### 7. HN Search（Algolia）

- 网址：https://hn.algolia.com/?dateRange=pastWeek&query=hiring%20backend&sort=byDate&type=story
- 借什么：筛选写成一句话："Search [Stories] by [Date] for [Past Week]"，每个方括号是一个下拉框。没有结果时写清楚搜了什么（"We found no stories matching hiring backend for this period"），并直接给两个放宽的动作："Search with a wider date range"、"Search for comments"。
- 为什么适合：本产品的查询能自然写成中文句子："在 上海、杭州 找 后端开发，来源 全部，只看 7 天内"。用户一眼能读懂当前条件，自然语言搜索（nl_query）解析出来的参数也能用同一句话回显。空结果直接给"放宽到 30 天""加上远程"这类按钮。
- 不能照搬：橙色 HN 标识。

### 8. GOV.UK Design System：任务列表

- 网址：https://design-system.service.gov.uk/components/task-list/
- 借什么：每行是"任务名 + 状态"，整行都是链接。研究发现用户会去点状态标签，以为它是按钮，所以状态被改得不像按钮。提示文字只写一句短话。展示用户的回答要用 Summary list，不要用任务列表。
- 为什么适合：设置页的来源列表（成功 / 失败 / 需要登录 / 未运行）、定方向页的"今天就能做"都是这种结构。状态标签不做成按钮的样子，跟旧规范"状态是小型矩形标签，不放大为装饰"一致，而且给了理由。定方向页回显已回答的问题用 Summary list。
- 不能照搬：GDS Transport 字体只许 GOV.UK 使用；皇冠标识。

## 中文排版

### 9. 少数派文章页

- 网址：https://sspai.com/post/118191
- 实测（浏览器 getComputedStyle）：正文 17px，行高 30.6px（1.8），段落宽 680px（约 40 个汉字），段后距 32px，字体栈 `-apple-system, system-ui, "PingFang SC", "Hiragino Sans GB", "Microsoft Yahei"`。中西文之间有空格："10 月 31 日""Apple 智能"。
- 借什么：长段中文阅读（JD 正文、定方向的理由）用 16–17px、行高 1.75–1.85、每行 34–40 字。中西文、数字之间留空。
- 不能照搬：红色派标识、头图插画。

### 10. W3C《中文排版需求》（clreq）

- 网址：https://www.w3.org/TR/clreq/ ，第 6.1.1 节"行首行尾禁则"，第 6.3.3 节"横排的中、西文混排配置"
- 原文要点：点号、结束引号、结束括号等不能出现在行首，开始引号、开始括号不能出现在行尾。汉字与西文字母、数字之间用不多于四分之一个汉字宽的字距；在中文点号前后、括号内侧不加。
- 借什么：CSS 用 `line-break: strict` 处理禁则；中西文间距优先用 `text-autospace: normal`（新版 Chrome / Safari 支持），不支持的浏览器上不手工插空格，靠数据里已有的空格。原型里的合成数据按少数派的写法自带空格。
- 不能照搬：无，这是规范。

## 中文产品

另找了两个中文产品，看真实的中文界面怎么处理中英混排、数字和标点。字节跳动招聘官网（jobs.bytedance.com）和飞书（feishu.cn）在内置浏览器里打开后页面为空（body 没有文字），没研究成。

### 11. 腾讯招聘搜索页（多数是反例）

- 网址：https://careers.tencent.com/search.html?keyword=后台开发
- 实测：岗位名 24px、字重 400、颜色 `rgb(50,50,50)`；辅助文字 12px、`letter-spacing: -0.49px`；字体栈以 "SF Pro SC" 开头。
- 看到的问题：
  - 岗位名中西文贴在一起："AI后台开发工程师""UE5 DS后台开发"。这是招聘方填的原文，产品改不了数据。所以本产品不能只靠文案规范，要用 `text-autospace` 在渲染时补间距。
  - 元信息写"更新于2026年10月29日"。"更新"可能是改了一个字，也可能是重新发布，读者分不清岗位到底多新。本产品把"首次发现""发布日期""最近核验"分开写。
  - 结果计数写成 `154条关于""的结果`，关键词为空时引号里什么都没有；"显示1-10,共79职位"里混用了英文逗号。空值和计数的文案要单独设计。
  - 12px 中文再加负字距，字挤在一起。中文小字不加负字距。
- 借什么：左侧筛选按"国家/地区、城市、职业类别、事业群、招聘类型"分组折叠。招聘方的分类是用户熟悉的词，本产品的筛选名也用"城市、方向、来源"这类白话。

### 12. Readhub（跨来源合并的中文范例）

- 网址：https://readhub.cn/hot ，话题页 https://readhub.cn/topic/8xfnEHnU5CI
- 实测：列表标题后面跟浅灰相对时间（14px、`rgb(127,127,127)`，"11 小时前"）；话题页标题 24px、字重 500、颜色 `rgba(0,0,0,.9)`（不用纯黑）、`letter-spacing: 0.48px`（中文标题用正字距）；`text-autospace` 计算值为 `normal`。中西文之间都有空格："赛力斯：10 月汽车销量 2.70 万辆"；引号用「」。
- 借什么：
  - 一个话题合并多家报道：正文下写一行"格隆汇/新浪科技/IT 之家"，读者一眼知道这件事有几个来源。本产品的"见于 3 个来源：公司官网 已核验在招、Moka、站点地图"就是这个结构。
  - 话题摘要里直接写"截至目前，尚未找到关于上述……的 xAI 官方公告"，把"有人说"和"官方确认"分开。本产品的"在招待确认"照这个写法："只在站点地图里见到，官网列表里没找到这条，还不能确认在招"。
- 不能照搬：Readhub 的品牌字 nocodeSymbol。

## 细节工艺的来源

Vercel Web Interface Guidelines、Rauno Freiberg、Emil Kowalski、Paco Coursey、Jhey Tompkins、Adam Argyle 等，见 `craft-details.md`。

## DesignBox 灵感盒

索引：本机 DesignBox 参考库的 `web/catalog.json`，共 15 条。按本产品的用户动作（检索、读 JD、分拣、确认）逐条看了 tags / scene / limits。

用：

- **Basement Staggered Slider**（用户 2026-10-23 认可）：借"大小、遮挡和明暗建立前后关系"。只在方向 C 的分拣页用：当前岗位是最前面那张，后面两张错层露出，提示"后面还有"。不借自动轮播，切换由按键或点击触发。手机按它自己的做法，重新排成纵向，不缩小桌面布局。
- **Grid to Full Preview**：借"少一次页面跳转，仍保持空间连续"。搜索结果点开后，详情在右侧原地展开，列表不离开视野。它的研究结论里写了"hover-only 要改成点击 / Enter 入口，手机要有正常详情页"，原型照这条做，不做悬停预览。
- **On-Scroll Text Highlight**：只借 `<mark>` 的语义和"静态可读终态"。JD 里命中的关键词、证据片段用 `<mark>` 静态标出，不做逐字动画。它的笔记明确说"高频信息流、要快速查找信息的文档不宜频繁隐藏或闪烁关键词"，JD 正是这种文档。
- **Line Hover Styles**：只借 Metis（单线从一端展开）这一种，用在少量文字链接上。笔记里说"hover 前就应能识别链接"，所以链接默认就有下划线。

不用：

- Codrops Scroll-Based Layout、Scroll Layout Formations、One Element Scroll、Image Expansion Typography：都是滚动驱动的叙事构图。本产品是工具，用户来了就查、就分，不该被滚动编排拖住。
- Image Tiles Menu、Repeating Image Transition、Rounded Menu、CSS Marquee Menu：靠图片和大幅转场，本产品没有图片素材，导航也只有五个入口。
- Context-Aware Logo、CSS Button Hover、Text Block Transitions：品牌装饰。Text Block Transitions 的笔记还指出它按英文空格拆词，中文不能直接用。

## 字体

用户已同意打包开源字体（2026-11-02 由发起会话转达），约束是：只用 OFL 或同等宽松许可；所有 woff2 合计不超过 1.5 MB；中文字体只用于固定的界面文字并按实际用字子集化；`font-display: swap`；运行时不连外网。

原型的做法和体积见 `prototypes/_shared/fonts/NOTICE.md`：五个子集合计 412 KB，每个方向 116–150 KB。不打包时的回退效果用 `?fonts=system` 打开，截图是 `prototypes/screenshots/*-systemfonts.png`。
