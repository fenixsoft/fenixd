#!/usr/bin/env bash
# =============================================================================
# fenixd 安装程序
# =============================================================================
# 将 fenixd 框架安装到本机：
#   1. 检查依赖（Python 3.10+ / git / tmux / Claude Code CLI / PyYAML）
#   2. 将 Claude Code skills 软链到 ~/.claude/skills/
#   3. 将 fenix-init 软链到 PATH（优先 ~/.local/bin，其次 /usr/local/bin）
#
# 用法: bash install.sh
# 可重复执行（幂等）。
# =============================================================================
set -euo pipefail

# 框架根目录 = 本脚本所在目录
FENIXD_HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "================================================================"
echo "  fenixd 安装程序"
echo "  框架目录: ${FENIXD_HOME}"
echo "================================================================"

# ── 1. 依赖检查 ──────────────────────────────────────────────────
fail=0
check() {
  local name="$1"; shift
  if "$@" >/dev/null 2>&1; then
    echo "  ✅ ${name}"
  else
    echo "  ❌ 缺少依赖: ${name}"
    fail=1
  fi
}

echo "── 依赖检查 ──"
# Python 3.10+
if python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then
  echo "  ✅ python3 ($(python3 --version 2>&1))"
else
  echo "  ❌ 缺少依赖: python3 3.10+ (当前: $(python3 --version 2>&1 || echo 无))"
  fail=1
fi
check "git" git --version
check "tmux" tmux -V
check "claude CLI" claude --version
if python3 -c "import yaml" 2>/dev/null; then
  echo "  ✅ PyYAML ($(python3 -c 'import yaml; print(yaml.__version__)' 2>/dev/null))"
else
  echo "  ⚠️  PyYAML 未安装，正在安装..."
  pip3 install pyyaml -q && echo "  ✅ PyYAML 安装完成" || { echo "  ❌ PyYAML 安装失败，请手动执行: pip3 install pyyaml"; fail=1; }
fi

if [ "$fail" -ne 0 ]; then
  echo ""
  echo "存在缺失依赖，请先安装后再运行本脚本。"
  exit 1
fi

# ── 2. 安装 Claude Code skills ───────────────────────────────────
echo "── 安装 Claude Code skills ──"
SKILLS_DIR="${HOME}/.claude/skills"
mkdir -p "${SKILLS_DIR}"
for skill_dir in "${FENIXD_HOME}"/skills/*/; do
  skill_name="$(basename "${skill_dir}")"
  target="${SKILLS_DIR}/${skill_name}"
  if [ -L "${target}" ] && [ "$(readlink "${target}")" = "${skill_dir%/}" ]; then
    echo "  ✓ ${skill_name}（已软链）"
  elif [ -e "${target}" ] || [ -L "${target}" ]; then
    echo "  ⚠️  ${skill_name} 已存在且非框架软链，跳过（请手动处理）"
  else
    ln -s "${skill_dir%/}" "${target}"
    echo "  ✅ ${skill_name} → ${target}"
  fi
done

# ── 3. 将 fenix-init 放入 PATH ────────────────────────────────────
echo "── 安装 fenix-init 命令 ──"
BIN_DIR="${HOME}/.local/bin"
if [ ! -d "${BIN_DIR}" ]; then
  if [ -w /usr/local/bin ]; then
    BIN_DIR="/usr/local/bin"
  else
    mkdir -p "${HOME}/.local/bin"
  fi
fi
ln -sfn "${FENIXD_HOME}/fenix-init" "${BIN_DIR}/fenix-init"
echo "  ✅ fenix-init → ${BIN_DIR}/fenix-init"

# 若 ~/.local/bin 尚不在 PATH，给出提示
if ! echo "${PATH}" | tr ':' '\n' | grep -qx "${BIN_DIR}"; then
  echo "  ⚠️  ${BIN_DIR} 不在 PATH 中，请将以下行加入 ~/.zshrc / ~/.bashrc："
  echo "       export PATH=\"${BIN_DIR}:\$PATH\""
fi

echo ""
echo "================================================================"
echo "  安装完成！"
echo "================================================================"
echo "  下一步："
echo "    1. （可选）配置状态栏：在 ~/.claude/settings.json 的 statusLine 指向"
echo "       python3 ${FENIXD_HOME}/bin/statusline.py"
echo "    2. 进入你的项目目录，运行: fenix-init"
echo "    3. 启动框架: /fenix-setup"
echo "    4. 创建需求: /fenix-new \"你的想法\""
echo ""
echo "  🐉 新能力 — Web Dashboard："
echo "     在任意 Fenixd 项目内运行 /fenix-dashboard，即可在浏览器查看"
echo "     跨项目 SPEC 状态 / 任务进度 / 验证报告 / 失败截图 / 运行中 Agent 对话。"
echo "     （skill 已自动软链至 ~/.claude/skills/fenix-dashboard）"
echo "================================================================"
