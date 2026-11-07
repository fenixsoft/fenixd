#!/usr/bin/env bash
# =============================================================================
# fenixd 集成测试容器内主编排（由宿主 run.sh 以 `bash /opt/it/e2e.sh` 启动）
# =============================================================================
# 全链顺序（真实模式）：HTTPS 克隆框架 → install.sh → 夹具项目创建 → 依注入
# 环境变量生成 .fenix/config.yaml → dashboard 前端 dist 缺失时先构建 →
# nohup 启动 daemon + 健康检查 → fenix_spec.py new + 种子覆写 +
# core.state_machine.add_spec 程序化注册 fast-track SPEC → 轮询 STATE.md 至
# done/blocked → 断言（终态 done / merge-back 页面元素 / 验证报告 pass /
# run jsonl 在场）→ 双轮汇总 summary.json。
#
# 双轮编排（D6）：/work/round-claude/ 与 /work/round-dsh/ 独立夹具项目、
# 独立配置（仅 agent.harness 不同）与独立超时预算；dsh 轮前置完成
# fenix-dsh-bundle 容器内部署（自定义 profile + link: 软链挂入）。
# 任一轮失败记录后继续另一轮；任一失败整体 exit 1。
#
# smoke 模式（FENIX_IT_MODE=smoke）：跳过 SPEC 注册与闭环轮次，仅克隆安装、
# 夹具项目创建 + daemon 启动健康检查 + 三插件面验证。
#
# 产物统一落 FENIX_IT_ARTIFACTS_DIR（容器内 /artifacts 读写卷）。
# 退出码: 0=全绿; 1=判定失败; 2=用法/装置错误。
# =============================================================================
set -uo pipefail

MODE="${FENIX_IT_MODE:-real}"
ART="${FENIX_IT_ARTIFACTS_DIR:-/artifacts}"
GIT_REPO="${FENIX_IT_GIT_REPO:-https://github.com/fenixsoft/fenixd.git}"
GIT_REF="${FENIX_IT_GIT_REF:-main}"
PLUGINS_REPO="${FENIX_IT_PLUGINS_REPO:-}"
TIMEOUT="${FENIX_IT_TIMEOUT:-3600}"
SPEC_NAME="add-app-badge"

# install.sh 将 fenix-init 软链至 ~/.local/bin（非登录 shell 默认不含该路径）
export PATH="${HOME}/.local/bin:/usr/local/bin:${PATH}"

WORK=/work
FW="${WORK}/framework"
DSH_HOME_HEADLESS="${WORK}/dsh-home"     # dsh headless 轮隔离家目录（profile 与 agent.dsh_profile 一致）
DSH_PROFILE="fenix"                       # dsh_adapter.DSH_DEFAULT_PROFILE 同源
DASH_PORT=8787
LOG="${ART}/orchestrate.log"
mkdir -p "${ART}"

log() { echo "[e2e $(date -u '+%H:%M:%S')] $*" | tee -a "${LOG}"; }

# ── 汇总产物（任何退出路径都尽力写 summary.json）───────────────────────────
MODE_OUT="${MODE}"
declare -a ROUND_LINES=()   # "harness|status|elapsed_seconds|reason"
declare -A FACE_STATUS=()   # skills / dashboard / dsh_web → pass|fail|skipped
declare -a FAILURES=()

face_status() { echo "${FACE_STATUS[$1]:-skipped}"; }

write_summary() {
  local final_rc="$1"
  python3 - "${ART}/summary.json" "${MODE_OUT}" "${final_rc}" \
    "${ROUND_LINES[@]-}" <<'PY'
import datetime, json, os, sys
path, mode, rc = sys.argv[1], sys.argv[2], sys.argv[3]
rounds = []
for line in sys.argv[4:]:
    if not line:
        continue
    parts = line.split("|", 3)
    while len(parts) < 4:
        parts.append("")
    rounds.append({
        "harness": parts[0], "status": parts[1],
        "elapsed_seconds": int(parts[2] or 0), "reason": parts[3],
    })
faces = {}
for key in ("skills", "dashboard", "dsh_web"):
    faces[key] = os.environ.get(f"FACE_{key.upper()}", "skipped")
summary = {
    "mode": mode,
    "exit_code": int(rc),
    "git_repo": os.environ.get("FENIX_IT_GIT_REPO_ECHO", ""),
    "git_ref": os.environ.get("FENIX_IT_GIT_REF_ECHO", ""),
    "rounds": rounds,
    "plugin_faces": faces,
    "failures": json.loads(os.environ.get("FENIX_IT_FAILURES", "[]")),
    "artifacts_dir": os.environ.get("FENIX_IT_ARTIFACTS_DIR", "/artifacts"),
    "finished_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
}
with open(path, "w", encoding="utf-8") as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)
PY
}

export FACE_SKILLS FACE_DASHBOARD FACE_DSH_WEB
sync_face_env() {
  export FACE_SKILLS="$(face_status skills)"
  export FACE_DASHBOARD="$(face_status dashboard)"
  export FACE_DSH_WEB="$(face_status dsh_web)"
  export FENIX_IT_FAILURES="$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1:], ensure_ascii=False))' "${FAILURES[@]-}")"
  export FENIX_IT_GIT_REPO_ECHO="${GIT_REPO}" FENIX_IT_GIT_REF_ECHO="${GIT_REF}"
}

SUMMARY_WRITTEN=0
finish() {  # $1 = exit code
  SUMMARY_WRITTEN=1
  sync_face_env
  write_summary "$1"
  log "summary.json 已落盘: ${ART}/summary.json（exit $1）"
  trap - EXIT
  exit "$1"
}
trap 'rc=$?; if [ "${SUMMARY_WRITTEN}" -eq 0 ]; then sync_face_env; write_summary "$rc"; fi; exit "$rc"' EXIT

record_failure() { FAILURES+=("$1"); log "失败: $1"; }

# ════════════════════════════════════════════════════════════════════════
# 0) 入参自检（真实模式容器内侧复核凭据齐备性，缺项属装置错误 exit 2）
# ════════════════════════════════════════════════════════════════════════
if [ "${MODE}" != "smoke" ] && [ "${MODE}" != "real" ]; then
  log "FENIX_IT_MODE 非法: ${MODE}（合法 smoke|real）"; finish 2
fi
if [ "${MODE}" = "real" ]; then
  miss=()
  [ -n "${FENIX_IT_LLM_BASE_URL:-}" ] || miss+=("FENIX_IT_LLM_BASE_URL")
  [ -n "${FENIX_IT_LLM_API_KEY:-}" ]  || miss+=("FENIX_IT_LLM_API_KEY")
  [ -n "${FENIX_IT_LLM_MODEL:-}" ]    || miss+=("FENIX_IT_LLM_MODEL")
  if [ "${#miss[@]}" -gt 0 ]; then
    log "真实模式缺 LLM 凭据: ${miss[*]}（容器内侧复核）"; finish 2
  fi
fi
log "模式=${MODE} 克隆源=${GIT_REPO} 引用=${GIT_REF} 每轮预算=${TIMEOUT}s 插件源=${PLUGINS_REPO:-<无>}"

# ════════════════════════════════════════════════════════════════════════
# 1) 克隆框架（框架不入镜像；git URL 与本地路径均支持）
# ════════════════════════════════════════════════════════════════════════
log "克隆框架: ${GIT_REPO}（ref=${GIT_REF}）"
rm -rf "${FW}"
if ! git clone --depth 1 -b "${GIT_REF}" "${GIT_REPO}" "${FW}" >>"${LOG}" 2>&1; then
  log "浅克隆失败，回退完整克隆"
  rm -rf "${FW}"
  if ! git clone -b "${GIT_REF}" "${GIT_REPO}" "${FW}" >>"${LOG}" 2>&1; then
    record_failure "框架克隆失败: repo=${GIT_REPO} ref=${GIT_REF}（克隆错误详见 orchestrate.log）"
    finish 1
  fi
fi
log "克隆完成: $(git -C "${FW}" rev-parse --short HEAD)"

# ════════════════════════════════════════════════════════════════════════
# 2) install.sh（依赖检查 + skills 软链 + fenix-init 入 PATH）
# ════════════════════════════════════════════════════════════════════════
log "执行 install.sh"
if ! (cd "${FW}" && bash install.sh) >>"${ART}/install.log" 2>&1; then
  record_failure "install.sh 失败（见 install.log 尾部: $(tail -3 "${ART}/install.log" | tr '\n' ' ')）"
  finish 1
fi
log "install.sh 完成"

# ════════════════════════════════════════════════════════════════════════
# 3) dashboard 前端 dist 缺失时先构建（源码克隆形态；dist 不入 git）
# ════════════════════════════════════════════════════════════════════════
if [ ! -f "${FW}/core/dashboard/static/dist/index.html" ]; then
  log "前端 dist 缺失，构建: npm install --no-audit --no-fund && npm run build"
  if ! (cd "${FW}/core/dashboard/static" \
        && npm install --no-audit --no-fund && npm run build) >>"${ART}/frontend-build.log" 2>&1; then
    record_failure "dashboard 前端构建失败（见 frontend-build.log 尾部: $(tail -3 "${ART}/frontend-build.log" | tr '\n' ' ')）"
    finish 1
  fi
  log "前端构建完成"
else
  log "前端 dist 已在场，跳过构建"
fi

# ════════════════════════════════════════════════════════════════════════
# 公共函数：夹具项目创建 / 配置生成 / daemon 启动 / SPEC 注册 / 轮询 / 断言
# ════════════════════════════════════════════════════════════════════════

# make_fixture_project <项目目录> <项目名>
make_fixture_project() {
  local pdir="$1" pname="$2"
  mkdir -p "${pdir}"
  cp /opt/it/fixture/index.html /opt/it/fixture/app.js "${pdir}/"
  git -C "${pdir}" init -q
  git -C "${pdir}" add -A
  git -C "${pdir}" -c user.name=fenix-it -c user.email=fenix-it@example.com \
      commit -qm "chore: 夹具静态小站初始版"
  (cd "${pdir}" && fenix-init . --name "${pname}" --type web) >>"${LOG}" 2>&1
}

# gen_config <项目目录> <harness>
# 依注入环境变量生成 .fenix/config.yaml：provider 三要素（可选，smoke 无凭据时
# 留空注册表）、agents.models 全角色指派、agent.harness、project.type: web、
# 审批门保持人工档（gates.approve_mode: manual，设计 D5）。
gen_config() {
  local pdir="$1" harness="$2"
  PROJECT_DIR="${pdir}" HARNESS="${harness}" python3 <<'PY'
import os, sys, yaml
proj, harness = os.environ["PROJECT_DIR"], os.environ["HARNESS"]
cfg_path = os.path.join(proj, ".fenix", "config.yaml")
with open(cfg_path, encoding="utf-8") as f:
    cfg = yaml.safe_load(f) or {}
cfg.setdefault("project", {})["type"] = "web"   # 夹具为静态小站：显式声明 web 形态
base = os.environ.get("FENIX_IT_LLM_BASE_URL", "").strip()
key = os.environ.get("FENIX_IT_LLM_API_KEY", "").strip()
model = os.environ.get("FENIX_IT_LLM_MODEL", "").strip()
if base and key and model:
    cfg.setdefault("llm", {})["providers"] = [
        {"name": "fenix-it", "baseurl": base, "apikey": key, "model": model}
    ]
    sys.path.insert(0, os.path.join(proj, ".fenix"))
    from core.config import ConfigLoader
    roles = list(ConfigLoader.KNOWN_AGENT_TYPES)
    cfg.setdefault("agents", {})["models"] = {r: {"provider": "fenix-it"} for r in roles}
agent = cfg.setdefault("agent", {})
agent["harness"] = harness
if harness == "dsh":
    # dsh 线协议守卫同款判据：Anthropic 兼容形态 baseurl 须 anthropic-messages
    if "/anthropic" in base:
        agent["dsh_api"] = "anthropic-messages"
    # profile 与容器内部署一致（dsh_adapter.DSH_DEFAULT_PROFILE 同源）；
    # dsh_home 指向 bundle 部署的隔离家目录
    agent["dsh_profile"] = "fenix"
    agent["dsh_home"] = "/work/dsh-home"
cfg.setdefault("gates", {})["approve_mode"] = "manual"
with open(cfg_path, "w", encoding="utf-8") as f:
    yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
print(f"config.yaml 生成完毕: harness={harness} provider={'有' if base and key and model else '无(smoke)'}")
PY
}

# start_daemon <项目目录> <日志文件> <pid 文件>；健康检查 = 进程存活 +
# .fenix/logs 出现日志输出；失败时输出日志尾部。
start_daemon() {
  local pdir="$1" dlog="$2" pidf="$3"
  (cd "${pdir}" && nohup python3 .fenix/fenixd.py >>"${dlog}" 2>&1 & echo $! >"${pidf}")
  local pid
  pid="$(cat "${pidf}")"
  local i
  for i in $(seq 1 45); do
    if ! kill -0 "${pid}" 2>/dev/null; then
      log "daemon 进程已退出（pid=${pid}），日志尾部: $(tail -3 "${dlog}" | tr '\n' ' ')"
      return 1
    fi
    if [ -d "${pdir}/.fenix/logs" ] && [ -n "$(ls "${pdir}/.fenix/logs" 2>/dev/null | head -1)" ]; then
      sleep 2
      kill -0 "${pid}" 2>/dev/null || { log "daemon 健康检查窗口内退出"; return 1; }
      log "daemon 健康检查通过（pid=${pid}，日志目录在场）"
      return 0
    fi
    sleep 1
  done
  log "daemon 健康检查超时（45s 内无日志输出），日志尾部: $(tail -3 "${dlog}" | tr '\n' ' ')"
  return 1
}

stop_daemon() {  # <pid 文件>
  local pidf="$1"
  [ -f "${pidf}" ] && kill "$(cat "${pidf}")" 2>/dev/null || true
  rm -f "${pidf}"
}

# scaffold_spec <项目目录>：fenix_spec.py new + 种子覆写 + mode: fast-track +
# 声明 lint 预检（lint 违规禁止进入注册——对齐 fenix-new skill §3.3）。
scaffold_spec() {
  local pdir="$1"
  (
    set -e
    cd "${pdir}"
    python3 .fenix/bin/fenix_spec.py new "${SPEC_NAME}"
    cp /opt/it/fixture/spec-proposal.md "spec/changes/${SPEC_NAME}/proposal.md"
    cp /opt/it/fixture/spec-tasks.md "spec/changes/${SPEC_NAME}/tasks.md"
    python3 - "${SPEC_NAME}" <<'PY'
import sys
from pathlib import Path
name = sys.argv[1]
p = Path("spec/changes") / name / ".spec.yaml"
text = p.read_text(encoding="utf-8")
if "mode:" not in text:
    p.write_text(text.rstrip() + "\nmode: fast-track\n", encoding="utf-8")
print("mode: fast-track 已写入 .spec.yaml")
PY
    python3 - "${SPEC_NAME}" <<'PY2'
import sys
sys.path.insert(0, ".fenix")
from core.deliverables import lint_declared, lint_tasks_parseable
name = sys.argv[1]
v = lint_declared(f"spec/changes/{name}", ".") + lint_tasks_parseable(f"spec/changes/{name}", ".")
print("\n".join(v) if v else "OK")
sys.exit(1 if v else 0)
PY2
  ) >>"${LOG}" 2>&1
}

# register_spec <项目目录>：core.state_machine.add_spec 程序化注册（drafted）
register_spec() {
  local pdir="$1"
  (cd "${pdir}" && python3 - "${SPEC_NAME}" <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, ".fenix")
from core.state_machine import StateMachine
name = sys.argv[1]
sm = StateMachine(Path(".fenix/STATE.md"), None)
ok = sm.add_spec(name, {"status": "drafted", "priority": 5})
print(f"SPEC {name} registered={ok}")
PY
  ) >>"${LOG}" 2>&1
}

# poll_status <项目目录> <预算秒>：轮询 STATE.md 至终态，stdout 输出终态
# （done / blocked / 其他非终态值 / timeout）
poll_status() {
  local pdir="$1" budget="$2" st=""
  local deadline=$(( SECONDS + budget ))
  while [ "${SECONDS}" -lt "${deadline}" ]; do
    st="$(cd "${pdir}" && python3 - "${SPEC_NAME}" <<'PY' 2>/dev/null || echo read_error
import sys
from pathlib import Path
sys.path.insert(0, ".fenix")
from core.state_machine import StateMachine
name = sys.argv[1]
sm = StateMachine(Path(".fenix/STATE.md"), None)
entry = sm.read_all().get(name) or {}
print(entry.get("status", ""))
PY
)"
    case "${st}" in
      done|blocked) echo "${st}"; return 0 ;;
    esac
    sleep 10
  done
  echo "timeout"
}

# assert_round <项目目录>：终态后断言链（done / 页面元素 / 验证报告 / run jsonl）
# 输出断言失败明细（空串 = 全过）。
assert_round() {
  local pdir="$1" bad="" rep
  if ! grep -q 'data-testid="app-badge"' "${pdir}/index.html" 2>/dev/null; then
    bad="${bad} 夹具页面缺预期元素 data-testid=app-badge（merge-back 未落地?）;"
  fi
  rep="${pdir}/.fenix/verify-progress/${SPEC_NAME}/report.json"
  if [ ! -f "${rep}" ]; then
    bad="${bad} 验证报告缺失（${rep}）;"
  else
    python3 - "${rep}" <<'PY' || bad="${bad} 验证报告非 pass（summary.failed/errors 非零或解析失败）;"
import json, sys
try:
    with open(sys.argv[1], encoding="utf-8") as f:
        s = json.load(f)["summary"]
except Exception:
    sys.exit(1)
sys.exit(0 if (s.get("failed", 1) == 0 and s.get("errors", 1) == 0) else 1)
PY
  fi
  if ! find "${pdir}/.fenix/runs" -name '*.jsonl' -size +0 2>/dev/null | head -1 | grep -q .; then
    bad="${bad} .fenix/runs/ 无 run jsonl 产物;"
  fi
  echo "${bad}"
}

# deploy_dsh_bundle：dsh 轮前置——bundle npm install + 自定义 profile 创建 +
# link: 软链挂入 + bundles 追加 + dump-config 挂载自检（D6）。失败返回非零。
deploy_dsh_bundle() {
  log "dsh 轮前置: fenix-dsh-bundle 容器内部署"
  if ! (cd "${FW}/dsh-bundle" && npm install --no-audit --no-fund) >>"${ART}/dsh-bundle-install.log" 2>&1; then
    log "bundle npm install 失败: $(tail -3 "${ART}/dsh-bundle-install.log" | tr '\n' ' ')"
    return 1
  fi
  # shipped 模板名（headless）被 CLI 禁止作为自定义 profile 目标——必须携带
  # --profile 自定义名（dsh_adapter 实测口径）
  if ! DSH_HOME="${DSH_HOME_HEADLESS}" dsh --profile "${DSH_PROFILE}" \
        --from-default-profile headless >>"${LOG}" 2>&1; then
    log "自定义 profile 创建失败（profile=${DSH_PROFILE}）"
    return 1
  fi
  if ! DSH_HOME="${DSH_HOME_HEADLESS}" dsh plugin --profile "${DSH_PROFILE}" \
        add "link:${FW}/dsh-bundle" >>"${LOG}" 2>&1; then
    log "bundle link: 挂入失败（plugin add link:${FW}/dsh-bundle）"
    return 1
  fi
  DSH_HOME="${DSH_HOME_HEADLESS}" python3 - "${DSH_PROFILE}" <<'PY' >>"${LOG}" 2>&1 || { log "bundles 追加失败"; return 1; }
import json, os, sys
profile = sys.argv[1]
pkg_path = os.path.join(os.environ["DSH_HOME"], "profiles", profile, "package.json")
with open(pkg_path, encoding="utf-8") as f:
    pkg = json.load(f)
bundles = pkg.setdefault("dsh", {}).setdefault("profile", {}).setdefault("bundles", [])
if "fenix-dsh-bundle" not in bundles:
    bundles.append("fenix-dsh-bundle")
with open(pkg_path, "w", encoding="utf-8") as f:
    json.dump(pkg, f, ensure_ascii=False, indent=2)
print("dsh.profile.bundles 已追加 fenix-dsh-bundle")
PY
  if ! DSH_HOME="${DSH_HOME_HEADLESS}" dsh --profile "${DSH_PROFILE}" --dump-config 2>>"${LOG}" \
      | grep -q fenix-model-config; then
    log "bundle 挂载自检失败（--dump-config 无 fenix-model-config 标记）"
    return 1
  fi
  log "fenix-dsh-bundle 部署与挂载自检通过"
}

# run_round <harness>：单轮闭环（夹具项目 → 配置 → daemon → 注册 → 轮询 → 断言）
run_round() {
  local harness="$1"
  local rdir="${WORK}/round-${harness}" pdir rlog pidf t0 st secs bad
  pdir="${rdir}/project"; rlog="${ART}/daemon-${harness}.log"; pidf="${ART}/daemon-${harness}.pid"
  t0=${SECONDS}
  mkdir -p "${rdir}"

  log "── 轮次 ${harness} 开始（预算 ${TIMEOUT}s）──"
  if ! make_fixture_project "${pdir}" "fixture-${harness}"; then
    ROUND_LINES+=("${harness}|fail|0|夹具项目创建失败"); return 1
  fi
  if ! gen_config "${pdir}" "${harness}"; then
    ROUND_LINES+=("${harness}|fail|0|config.yaml 生成失败"); return 1
  fi
  if ! start_daemon "${pdir}" "${rlog}" "${pidf}"; then
    ROUND_LINES+=("${harness}|fail|$(( SECONDS - t0 ))|daemon 启动/健康检查失败"); return 1
  fi
  if ! scaffold_spec "${pdir}"; then
    stop_daemon "${pidf}"
    ROUND_LINES+=("${harness}|fail|$(( SECONDS - t0 ))|SPEC 脚手架/种子覆写/lint 失败（见 orchestrate.log）"); return 1
  fi
  if [ "${harness}" = "dsh" ]; then
    # 模型显式配置三要素缺失即该轮 fail-loud（D6）
    if [ -z "${FENIX_IT_LLM_BASE_URL:-}" ] || [ -z "${FENIX_IT_LLM_API_KEY:-}" ] || [ -z "${FENIX_IT_LLM_MODEL:-}" ]; then
      stop_daemon "${pidf}"
      ROUND_LINES+=("${harness}|fail|$(( SECONDS - t0 ))|模型显式配置三要素缺失"); return 1
    fi
    if ! deploy_dsh_bundle; then
      stop_daemon "${pidf}"
      ROUND_LINES+=("${harness}|fail|$(( SECONDS - t0 ))|fenix-dsh-bundle 部署/挂载自检失败"); return 1
    fi
  fi
  if ! register_spec "${pdir}"; then
    stop_daemon "${pidf}"
    ROUND_LINES+=("${harness}|fail|$(( SECONDS - t0 ))|add_spec 注册失败"); return 1
  fi
  log "轮次 ${harness}: SPEC ${SPEC_NAME} 已注册，轮询终态（≤${TIMEOUT}s）"
  st="$(poll_status "${pdir}" "${TIMEOUT}")"
  stop_daemon "${pidf}"
  secs=$(( SECONDS - t0 ))
  if [ "${st}" != "done" ]; then
    ROUND_LINES+=("${harness}|fail|${secs}|终态=${st}（期望 done）")
    return 1
  fi
  bad="$(assert_round "${pdir}")"
  if [ -n "${bad}" ]; then
    ROUND_LINES+=("${harness}|fail|${secs}|终态 done 但断言失败:${bad}")
    return 1
  fi
  ROUND_LINES+=("${harness}|pass|${secs}|")
  log "轮次 ${harness}: 全绿（耗时 ${secs}s）"
  return 0
}

# ════════════════════════════════════════════════════════════════════════
# 4) 模式分派
# ════════════════════════════════════════════════════════════════════════
CHECK_PROJECT=""

if [ "${MODE}" = "smoke" ]; then
  # ── smoke：夹具项目 + daemon 健康检查（闭环轮次跳过），随后三插件面 ──
  log "── smoke 模式：夹具项目创建 + daemon 启动健康检查 ──"
  sdir="${WORK}/round-smoke"; pdir="${sdir}/project"
  t0=${SECONDS}
  if ! make_fixture_project "${pdir}" "fixture-smoke"; then
    record_failure "smoke: 夹具项目创建失败"; finish 1
  fi
  if ! gen_config "${pdir}" "claude"; then
    record_failure "smoke: config.yaml 生成失败"; finish 1
  fi
  if ! start_daemon "${pdir}" "${ART}/daemon-smoke.log" "${ART}/daemon-smoke.pid"; then
    record_failure "smoke: daemon 启动/健康检查失败"; finish 1
  fi
  if ! scaffold_spec "${pdir}"; then
    stop_daemon "${ART}/daemon-smoke.pid"
    record_failure "smoke: SPEC 脚手架失败（smoke 不注册、仅脚手架以供 skill 面检查）"; finish 1
  fi
  ROUND_LINES+=("smoke|pass|$(( SECONDS - t0 ))|克隆安装/夹具/daemon 健康检查通过")
  CHECK_PROJECT="${pdir}"
else
  # ── real：双轮顺序（D6：任一轮失败记录后继续另一轮）──
  run_round claude || true
  run_round dsh || true
  if [ -d "${WORK}/round-claude/project" ]; then
    CHECK_PROJECT="${WORK}/round-claude/project"
  elif [ -d "${WORK}/round-dsh/project" ]; then
    CHECK_PROJECT="${WORK}/round-dsh/project"
  fi
fi

# ════════════════════════════════════════════════════════════════════════
# 5) 三插件面验证（real 与 smoke 均执行；任一面失败不静默）
# ════════════════════════════════════════════════════════════════════════
export FENIX_IT_FRAMEWORK_DIR="${FW}"
export FENIX_IT_PROJECT="${CHECK_PROJECT}"
export FENIX_IT_SPEC_NAME="${SPEC_NAME}"
export FENIX_IT_DASH_PORT="${DASH_PORT}"
export FENIX_IT_ARTIFACTS_DIR="${ART}"

log "── 三插件面验证 ──"
if bash /opt/it/checks/check_skills.sh >>"${LOG}" 2>&1; then
  FACE_STATUS[skills]=pass; log "skills 面: pass"
else
  FACE_STATUS[skills]=fail; record_failure "skills 插件面失败（详见 orchestrate.log 中 check_skills 输出）"
fi

if bash /opt/it/checks/check_dashboard.sh >>"${LOG}" 2>&1; then
  FACE_STATUS[dashboard]=pass; log "dashboard 面: pass"
else
  FACE_STATUS[dashboard]=fail; record_failure "dashboard 插件面失败（详见 orchestrate.log 中 check_dashboard 输出）"
fi

if python3 /opt/it/checks/check_dsh_web.py >>"${LOG}" 2>&1; then
  FACE_STATUS[dsh_web]=pass; log "dsh web 面: pass"
else
  FACE_STATUS[dsh_web]=fail; record_failure "dsh web 插件面失败（详见 orchestrate.log 中 check_dsh_web 输出）"
fi

# ── 汇总判定 ──────────────────────────────────────────────────────────────
all_green=1
for line in "${ROUND_LINES[@]-}"; do
  status_field="${line#*|}"; status_field="${status_field%%|*}"
  [ "${status_field}" = "pass" ] || all_green=0
done
for key in skills dashboard dsh_web; do
  [ "${FACE_STATUS[${key}]:-}" = "pass" ] || all_green=0
done

if [ "${all_green}" -eq 1 ]; then
  log "全部判定通过（轮次 + 三插件面）"
  finish 0
else
  log "存在失败判定（${#FAILURES[@]} 条失败明细）"
  finish 1
fi
