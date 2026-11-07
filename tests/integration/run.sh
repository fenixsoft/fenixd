#!/usr/bin/env bash
# =============================================================================
# fenixd 集成测试一键入口（宿主侧；spec: add-integration-test-env）
# =============================================================================
# 用法:
#   tests/integration/run.sh                 # 真实模式：双 harness 各跑一轮 e2e（需 LLM 凭据）
#   tests/integration/run.sh --smoke         # 免凭据模式：镜像自检 + 克隆安装 + 夹具 + 三插件面
#   tests/integration/run.sh --build-only    # 仅构建/预热镜像
#
# 环境变量契约（设计 D3）:
#   FENIX_IT_LLM_BASE_URL / FENIX_IT_LLM_API_KEY / FENIX_IT_LLM_MODEL
#       LLM 三要素；真实模式必填（缺项 exit 2 零动作）。claude 轮映射
#       ANTHROPIC_BASE_URL/AUTH_TOKEN/MODEL，dsh 轮映射 bundle 模型显式配置三要素。
#   FENIX_IT_GIT_REPO    默认 https://github.com/fenixsoft/fenixd.git
#       框架克隆源。特殊形态：值为主机上已存在的目录路径时，改为只读挂载该
#       目录进容器并从本地路径克隆（离线/无 GitHub 场景的开发替代，行为仍为
#       「运行期克隆、框架不入镜像」）。
#   FENIX_IT_GIT_REF     默认 main
#   FENIX_IT_PLUGINS_REPO 默认宿主 /root/dsh-plugins（存在时）；否则必填
#       dsh 面板桥插件源：宿主目录路径（挂载进容器）或 git URL（容器内克隆）。
#   FENIX_IT_TIMEOUT     真实模式每轮秒数（默认 3600；smoke 900）
#   FENIX_IT_ARTIFACTS_DIR 产物目录，默认 <repo>/.history/integration-runs/<UTC时间戳>/
#   构建期源镜像（官方源停滞时传国内镜像，缺省空串=官方源）:
#     FENIX_IT_APT_MIRROR   apt 源站 origin（如 http://mirrors.aliyun.com）
#     FENIX_IT_NPM_REGISTRY npm registry（如 https://registry.npmmirror.com）
#     FENIX_IT_PIP_INDEX    PyPI index（如 https://mirrors.aliyun.com/pypi/simple）
#
# 退出码: 0=全绿; 1=判定失败（摘要含失败明细）; 2=用法/装置错误。
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

MODE="real"          # real | smoke
BUILD_ONLY=0

for arg in "$@"; do
  case "${arg}" in
    --smoke)      MODE="smoke" ;;
    --build-only) BUILD_ONLY=1 ;;
    -h|--help)    sed -n '3,30p' "$0"; exit 0 ;;
    *) echo "未知参数: ${arg}（支持 --smoke / --build-only / --help）" >&2; exit 2 ;;
  esac
done

log()  { echo "[run.sh] $*"; }
die2() { echo "[run.sh] 装置/用法错误: $*" >&2; exit 2; }

# ── 环境变量契约解析 ────────────────────────────────────────────────────────
GIT_REPO="${FENIX_IT_GIT_REPO:-https://github.com/fenixsoft/fenixd.git}"
GIT_REF="${FENIX_IT_GIT_REF:-main}"
PLUGINS_REPO="${FENIX_IT_PLUGINS_REPO:-}"
if [ -z "${PLUGINS_REPO}" ] && [ -d /root/dsh-plugins ]; then
  PLUGINS_REPO=/root/dsh-plugins
fi
TIMEOUT="${FENIX_IT_TIMEOUT:-}"
if [ -z "${TIMEOUT}" ]; then
  if [ "${MODE}" = "smoke" ]; then TIMEOUT=900; else TIMEOUT=3600; fi
fi

if [ -n "${FENIX_IT_ARTIFACTS_DIR:-}" ]; then
  ARTIFACTS="${FENIX_IT_ARTIFACTS_DIR}"
else
  ARTIFACTS="${REPO_ROOT}/.history/integration-runs/$(date -u +%Y%m%dT%H%M%SZ)"
fi

# ── Docker 装置检查（exit 2 语义：装置错误）────────────────────────────────
command -v docker >/dev/null 2>&1 || die2 "docker CLI 不可用（请安装 Docker 后重试）"
docker info >/dev/null 2>&1 || die2 "Docker daemon 不可达（docker info 失败；请确认 daemon 已启动）"

# ── 镜像构建/复用：tag = Dockerfile 内容哈希 ───────────────────────────────
IMAGE_HASH="$(sha256sum "${SCRIPT_DIR}/Dockerfile" | cut -c1-12)"
IMAGE_TAG="fenix-it-env:${IMAGE_HASH}"

# FENIX_IT_APT_MIRROR：构建期 apt 源镜像（官方 deb.debian.org 在部分网络停滞时
# 传国内镜像加速，如 https://mirrors.aliyun.com/debian）；缺省空串=官方源。
image_build() {
  local bargs=()
  [ -n "${FENIX_IT_APT_MIRROR:-}" ] && bargs+=(--build-arg "APT_MIRROR=${FENIX_IT_APT_MIRROR}")
  [ -n "${FENIX_IT_NPM_REGISTRY:-}" ] && bargs+=(--build-arg "NPM_REGISTRY=${FENIX_IT_NPM_REGISTRY}")
  [ -n "${FENIX_IT_PIP_INDEX:-}" ] && bargs+=(--build-arg "PIP_INDEX_URL=${FENIX_IT_PIP_INDEX}")
  (cd "${SCRIPT_DIR}" && docker build -t "${IMAGE_TAG}" "${bargs[@]}" .) \
    || die2 "镜像构建失败（构建期错误属装置/网络面，exit 2）"
}

# --build-only 只做镜像预热、无需凭据，在凭据自检之前短路。
if [ "${BUILD_ONLY}" -eq 1 ]; then
  if docker image inspect "${IMAGE_TAG}" >/dev/null 2>&1; then
    log "镜像已存在，跳过构建: ${IMAGE_TAG}（强制重建请先 docker rmi ${IMAGE_TAG}）"
  else
    log "构建镜像: ${IMAGE_TAG}（分层缓存，低频变动层命中时仅增补高频层）"
    image_build
  fi
  log "预热完成: ${IMAGE_TAG}"
  log "后续步骤: tests/integration/run.sh --smoke  →  注入凭据后 tests/integration/run.sh"
  exit 0
fi

if [ "${MODE}" = "real" ]; then
  missing=()
  [ -n "${FENIX_IT_LLM_BASE_URL:-}" ] || missing+=("FENIX_IT_LLM_BASE_URL")
  [ -n "${FENIX_IT_LLM_API_KEY:-}" ]  || missing+=("FENIX_IT_LLM_API_KEY")
  [ -n "${FENIX_IT_LLM_MODEL:-}" ]    || missing+=("FENIX_IT_LLM_MODEL")
  if [ "${#missing[@]}" -gt 0 ]; then
    echo "[run.sh] 真实模式缺少 LLM 凭据环境变量（未发起任何容器/克隆/网络动作）:" >&2
    for m in "${missing[@]}"; do
      echo "  - ${m}" >&2
    done
    cat >&2 <<'EOF'
修复指引:
  export FENIX_IT_LLM_BASE_URL=https://<gateway>/v1   # OpenAI 兼容端点
  export FENIX_IT_LLM_API_KEY=sk-xxx                  # 不落盘，仅注入容器 env
  export FENIX_IT_LLM_MODEL=<model-id>
  tests/integration/run.sh
免凭据验证请使用: tests/integration/run.sh --smoke
EOF
    exit 2
  fi
fi

# ── dsh web 插件源前置检查（smoke/real 均需；缺席 fail-loud 由容器内上报）──
if [ -z "${PLUGINS_REPO}" ]; then
  log "警告: 未提供 FENIX_IT_PLUGINS_REPO 且宿主 /root/dsh-plugins 不存在；"
  log "       dsh web 插件面将在容器内按设计 fail-loud（不静默降级）。"
fi

# ── 镜像构建/复用（tag 已在上方按内容哈希确定）────────────────────────────
if ! docker image inspect "${IMAGE_TAG}" >/dev/null 2>&1; then
  log "本地无镜像 ${IMAGE_TAG}，先构建（等价 --build-only 预热）"
  image_build
fi

# ── 产物目录（宿主侧创建；读写卷挂至容器 /artifacts）───────────────────────
mkdir -p "${ARTIFACTS}"
log "产物目录: ${ARTIFACTS}"

# ── 挂载与容器内变量换算 ───────────────────────────────────────────────────
# /opt/it 只读挂载编排脚本；产物仅能经 /artifacts 卷落回宿主（D2）。
MOUNT_ARGS=( -v "${SCRIPT_DIR}:/opt/it:ro" -v "${ARTIFACTS}:/artifacts" )
ENV_ARGS=(
  -e FENIX_IT_MODE="${MODE}"
  -e FENIX_IT_GIT_REF="${GIT_REF}"
  -e FENIX_IT_TIMEOUT="${TIMEOUT}"
  -e FENIX_IT_ARTIFACTS_DIR=/artifacts
)

# FENIX_IT_GIT_REPO 目录形态：只读挂载进容器，容器内克隆源换算为挂载路径
#（默认 git URL 形态原样传入，由容器内 e2e.sh 克隆）。
# 挂载目标取 git 共享对象库（--git-common-dir）而非目录本身：worktree 的
# .git 是指向宿主 gitdir 的文件指针，容器内不存在宿主路径，直接挂工作树
# 会导致容器内 clone 报 not a git repository；普通仓的 common dir 即 <根>/.git，
# 两种形态统一，且 git clone 支持直接以 gitdir 路径为源（无需源工作树）。
CONTAINER_GIT_REPO="${GIT_REPO}"
if [ -d "${GIT_REPO}" ]; then
  COMMON_DIR="$(cd "${GIT_REPO}" && git rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" \
    || die2 "FENIX_IT_GIT_REPO 目录不是 git 仓库: ${GIT_REPO}"
  CONTAINER_GIT_REPO=/opt/framework-src
  MOUNT_ARGS+=( -v "${COMMON_DIR}:${CONTAINER_GIT_REPO}:ro" )
  log "框架源挂载（git 共享对象库）: ${COMMON_DIR} → ${CONTAINER_GIT_REPO}"
fi
ENV_ARGS+=( -e FENIX_IT_GIT_REPO="${CONTAINER_GIT_REPO}" )

# FENIX_IT_PLUGINS_REPO 目录形态：同样只读挂载；git URL 形态原样传入。
CONTAINER_PLUGINS_REPO="${PLUGINS_REPO}"
if [ -n "${PLUGINS_REPO}" ] && [ -d "${PLUGINS_REPO}" ]; then
  REAL_PLUGINS_DIR="$(cd "${PLUGINS_REPO}" && pwd)"
  CONTAINER_PLUGINS_REPO=/opt/plugins-src
  MOUNT_ARGS+=( -v "${REAL_PLUGINS_DIR}:${CONTAINER_PLUGINS_REPO}:ro" )
  ENV_ARGS+=( -e FENIX_IT_PLUGINS_REPO="${CONTAINER_PLUGINS_REPO}" )
  log "插件仓宿主目录挂载: ${REAL_PLUGINS_DIR} → ${CONTAINER_PLUGINS_REPO}"
else
  ENV_ARGS+=( -e FENIX_IT_PLUGINS_REPO="${CONTAINER_PLUGINS_REPO}" )
fi

# 真实模式注入 LLM 三要素（仅容器 env，不落任何盘上文件）
if [ "${MODE}" = "real" ]; then
  ENV_ARGS+=(
    -e FENIX_IT_LLM_BASE_URL="${FENIX_IT_LLM_BASE_URL}"
    -e FENIX_IT_LLM_API_KEY="${FENIX_IT_LLM_API_KEY}"
    -e FENIX_IT_LLM_MODEL="${FENIX_IT_LLM_MODEL}"
  )
fi

# ── 总预算兜底：每轮 TIMEOUT + 编排开销；超时强杀容器并判失败 ───────────────
if [ "${MODE}" = "smoke" ]; then
  TOTAL_BUDGET=$(( TIMEOUT + 1800 ))    # smoke：单轮 + 前端构建/GUI 余量
else
  TOTAL_BUDGET=$(( TIMEOUT * 2 + 1800 ))  # real：双轮 + 克隆安装/构建余量
fi
CNAME="fenix-it-$(date -u +%H%M%S)"

cleanup() {
  docker rm -f "${CNAME}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

log "启动容器: docker run --name ${CNAME}（模式=${MODE}，每轮预算=${TIMEOUT}s，总兜底=${TOTAL_BUDGET}s）"
set +e
timeout -k 60 "${TOTAL_BUDGET}" docker run --name "${CNAME}" \
  "${MOUNT_ARGS[@]}" "${ENV_ARGS[@]}" \
  "${IMAGE_TAG}" bash /opt/it/e2e.sh
rc=$?
set -e

case "${rc}" in
  0) log "集成运行全绿。产物: ${ARTIFACTS}/summary.json" ;;
  2) log "容器内上报用法/装置错误（exit 2）。产物: ${ARTIFACTS}/" ;;
  124|137) log "总预算超时（${TOTAL_BUDGET}s），容器已强杀，按判定失败处置（exit 1）。产物: ${ARTIFACTS}/" ;;
  *) log "集成运行为判定失败（exit ${rc}）。明细见 ${ARTIFACTS}/summary.json 与日志" ;;
esac

if [ ! -f "${ARTIFACTS}/summary.json" ]; then
  log "警告: summary.json 未落盘（容器早期崩溃）——以编排日志为失败证据，按判定失败处置"
  # if 形态保证条件为假时返回 0，不污染下方 exit 的真实退出码
  if [ "${rc}" -eq 0 ]; then rc=1; fi
fi

exit "${rc}"
