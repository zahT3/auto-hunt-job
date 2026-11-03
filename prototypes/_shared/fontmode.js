// ?fonts=system：不用打包字体，只用系统字体，对比回退效果。
// ?fonts=windows：在 Mac 上模拟 Windows 的回退：去掉只有 macOS 才有的宋体、楷体（Songti SC、Kaiti SC 等），看界面在没有它们时的样子。
const mode = new URLSearchParams(location.search).get('fonts');
if (mode === 'system' || mode === 'windows') document.documentElement.dataset.fonts = mode;
