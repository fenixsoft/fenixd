#!/usr/bin/env bash
# =============================================================================
# fenixd 打包脚本
# =============================================================================
# 将 fenixd 框架打包为可分发的 tar.gz 包。
# 包含完整的 Python 框架、Dashboard（静态资源）、skills、安装脚本。
#
# 用法: bash scripts/package.sh
# 输出: dist/fenixd-<version>.tar.gz
# =============================================================================
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="${ROOT_DIR}/dist"
VERSION="$(date +%Y%m%d)"
PKG_NAME="fenixd-${VERSION}"
PKG_DIR="${DIST_DIR}/${PKG_NAME}"

echo "================================================================"
echo "  fenixd 打包"
echo "  版本: ${VERSION}"
echo "  输出: ${DIST_DIR}/${PKG_NAME}.tar.gz"
echo "================================================================"

# ── 清理 ──────────────────────────────────────────────────────
rm -rf "${PKG_DIR}"
mkdir -p "${PKG_DIR}"

# ── 复制文件 ──────────────────────────────────────────────────
echo "── 复制框架文件 ──"

# 核心 Python 代码
cp -r "${ROOT_DIR}/core" "${PKG_DIR}/core"

# Dashboard 静态资源
mkdir -p "${PKG_DIR}/core/dashboard/static"
cp -r "${ROOT_DIR}/core/dashboard/static/"* "${PKG_DIR}/core/dashboard/static/"

# CLI 入口
mkdir -p "${PKG_DIR}/bin"
cp "${ROOT_DIR}/bin/fenix_dashboard.py" "${PKG_DIR}/bin/"
cp "${ROOT_DIR}/bin/fenix_process.py" "${PKG_DIR}/bin/"
cp "${ROOT_DIR}/bin/fenix_session.py" "${PKG_DIR}/bin/"
cp "${ROOT_DIR}/bin/statusline.py" "${PKG_DIR}/bin/"

# Skills
mkdir -p "${PKG_DIR}/skills"
cp -r "${ROOT_DIR}/skills/"* "${PKG_DIR}/skills/" 2>/dev/null || true

# 配置模板
cp "${ROOT_DIR}/config.template.yaml" "${PKG_DIR}/" 2>/dev/null || true

# 安装脚本
cp "${ROOT_DIR}/install.sh" "${PKG_DIR}/"

# README
cp "${ROOT_DIR}/README.md" "${PKG_DIR}/" 2>/dev/null || true

# ── 清理缓存文件 ──────────────────────────────────────────────
find "${PKG_DIR}" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "${PKG_DIR}" -type f -name "*.pyc" -delete 2>/dev/null || true
find "${PKG_DIR}" -type f -name ".DS_Store" -delete 2>/dev/null || true

# ── 打 tar.gz 包 ──────────────────────────────────────────────
echo "── 生成压缩包 ──"
cd "${DIST_DIR}"
tar -czf "${PKG_NAME}.tar.gz" "${PKG_NAME}"
rm -rf "${PKG_DIR}"

SIZE=$(du -h "${DIST_DIR}/${PKG_NAME}.tar.gz" | cut -f1)
echo ""
echo "✅ 打包完成: ${PKG_NAME}.tar.gz (${SIZE})"
echo "   路径: ${DIST_DIR}/${PKG_NAME}.tar.gz"
