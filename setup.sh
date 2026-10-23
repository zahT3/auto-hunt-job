#!/bin/sh
set -eu
cd "$(dirname "$0")"
# A project venv keeps both normal application and optional browser runtime reproducible.
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
printf '\n启动：.venv/bin/python run.py\n离线演示：.venv/bin/python run.py --demo --port 8767\n'
