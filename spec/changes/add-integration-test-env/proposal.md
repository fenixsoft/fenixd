# Proposal: add-integration-test-env — Docker 集成测试环境与双 harness 端到端验证

## Why

fenixd 目前的质量保障停留在宿主机上的 pytest 单元/回归测试与 `bin/dsh_acceptance.py` 的 dsh 通道冒烟/验收：没有一个「干净机器」视角的端到端验证。框架的真实使用形态是「在一台新机器上装好 harness → 克隆框架 → 初始化项目 → daemon 自动跑完一个 SPEC」——这条全链（安装、插件装配、daemon 调度、fast-track 实现、Playwright 验证、产物落盘）从未在隔离环境中被系统性验证过。框架演进至今已经历上百个 SPEC，任何一次升级都可能在这条链上引入回归而单测无法察觉（如依赖缺失、安装链断裂、harness 配置漂移、dashboard/dsh web 插件装载失败）。

本 SPEC 建立一套基于轻量 Docker 镜像的集成测试环境：镜像内预装 claude code 与 deepseek harness（dsh）两套 Agent 运行时，每次运行从 GitHub 拉取最新 fenix 框架，在夹具项目上注册一个简单 SPEC，验证其被 daemon 自动「实现 → 验证 → done」完整闭环，并确保 skill、dashboard、dsh web 三个插件面可正常安装与使用。这是框架对外可信交付（GitHub 分发形态）的回归底线。

## What Changes

- 新增 `tests/integration/` 集成测试目录（归入既有 tests/ 测试树），包含镜像定义、运行编排、夹具模板与验证脚本，全部自包含、不侵入框架核心代码。
- 新增轻量 Docker 测试镜像（瘦 Linux 基底，python3.11 / Node 20 / git / tmux / Playwright+Chromium 预装；`@anthropic-ai/claude-code` 与 `@deepseek-ai/dsh@0.2.0-rc.2` 两套 harness CLI 预装）。fenix 框架代码**不**烘进镜像——每次运行时按用户确认的 HTTPS 公开克隆方式从 GitHub 拉取（仓库/引用可经环境变量覆盖）。
- 新增一键运行入口 `tests/integration/run.sh`（本地脚本触发，用户已确认不做 CI workflow）：构建/复用镜像 → `docker run` 注入外部 LLM 配置（baseurl/key/model 环境变量）→ 容器内完成「克隆框架 → 安装 → 创建夹具项目 → 注册简单 SPEC → daemon 自动闭环 → 断言产物」全链。
- 双 harness 覆盖（用户已确认）：同一夹具 SPEC 流程在 claude 与 dsh 通道各完整跑一轮（`agent.harness` 切换，独立夹具项目与超时预算），汇总双轮结果。
- 三插件面验证（用户已确认 dsh web 走**完整 GUI 验证**）：
  - **skill**：install.sh 装配的 fenix-* skills 软链存在、fenix-init 入 PATH、框架生成器在夹具项目内可运行；
  - **dashboard**：`fenix_dashboard.py --serve` 起服、HTTP 可达、夹具项目注册可见；
  - **dsh web 插件**：容器内启动 dsh web（`dsh web` profile），装载 fenix-dsh-dashboard-bridge 插件（源自 dsh-plugins 仓，克隆地址可配置），Playwright 断言 fenix 面板桥 iframe 真实挂载渲染（embed=1 指向 dashboard :8787）。
- 运行产物（状态摘要 JSON、daemon 日志、验证报告、GUI 截图）输出到宿主机挂载目录，遵循仓库约定落 `.history/`（gitignored），退出码 fail-loud。
- 新增 `--smoke` 免凭据模式：跳过真实 LLM 轮次，仅做镜像内环境自检 + 三插件装配验证（无需 baseurl/key，可重复、可作本 SPEC 自身验证场景的执行目标）；真实双 harness e2e 轮次需要外部注入 LLM 凭据，属人工/CI 触发步骤。

## Capabilities

### New Capabilities

- `integration-test-env`: Docker 集成测试环境全集——轻量镜像契约（双 harness 预装、LLM 配置外部注入、框架不烘入）、一键运行编排（克隆→安装→夹具→SPEC 闭环→断言）、双 harness 各跑一轮、三插件面验证（skill 装配 / dashboard 服务 / dsh web 面板桥 GUI 挂载）、`--smoke` 免凭据模式与 fail-loud 产物契约。

### Modified Capabilities

<!-- 无：纯新增测试子系统，不改任何既有能力的 spec 级行为。
     既有相关能力（dsh-primary-acceptance 的一键验收、test-engineering 的套件结构）保持不变，
     集成环境作为独立面并存，设计中引用其既有机制不重复造轮子。 -->

## Impact

- **新增文件**：全部位于 `tests/integration/`（Dockerfile、run.sh、容器内编排脚本、夹具模板、插件验证脚本、README），不触碰 `core/`、`bin/`、`skills/` 等既有交付物。
- **运行时依赖**：宿主机需 Docker（本机已有 docker 29.7.1）；容器内依赖经镜像固化；真实 e2e 轮需外部 LLM 端点凭据（baseurl/key/model 环境变量注入，不落盘）。
- **外部资源**：GitHub 上 fenixsoft/fenixd 仓（HTTPS 公开克隆）与 dsh-plugins 仓（面板桥插件源，地址可配置）；npm registry（镜像构建期）。
- **无关面**：不改变 daemon 调度、状态机、验证引擎等任何既有行为；`tests/` 既有 pytest 套件不受影响（集成运行产物落 `.history/`，不产生单测可见副作用）。
- **风险提示**：真实 e2e 轮耗时受模型速度影响（单轮可达数十分钟），run.sh 需可配置超时预算并支持 `--smoke` 快速档。
