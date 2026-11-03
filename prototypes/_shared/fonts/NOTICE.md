# 原型打包的字体

全部是 SIL Open Font License 1.1。许可证原文在同目录的 `OFL-*.txt`。这些文件是子集化后的修改版本，由 `prototypes/_tools/build_fonts.sh` 生成。

| 文件 | 来源字体 | 版权 | 子集内容 | 大小 |
| --- | --- | --- | --- | --- |
| `inter.woff2` | Inter，google/fonts `ofl/inter/Inter[opsz,wght].ttf` | The Inter Project Authors | 基本拉丁、拉丁补充、常用标点；wght 300–700，保留 opsz | 56 KB |
| `sans-a.woff2` | Noto Sans SC，`ofl/notosanssc/NotoSansSC[wght].ttf` | Adobe，保留字体名 "Source" | 方向 A 界面代码里的中文字和 ASCII；wght 400–700 | 94 KB |
| `serif-b.woff2` | Noto Serif SC，`ofl/notoserifsc/NotoSerifSC[wght].ttf` | Google Inc. | 方向 B 界面代码里的中文字和 ASCII；wght 400–900 | 116 KB |
| `archivo.woff2` | Archivo，`ofl/archivo/Archivo[wdth,wght].ttf` | The Archivo Project Authors | 基本拉丁、拉丁补充、常用标点；wght 400–900，wdth 62–100 | 54 KB |
| `sans-final.woff2` | Noto Sans SC | Adobe，保留字体名 "Source" | 合并原型界面代码里的中文字和 ASCII；wght 400–700 | 108 KB |
| `sans-c.woff2` | Noto Sans SC | Adobe，保留字体名 "Source" | 方向 C 界面代码里的中文字和 ASCII；wght 500–900 | 83 KB |

下载日期 2026-11-02，源文件 SHA-256：Inter `29160a80…`，NotoSansSC `a3041811…`，NotoSerifSC `050080d9…`，Archivo `0e094a7d…`。

OFL 规定修改版本不能使用保留字体名。Noto Sans SC 的保留名是 "Source"，这里的文件名和 CSS 字体族名（"AH Sans A" 等）都没有用到它。

实现到产品时：字体放进 `static/fonts/`，许可证原文一起放，署名写进仓库根目录的 `THIRD_PARTY_NOTICES.md`。原型阶段没有改这两处。
