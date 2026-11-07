#!/usr/bin/env bash
# =============================================================================
# skill 插件面检查（容器内执行；spec: add-integration-test-env）
# =============================================================================
# 断言:
#   1. ~/.claude/skills/ 下 fenix-* skill 软链存在且 SKILL.md 可读
#   2. fenix-init 在 PATH
#   3. claude --version 可执行
#   4. 夹具项目内 .fenix/bin/fenix_spec.py status 运行成功
# 任一失败输出失败项与原始错误并 exit 1。
#
# 依赖环境变量（e2e.sh 注入）:
#   FENIX_IT_FRAMEWORK_DIR  容器内框架克隆目录
#   FENIX_IT_PROJECT        夹具项目目录
#   FENIX_IT_SPEC_NAME      已脚手架的 SPEC 名（默认 add-app-badge）
# =============================================================================
set -uo pipefail

export PATH="${HOME}/.local/bin:/usr/local/bin:${PATH}"

FW="${FENIX_IT_FRAMEWORK_DIR:?check_skills 需 FENIX_IT_FRAMEWORK_DIR}"
PROJECT="${FENIX_IT_PROJECT:?check_skills 需 FENIX_IT_PROJECT}"
SPEC_NAME="${FENIX_IT_SPEC_NAME:-add-app-badge}"

fail=0
ck() {  # ck <描述> <命令...>
  local desc="$1"; shift
  if "$@" >/tmp/ck_skills.out 2>&1; then
    echo "  ✅ ${desc}"
  else
    echo "  ❌ ${desc}"
    echo "     原始错误: $(head -c 300 /tmp/ck_skills.out | tr '\n' ' ')"
    fail=1
  fi
}

echo "── check_skills: skill 插件面 ──"

# 1) fenix-* skills 软链存在且 SKILL.md 可读
SKILLS_DIR="${HOME}/.claude/skills"
found=0
for d in "${SKILLS_DIR}"/fenix-*/; do
  [ -d "${d}" ] || continue
  found=$((found + 1))
  if [ -r "${d}SKILL.md" ]; then
    echo "  ✅ skill $(basename "${d}")（SKILL.md 可读）"
  else
    echo "  ❌ skill $(basename "${d}") SKILL.md 不可读"
    fail=1
  fi
done
if [ "${found}" -eq 0 ]; then
  echo "  ❌ ${SKILLS_DIR} 下无 fenix-* skill 软链（install.sh 未生效?）"
  ls "${SKILLS_DIR}" 2>&1 | head -5 || true
  fail=1
fi

# 2) fenix-init 在 PATH
if command -v fenix-init >/dev/null 2>&1; then
  echo "  ✅ fenix-init 在 PATH: $(command -v fenix-init)"
else
  echo "  ❌ fenix-init 不在 PATH"
  fail=1
fi

# 3) claude --version 可执行
ck "claude CLI 可执行" claude --version

# 4) 夹具项目内 SPEC 生成器 status 可运行
if (cd "${PROJECT}" && python3 .fenix/bin/fenix_spec.py status --change "${SPEC_NAME}" >/tmp/ck_spec.out 2>&1); then
  echo "  ✅ 夹具项目内 fenix_spec.py status 运行成功"
else
  echo "  ❌ 夹具项目内 fenix_spec.py status 失败"
  echo "     原始错误: $(head -c 300 /tmp/ck_spec.out | tr '\n' ' ')"
  fail=1
fi

if [ "${fail}" -ne 0 ]; then
  echo "check_skills: 存在失败项，exit 1"
  exit 1
fi
echo "check_skills: 全部通过"
exit 0
