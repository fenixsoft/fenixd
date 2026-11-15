#!/usr/bin/env bash
# =============================================================================
# fenixd 打包脚本
# =============================================================================
# 将 fenixd 框架打包为可分发的制品包（tar.gz + zip + sha256）。
# 包含完整部署面：Python 框架（core/ + 全量 bin/）、Dashboard 预构建静态资源、
# skills、fenix-init、双平台安装脚本（install.sh + install.ps1）、docs、
# dsh-bundle（含预构建 dist/）——install.md 的制品安装路径即消费本包。
#
# 用法: bash scripts/package.sh [version]（缺省日期版本；GitHub workflow 传 tag 名）
# 输出: dist/fenixd-<version>.tar.gz / .zip / .sha256
# =============================================================================
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="${ROOT_DIR}/dist"
VERSION="${1:-$(date +%Y%m%d)}"
PKG_NAME="fenixd-${VERSION}"
PKG_DIR="${DIST_DIR}/${PKG_NAME}"

echo "================================================================"
echo "  fenixd 打包"
echo "  版本: ${VERSION}"
echo "  输出: ${DIST_DIR}/${PKG_NAME}.tar.gz + .zip + .sha256"
echo "================================================================"

# ── 清理 ──────────────────────────────────────────────────────
rm -rf "${PKG_DIR}"
mkdir -p "${PKG_DIR}"

# ── 复制文件 ──────────────────────────────────────────────────
echo "── 复制框架文件 ──"

# 核心 Python 代码（含 dashboard static 源码与预构建 dist/）
cp -r "${ROOT_DIR}/core" "${PKG_DIR}/core"

# 全量 bin/（fenix_*.py 命令面 + fenixd_supervisor.py 守护 + dsh_acceptance.py
# 验收器——daemon/NSSM 承载与 §9.5 验收均依赖，缺一不可）
cp -r "${ROOT_DIR}/bin" "${PKG_DIR}/bin"

# Skills（8 个 fenix-* skill 目录）
mkdir -p "${PKG_DIR}/skills"
cp -r "${ROOT_DIR}/skills/"* "${PKG_DIR}/skills/" 2>/dev/null || true

# fenix-init 项目骨架生成器（install.sh/install.ps1 部署到 PATH）
cp "${ROOT_DIR}/fenix-init" "${PKG_DIR}/" 2>/dev/null || true

# 双平台安装脚本
cp "${ROOT_DIR}/install.sh" "${PKG_DIR}/" 2>/dev/null || true
cp "${ROOT_DIR}/install.ps1" "${PKG_DIR}/" 2>/dev/null || true

# docs（install.md 即部署手册本体；help/ 为排障与桥接文档）
mkdir -p "${PKG_DIR}/docs"
cp -r "${ROOT_DIR}/docs/"* "${PKG_DIR}/docs/" 2>/dev/null || true

# dsh-bundle（headless 通道制品；dist/ 预构建——CI 先 build 再打包，
# 源码使用者可按 package.json 自行重建）
if [ -d "${ROOT_DIR}/dsh-bundle" ]; then
  mkdir -p "${PKG_DIR}/dsh-bundle"
  (cd "${ROOT_DIR}/dsh-bundle" && \
    tar -cf - --exclude='node_modules' --exclude='.git' \
      --exclude='__pycache__' --exclude='*.pyc' .) \
    | (cd "${PKG_DIR}/dsh-bundle" && tar -xf -)
fi

# 配置模板（已迁入 .fenix/，打包保留根层等价路径以兼容旧安装脚本）
cp "${ROOT_DIR}/.fenix/config.template.yaml" "${PKG_DIR}/" 2>/dev/null || true

# V2 dev-server（add-worktree-test-server）
mkdir -p "${PKG_DIR}/tests/v2"
cp "${ROOT_DIR}/tests/v2/dev-server.mjs" "${PKG_DIR}/tests/v2/" 2>/dev/null || true
cp "${ROOT_DIR}/tests/v2/playwright.config.js" "${PKG_DIR}/tests/v2/" 2>/dev/null || true

# README + 版本标识
cp "${ROOT_DIR}/README.md" "${PKG_DIR}/" 2>/dev/null || true
printf '%s\n' "${VERSION}" > "${PKG_DIR}/VERSION"

# ── 清理缓存文件 ──────────────────────────────────────────────
find "${PKG_DIR}" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "${PKG_DIR}" -type d -name "node_modules" -exec rm -rf {} + 2>/dev/null || true
find "${PKG_DIR}" -type f -name "*.pyc" -delete 2>/dev/null || true
find "${PKG_DIR}" -type f -name ".DS_Store" -delete 2>/dev/null || true

# ── 打包（tar.gz 给 Linux/macOS，zip 给 Windows Expand-Archive）──
echo "── 生成压缩包 ──"
cd "${DIST_DIR}"
tar -czf "${PKG_NAME}.tar.gz" "${PKG_NAME}"
# zip 内保持顶层目录一致（解压后同 tar 形态）
zip -qry "${PKG_NAME}.zip" "${PKG_NAME}"
rm -rf "${PKG_DIR}"

# ── 校验和 ────────────────────────────────────────────────────
sha256sum "${PKG_NAME}.tar.gz" "${PKG_NAME}.zip" > "${PKG_NAME}.sha256"

SIZE_T=$(du -h "${DIST_DIR}/${PKG_NAME}.tar.gz" | cut -f1)
SIZE_Z=$(du -h "${DIST_DIR}/${PKG_NAME}.zip" | cut -f1)
echo ""
echo "✅ 打包完成: ${PKG_NAME}.tar.gz (${SIZE_T}) + ${PKG_NAME}.zip (${SIZE_Z})"
echo "   路径: ${DIST_DIR}/${PKG_NAME}.{tar.gz,zip,sha256}"
