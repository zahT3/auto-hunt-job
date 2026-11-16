#!/bin/sh
set -eu
cd "$(dirname "$0")"
# A project venv keeps both normal application and optional browser runtime reproducible.
python3 -m venv .venv
if ! .venv/bin/python -m pip install -r requirements.txt; then
    printf '\n安装失败。DOCX 导出依赖 python-docx，它依赖 lxml（含 C 扩展）：常见平台有预编译包，冷门平台需要本机有 C 编译器和 libxml2/libxslt 开发包。\n' >&2
    printf '没有 lxml 也可以先装其余依赖，PDF 和 Markdown 导出照常可用，DOCX 导出会提示缺少 python-docx。\n' >&2
    exit 1
fi
printf '\n启动：.venv/bin/python run.py\n离线演示：.venv/bin/python run.py --demo --port 8767\n'
