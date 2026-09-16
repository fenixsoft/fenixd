#!/usr/bin/env bash
# refactor-verification-module 6.1：代码格式化统一入口（design D7 / tasks 6.1-6.5）。
#
# 工具：black（版本 26.5.1，2026-09-16 环境实测；无网络时回退 ruff format /
# black / autopep8 顺序安装）。安装：`pip install black pytokens`。
#
# 作用域：仅 core/、bin/、根 fenixd.py 的 *.py（tasks 6.2；MUST NOT 改动
# agents/、docs/、spec/ 与任何 *.md）。
# line-length=100（tasks 6.2 指定当前主流）。
#
# 例外：`core/agent_runner/runner.py` 被排除——refactor-agent-runner-module
# 已将其收敛至 ≤3800 行（test_agent_runner_modules_contract 行数契约），
# black 拆行会使其膨胀至 4090 行破坏该契约（「零行为变化/不引入新失败」
# 验收口径），故保持其格式化前形态。
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m black --line-length=100 --exclude 'core/agent_runner/runner\.py$' \
  core/ bin/ fenixd.py
