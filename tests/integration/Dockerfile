# =============================================================================
# fenixd 集成测试环境镜像（tests/integration，spec: add-integration-test-env）
# =============================================================================
# 纯环境镜像：双 harness CLI（claude code + dsh）、Playwright + Chromium、
# 基础工具链。fenix 框架代码不烘入（运行期由 e2e.sh 从 FENIX_IT_GIT_REPO
# 克隆）；LLM baseurl/key/model 全部运行期经环境变量注入，镜像内零凭据。
#
# 构建入口：tests/integration/run.sh --build-only（或 docker build 直接执行）。
# 镜像 tag 由 run.sh 按 Dockerfile 内容哈希生成（fenix-it-env:<hash>）。
# =============================================================================
FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    # bookworm pip 默认 PEP 668 externally-managed：框架 install.sh 的补装
    # （pyyaml/httpx/jsonschema）不带 --break-system-packages，经此 env 放行
    PIP_BREAK_SYSTEM_PACKAGES=1 \
    # Playwright 浏览器下载源：官方 CDN 在部分网络环境被网关拦截，
    # npmmirror 镜像路径实测可达（同源二进制）。网络可用官方源时可覆盖。
    PLAYWRIGHT_DOWNLOAD_HOST=https://cdn.npmmirror.com/binaries/playwright

# ── 层 1：系统包（低频变动在前，最大化层缓存命中）──────────────────────────
# APT_MIRROR 构建参数：官方 deb.debian.org 在部分网络环境（CN/Fastly）下载
# 停滞，可传国内镜像（如 https://mirrors.aliyun.com/debian）加速；缺省空串
# = 保持官方源。镜像仅替换域名，deb822（debian.sources）与传统格式双兼容。
ARG APT_MIRROR=""
RUN if [ -n "${APT_MIRROR}" ]; then \
      for f in /etc/apt/sources.list.d/debian.sources /etc/apt/sources.list; do \
        [ -f "$f" ] && sed -i "s|http://deb.debian.org|${APT_MIRROR}|g" "$f" || true; \
      done; \
    fi \
    && apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        tmux \
        python3 \
        python3-venv \
        python3-pip \
        build-essential \
        libnss3 \
        libnspr4 \
        libatk1.0-0 \
        libatk-bridge2.0-0 \
        libcups2 \
        libdrm2 \
        libxkbcommon0 \
        libxcomposite1 \
        libxdamage1 \
        libxfixes3 \
        libxrandr2 \
        libgbm1 \
        libasound2 \
        libpango-1.0-0 \
        libcairo2 \
        libatspi2.0-0 \
        fonts-liberation \
        fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

# ── 层 2：Node 20（NodeSource）+ pnpm ──────────────────────────────────────
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g pnpm \
    && npm config set fund false --global \
    && npm config set audit-level moderate --global

# ── 层 3：双 harness CLI（全局安装；dsh 版本钉扎 0.2.0-rc.2）───────────────
# @deepseek-ai/dsh 含原生模块（node-pty 等），依赖上层 build-essential + python3。
RUN npm install -g --no-audit --no-fund \
        @anthropic-ai/claude-code \
        @deepseek-ai/dsh@0.2.0-rc.2

# ── 层 4：Playwright + Chromium（含系统依赖）──────────────────────────────
RUN pip3 install --break-system-packages playwright \
    && python3 -m playwright install --with-deps chromium

# ── 运行期挂载点（D2）：/opt/it=编排脚本(ro)、/artifacts=产物卷(rw)、
# /work=容器内工作区（框架克隆、夹具项目、DSH_HOME 隔离目录）。
RUN mkdir -p /opt/it /artifacts /work
WORKDIR /work

# 镜像自检缺省命令：打印双 harness 与 Playwright 版本（--smoke 镜像自检同款）。
CMD ["/bin/bash", "-lc", "claude --version && dsh --version && python3 --version && node --version && python3 -m playwright --version"]
