# 细节工艺清单

每条写：现象、做法、出处、落地位置。出处都在 2026-11-02 用应用内置浏览器打开核对过；没打开的写明。最后一节是三个原型逐项过一遍的结果。

出处缩写：

- **VWG**：Vercel《Web Interface Guidelines》，https://vercel.com/design/guidelines
- **Rauno**：Rauno Freiberg《Invisible Details of Interaction Design》（2023-07），https://rauno.me/craft/interaction-design 。他的付费课程 Devouring Details（https://devouringdetails.com ，$125）只看了公开介绍页，正文没读。
- **Emil-7**：Emil Kowalski《7 Practical Animation Tips》，https://emilkowal.ski/ui/7-practical-animation-tips
- **Emil-NA**：Emil Kowalski《You Don't Need Animations》，https://emilkowal.ski/ui/you-dont-need-animations
- **Paco**：Paco Coursey 的 next-themes README，https://github.com/pacocoursey/next-themes ；作品页 https://paco.me/craft
- **Jhey**：Jhey Tompkins 原型 "the-intention-of-hover"，https://www.jhey.dev/prototypes/2025/hover-intention/index.html （读了它的 CSS）
- **Argyle**：Adam Argyle《Using CSS to fix the irradiation illusion》（2025-11-29），https://nerdy.dev/adjust-perceived-typepace-weight-for-dark-mode-without-layout-shift ；X 上的原帖 https://x.com/argyleink （2025-11-30，搜索结果页里看到的，8,393 次浏览）
- **CSS-Tricks**：Greg Gibson《Using CSS Custom Properties to Adjust Variable Font Weights in Dark Mode》（2020-12-10），https://css-tricks.com/using-css-custom-properties-to-adjust-variable-font-weights-in-dark-mode/
- **M2**：Material Design 2《Dark theme》，https://m2.material.io/design/color/dark-theme.html
- **GF-GRAD**：Google Fonts Knowledge《Grade axis》，https://fonts.google.com/knowledge/glossary/grade_axis
- **clreq**：W3C《中文排版需求》，https://www.w3.org/TR/clreq/ 第 6.1.1、6.3.3 节
- **少数派**：https://sspai.com/post/118191 （实测样式）

## 1. 深色模式下的字重和颜色

- **现象**：浅色字在深色底上看起来更粗、更大，这是光渗错觉（irradiation illusion）。纯黑底配纯白字会加重它。
- **业界做法（查证结果）**：
  - Argyle：用可变字体的 GRAD 轴，深色模式设 `--GRAD: -50`。GRAD 改笔画粗细但不改字宽，不会重排（GF-GRAD 也这样定义：负值变细，单位和 wght 一致）。
  - CSS-Tricks：没有 GRAD 时，用一个字重系数在深色模式乘下去。文中例子 400→350、700→600。
  - M2：深色底推荐 `#121212`，不用纯黑；高强调文字用 87% 不透明白，中强调 60%，禁用 38%。
- **做法（原型里）**：
  - 打包的三款字体（Inter、Noto Sans/Serif SC、Archivo）都没有 GRAD 轴，所以用 wght 系数：`* { font-variation-settings: "wght" calc(var(--fw) * var(--wm)) }`，深色 `--wm: .9`（400→360，600→540）。代价是切主题时字宽会微变；主题一天切不了几次，可以接受。
  - 系统中文字体（苹方、宋体）不是可变字体，`font-variation-settings` 对它们无效；把 400 写成 360 又会被匹配到 Light 300，太细。所以系统字体的正文保持 400，只把粗体从 600 降到 500（`--strong`）。
  - 颜色不用纯黑纯白：A 底 `#17181a`、字 `#e2e4e7`；B 底 `#1b1c1f`、字 `#e4e5e7`；C 底 `#1a1f1c`、字 `#e2e8e4`。
  - `color-scheme: dark` 让滚动条和原生控件跟着变（VWG "Set the appropriate color-scheme"；Paco 的 next-themes 也列了 "Themed browser UI with color-scheme"）。
- **对选字体的影响**：以后要选有 GRAD 轴的字体（例如 Roboto Flex，OFL），就能做到不重排的调细。Roboto Flex 没有中文，只能管拉丁和数字。

## 2. 等宽数字

- **现象**：比例数字在列表、计数里对不齐，数字变化时会左右抖。
- **做法**：`body { font-variant-numeric: tabular-nums }`。Inter 和 Archivo 子集都保留了 `tnum` 特性。
- **出处**：VWG "Tabular numbers for comparisons"。
- **落地**：三个原型的 body；分拣计数、薪资、日期、来源表的岗位数。

## 3. 中英文间距和标点挤压

- **现象**：中文和英文、数字贴在一起显得挤；连续标点（"）。"）占两个全角，中间空一大块；标点跑到行首。
- **做法**：
  - 自己写的文案在中西文之间手动加空格（少数派、Readhub 的写法）。
  - 来源抓来的动态文本常常不带空格（腾讯招聘的岗位名 "AI后台开发工程师"），用 `text-autospace: normal` 让浏览器自动加约 1/8 字宽（Chrome 140 起支持，本机 Chrome 156 实测 `CSS.supports` 为真）。clreq 规定不超过 1/4 字宽，两者都在范围内。
  - `text-spacing-trim: normal` 挤压相邻标点；打包的思源黑体 / 宋体子集保留了 `halt`、`palt`（宋体还有 `chws`）特性，挤压才有字形可用。
  - `line-break: strict` 执行行首行尾禁则（clreq 6.1.1）。
  - 数字和单位之间加空格（VWG "Separate numbers & units with a space"，例如 "30–45K·15 薪"、"4 年 4 个月"）。
- **落地**：三个原型的 body；合成数据里的文案。

## 4. 焦点环

- **现象**：用 `:focus` 时鼠标点击也会出现焦点框，很多人干脆去掉；键盘用户就迷路了。
- **做法**：只用 `:focus-visible`，2px 实线、2px 偏移。路由切换后把焦点移到新页面的 h1（程序聚焦不显示框）。吸顶的顶栏和底栏不能挡住被聚焦的元素：A 用 `scroll-padding-top / bottom` 留出位置。
- **出处**：VWG "Clear focus"（"Sticky headers, footers… never cover the focused element"）、"Manage focus"。
- **落地**：三个原型；Escape 后焦点回到打开详情的那一行（A、B、C 都实测通过）。

## 5. 点击区域

- **现象**：小按钮、复选框的文字点不中。
- **做法**：桌面上可点元素至少 24px，手机至少 44px；复选框和文字放在同一个 `<label>` 里，整块都能点。`touch-action: manipulation` 去掉双击缩放的延迟。
- **出处**：VWG "Match visual & hit targets"、"No dead zones on controls"、"Prevent double-tap zoom on controls"。
- **落地**：A 桌面按钮 32px、筛选标签 28px；三个原型在 760px 以下 `.btn` 和带复选框的 label 都设 `min-height: 44px`；C 的分拣格口在手机上是三个整块按钮。

## 6. 悬停时的意图延迟

- **现象**：鼠标只是路过，提示框就弹出来，满屏闪。
- **做法**：第一次悬停等 400ms 才出现；刚关掉一个提示，600ms 内再指向别的，立即出现且不播动画。鼠标移开立即消失。键盘聚焦同样会出现，Esc 关掉。
- **出处**：Jhey 的原型只给"进入"加 `transition-delay: 0.15s`，离开不加（"add a small transition-delay so you don't trigger when passing over"）；Emil-7 第 3 条 "Don't delay subsequent tooltips"；VWG "Tooltip timing"。
- **落地**：`prototypes/_shared/tip.js`。A 的事实编号（F1…）、搜索词；B 的事实编号、关键词、搜索词；C 的事实编号、关键词、搜索词。实测：200ms 时还没出现，500ms 出现；紧接着指向下一个时立即出现（`tip instant`）。

## 7. 动画缓动和时长

- **现象**：动画慢、用 ease-in 起步拖沓；高频操作每次都播动画，用几天就嫌慢。
- **做法**：
  - 进出场用 ease-out，界面动画不超过 300ms（Emil-7 第 4、6 条）。原型里：颜色 160ms，按下缩放 120ms，toast 160–200ms，C 的卡片飞入格口 220ms。
  - 按下按钮缩到 0.97（Emil-7 第 1 条）。提示框从 0.97 缩放进入，不从 0 开始（Emil-7 第 2 条）。
  - 键盘触发的动作不播动画（Emil-NA "You should never animate them"；Rauno 说 bmrks 的列表动画用了几天就觉得慢，去掉后快多了）。C 的分拣：点格口时卡片飞过去，按 1/2/3 时直接换下一张。
  - 不写 `transition: all`，只列具体属性（VWG）。
- **落地**：三个原型的 `.btn`、`.toast`、`.tip`；C 的 `.card.leaving`。

## 8. 加载时布局不跳动、骨架屏

- **现象**：数据很快回来时，加载指示一闪而过；骨架和真实内容高度不同，换内容时整页跳。
- **做法**：超过 150ms 才显示骨架，显示了就至少停 400ms；骨架行高和真实条目一致；按钮文字改成"正在搜索…"并禁用，结束后恢复；容器加 `aria-busy`。骨架不做闪烁动画。
- **出处**：VWG "Minimum loading-state duration"（150–300ms 显示延迟、300–500ms 最短显示）、"Stable skeletons"、"Loading buttons"、"Ellipsis for… loading states"。
- **落地**：`U.loading()`（`_shared/util.js`）。A 顶栏"开始搜索"，B "重新搜一遍"，C "再收一次"。实测 A：100ms 时没有骨架，300ms 时 4 行骨架；骨架行高按实测真实行高定为 127px（B、C 桌面 170px，手机分别 258px、238px）。
- **没做**：字体换入时的布局跳动。打包字体用 `font-display: swap`，Inter 和系统字体的度量不同，换入时拉丁文字宽会微变。可以给回退字体加 `size-adjust`，第二轮实现时再补。

## 9. 空状态

- **现象**：只写"暂无数据"，用户不知道下一步。
- **做法**：写清搜了什么、为什么空、给一个能放宽条件的按钮。发布时间未知的岗位不在"7 天内"里悄悄丢掉，单独说"另有 2 个不知道发布时间"，一键列出来。
- **出处**：HN Search 的空结果页（见 `references.md` 第 7 条）；Geist Empty State 分四类；VWG "No dead ends"、"All states designed"。
- **落地**：三个原型的搜索空结果、分拣清空、详情页"还没做匹配解释"（同时写明会把岗位原文发到哪个服务）。

## 10. 长文本截断加完整提示

- **现象**：一行放不下就截断，用户看不到全文。
- **做法**：只在确实需要单行的地方截断（顶栏运行状态、底栏当前岗位、格口里的最近岗位），截断处加 `title` 给出全文。正文、岗位名一律换行，不截断。
- **出处**：VWG "Resilient to user-generated content"。
- **落地**：A 的 `#run`、底栏 `.cur`；C 的 `#run`、格口列表、面单里的地点。B 没有截断的地方。

## 11. 选中文字的颜色

- **做法**：`::selection` 用各方向自己的强调色：A 荧光笔黄配深色字，B 圆珠笔浅蓝，C 浅绿；深色模式另配。
- **落地**：三个原型。

## 12. 滚动条留出 gutter

- **现象**：内容从不满一屏变成满一屏时，滚动条出现，整页向左挤几像素。
- **做法**：`html { scrollbar-gutter: stable }`；A 搜索页的两栏各自滚动，也加上。
- **出处**：VWG "No excessive scrollbars"（建议在 macOS 把滚动条设成"始终显示"来测 Windows 上的效果）。
- **落地**：三个原型。

## 13. 减少动态

- **做法**：`prefers-reduced-motion: reduce` 下关掉所有 CSS 过渡和动画、平滑滚动；C 的卡片飞入在 JS 里也检查 `U.reduced()`，直接换下一张。
- **出处**：VWG "Honor prefers-reduced-motion"；旧 DESIGN.md 已有这条，保留。
- **落地**：三个原型；截图 `*-reduced.png`。

## 另外落地的几条

- 状态不只靠颜色：每个状态都是"形状 + 文字"（A 圆点 / 半圆 / 叉 / 虚线圈，B 批改符号 ✓ ✗ ？ △，C 实心点 / 菱形 / 叉 / 虚线圈）。VWG "Redundant status cues"；旧 DESIGN.md 的 State Text Rule。
- 占位符用例子并以省略号结尾（"例如 Go、支付…"）。VWG "Placeholders signal emptiness"、"Use the ellipsis character"。
- 手机上输入框 16px，避免 iOS Safari 聚焦时自动放大。VWG "Mobile input size"。
- 导航用 `<a>`，能用 Cmd+点击新开标签页。VWG "Links are links"。
- 命令面板里每个动作旁边写它的快捷键（Superhuman 的做法）。只在 A 做了。

## 合并原型（prototypes/final）逐项结果

第二轮按用户的选择（A 做整体、B 做岗位详情）合成了一版。下面是它逐项过一遍的结果，都在本机 Chrome 156 里用脚本实测或看截图核对过。

| 类别 | 结果 |
| --- | --- |
| 1 深色字重和颜色 | 做了：可变字体 wght × 0.9；系统字体粗体 600→500；底 `#17181a`、字 `#e2e4e7`；`color-scheme: dark` |
| 2 等宽数字 | 做了 |
| 3 中英间距、标点挤压 | 做了：`text-autospace`、`text-spacing-trim`、`line-break: strict`；打包子集保留 `halt`、`palt` |
| 4 焦点环 | 做了：Esc 从详情返回后焦点回到原来那一行（实测 `g-g01`）；分拣、撤销、关命令面板后焦点留在当前行；吸顶栏和底栏留了 `scroll-padding` |
| 5 点击区域 | 做了：桌面按钮 32px、筛选 28px、事实编号和搜索词 24px；手机按钮和选项 44px |
| 6 悬停意图延迟 | 做了：实测 200ms 时提示框还没出现，550ms 时出现 |
| 7 缓动和时长 | 做了：都在 200ms 以内、ease-out；键盘动作无动画 |
| 8 加载不跳动、骨架 | 做了：骨架 150ms 后出现、至少停 400ms，行高 131px（实测真实行 131–161px，最常见 131px）。字体换入的微小跳动没处理 |
| 9 空状态 | 做了：搜索无结果、分拣某组为空、岗位还没做匹配解释、还没抓到 JD |
| 10 截断加提示 | 做了：顶栏运行状态、底栏当前岗位 |
| 11 选中文字颜色 | 做了 |
| 12 滚动条 gutter | 做了 |
| 13 减少动态 | 做了 |

## 第一轮三个原型逐项结果

"做了"都在 Chrome 156（本机）里实测或截图核对过；"部分"写明缺什么。

| 类别 | A 荧光笔 | B 批注 | C 投递 |
| --- | --- | --- | --- |
| 1 深色字重和颜色 | 做了：wght × 0.9，粗体 600→500，非纯黑白 | 做了：同 A；宋体、楷体是系统字体，只降粗体 | 做了：同 A；特粗 800→700 |
| 2 等宽数字 | 做了 | 做了 | 做了 |
| 3 中英间距、标点挤压 | 做了 | 做了 | 做了 |
| 4 焦点环 | 做了；吸顶栏留了 scroll-padding | 做了 | 做了 |
| 5 点击区域 | 做了：桌面 ≥ 28px，手机 44px | 做了：桌面 ≥ 34px，手机 44px | 做了：桌面 ≥ 34px，手机 44px |
| 6 悬停意图延迟 | 做了（tip.js） | 做了 | 做了 |
| 7 缓动和时长 | 做了；键盘动作无动画 | 做了；键盘动作无动画 | 做了；点击飞入 220ms，按键不播 |
| 8 加载不跳动、骨架 | 做了；字体换入的微小跳动没处理 | 同 A | 同 A |
| 9 空状态 | 做了 | 做了 | 做了 |
| 10 截断加提示 | 做了 | 不适用（没有截断） | 做了 |
| 11 选中文字颜色 | 做了 | 做了 | 做了 |
| 12 滚动条 gutter | 做了（页面和两栏） | 做了 | 做了 |
| 13 减少动态 | 做了 | 做了 | 做了（含 JS 动画） |
