#!/usr/bin/env bash
# =============================================================================
# dashboard 插件面检查（容器内执行；spec: add-integration-test-env）
# =============================================================================
# 1. 幂等启动 fenix_dashboard.py --serve（已监听则复用）
# 2. 轮询 HTTP 200
# 3. 注册夹具项目（--add-project）后经 /api/projects 接口确认项目可见
# 4. 输出可达 URL
# 失败 fail-loud exit 1。
#
# 依赖环境变量（e2e.sh 注入）:
#   FENIX_IT_FRAMEWORK_DIR  容器内框架克隆目录
#   FENIX_IT_PROJECT        夹具项目目录
#   FENIX_IT_DASH_PORT      dashboard 端口（默认 8787）
#   FENIX_IT_ARTIFACTS_DIR  产物目录（dashboard 日志落此）
# =============================================================================
set -uo pipefail

FW="${FENIX_IT_FRAMEWORK_DIR:?check_dashboard 需 FENIX_IT_FRAMEWORK_DIR}"
PROJECT="${FENIX_IT_PROJECT:?check_dashboard 需 FENIX_IT_PROJECT}"
PORT="${FENIX_IT_DASH_PORT:-8787}"
ART="${FENIX_IT_ARTIFACTS_DIR:-/artifacts}"
BASE="http://127.0.0.1:${PORT}"

echo "── check_dashboard: dashboard 插件面 ──"

# 1) 幂等启动：已监听则复用
if curl -sf "${BASE}/api/projects" -o /dev/null 2>/dev/null; then
  echo "  ✅ dashboard 已在 ${BASE} 监听，复用既有实例"
else
  (cd "${FW}" && nohup python3 bin/fenix_dashboard.py --serve --port "${PORT}" \
      >>"${ART}/dashboard.log" 2>&1 & echo $! >"${ART}/dashboard.pid")
  echo "  · 已启动 dashboard（pid=$(cat "${ART}/dashboard.pid")），轮询就绪…"
fi

# 2) 轮询 HTTP 200（/api/projects 接口；60s 上限）
ok=0
for i in $(seq 1 60); do
  code="$(curl -s -o /dev/null -w '%{http_code}' "${BASE}/api/projects" 2>/dev/null || echo 000)"
  if [ "${code}" = "200" ]; then ok=1; break; fi
  sleep 1
done
if [ "${ok}" -ne 1 ]; then
  echo "  ❌ dashboard 60s 内未就绪（最后状态码 ${code}），日志尾部:"
  tail -5 "${ART}/dashboard.log" 2>/dev/null | sed 's/^/     /' || true
  exit 1
fi
echo "  ✅ dashboard HTTP 200: ${BASE}/api/projects"

# 3) 注册夹具项目（幂等，按路径去重）
if ! (cd "${FW}" && python3 bin/fenix_dashboard.py --add-project "${PROJECT}" >/tmp/ck_dash_add.out 2>&1); then
  echo "  ❌ --add-project 注册失败"
  echo "     原始错误: $(head -c 300 /tmp/ck_dash_add.out | tr '\n' ' ')"
  exit 1
fi
echo "  ✅ 夹具项目已注册: ${PROJECT}"

# 4) 经 dashboard 接口确认项目可见（注册表可能带 TTL 缓存，轮询 30s）
pname="$(basename "${PROJECT}")"
ok=0
for i in $(seq 1 30); do
  if curl -sf "${BASE}/api/projects" 2>/dev/null | python3 -c "
import json, sys
data = json.load(sys.stdin)
items = data.get('projects', data) if isinstance(data, dict) else data
sys.exit(0 if any('${PROJECT}' in str(p) or '${pname}' == str(p.get('name', '')) for p in items) else 1)
" 2>/dev/null; then
    ok=1; break
  fi
  sleep 1
done
if [ "${ok}" -ne 1 ]; then
  echo "  ❌ /api/projects 中未见夹具项目（${pname}）"
  curl -s "${BASE}/api/projects" 2>/dev/null | head -c 400 || true
  exit 1
fi
echo "  ✅ 夹具项目经 /api/projects 可见"

echo "check_dashboard: 全部通过，可达 URL: ${BASE}"
exit 0
