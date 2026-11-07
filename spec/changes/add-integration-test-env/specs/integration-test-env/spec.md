# integration-test-env — Docker 集成测试环境与双 harness 端到端验证

## ADDED Requirements

### Requirement: 轻量测试镜像契约
系统 SHALL 提供一份 Dockerfile（位于 `tests/integration/`），基于轻量瘦 Linux 基底镜像构建集成测试镜像，镜像内 MUST 预装：Python 3.10+、Node.js 20+、git、tmux、Playwright 及 Chromium（含系统依赖）、claude code CLI（`@anthropic-ai/claude-code`）与 deepseek harness CLI（`@deepseek-ai/dsh`，版本钉 `0.2.0-rc.2`）。fenix 框架代码 MUST NOT 烘入镜像——框架代码一律在运行期从 GitHub 拉取。LLM 的 baseurl/key/model 等配置 MUST 全部经运行期环境变量从外部注入，MUST NOT 写入镜像层或任何入库文件。

#### Scenario: 镜像构建成功且双 harness CLI 可用
- **WHEN** 在仓库根执行 `tests/integration/run.sh --build-only`（或镜像构建步骤被独立触发）
- **THEN** 镜像构建成功退出；`docker run <image> claude --version` 与 `docker run <image> dsh --version` 均输出版本号，且 dsh 版本为 `0.2.0-rc.2`

#### Scenario: 镜像内不含框架代码且 LLM 配置零残留
- **WHEN** 检查构建产物镜像的文件层
- **THEN** 镜像内不存在 fenixd 框架源码目录（框架只在运行期克隆），镜像与环境变量声明中不存在任何 LLM key 字面值

### Requirement: 一键运行编排契约
系统 SHALL 提供 `tests/integration/run.sh` 作为唯一本地触发入口：构建（或复用）镜像后 `docker run` 启动容器，经环境变量注入外部配置——LLM 三要素（baseurl/key/model，命名 `FENIX_IT_LLM_BASE_URL` / `FENIX_IT_LLM_API_KEY` / `FENIX_IT_LLM_MODEL`）、框架克隆源（默认 `https://github.com/fenixsoft/fenixd.git`，`FENIX_IT_GIT_REPO` / `FENIX_IT_GIT_REF` 可覆盖）、dsh 插件仓地址（`FENIX_IT_PLUGINS_REPO`）与超时预算（`FENIX_IT_TIMEOUT`）。容器内编排 MUST 顺序完成：HTTPS 克隆框架 → 执行 `install.sh` → 创建夹具项目（静态小站模板，git 初始化）→ 依注入配置生成 `.fenix/config.yaml`（provider 与 `agent.harness`）→ 启动 daemon → 程序化注册一个 fast-track 简单 SPEC（静态页可见元素 + 交互，可被 web 验证场景断言）→ 轮询 STATE.md 至终态 → 执行断言。

#### Scenario: 真实模式缺凭据时 fail-loud 且零调用
- **WHEN** 不带 LLM 环境变量执行 `run.sh`（真实模式，未加 `--smoke`）
- **THEN** 脚本在启动任何容器/克隆/真实模型调用之前，输出缺失项清单与修复指引并以非零码退出（对齐 `bin/dsh_acceptance.py accept` 的信号式自检哲学）

#### Scenario: 全链成功闭环
- **WHEN** 注入有效 LLM 配置执行 `run.sh`，夹具 SPEC 被调度实现
- **THEN** 夹具 SPEC 状态机到达 `done`；实现内容经 worktree merge-back 落入夹具项目主干（页面含预期元素）；验证报告为 pass verdict；`.fenix/runs/` 存在 run jsonl 产物；run.sh 以 0 退出

### Requirement: 双 harness 各跑一轮
真实模式下，系统 SHALL 在 claude 与 dsh 两个通道各完整执行一轮夹具 SPEC 闭环（经 `agent.harness` 配置切换），两轮 MUST 使用相互独立的夹具项目实例与独立的超时预算，任一轮失败 MUST NOT 中断另一轮执行；最终汇总两轮判定，任一轮失败则整体非零退出。

#### Scenario: 两轮独立执行并汇总
- **WHEN** 真实模式执行完成
- **THEN** 摘要产物包含 claude 与 dsh 两轮各自的终态、耗时与判定；两轮判定独立；一轮失败时另一轮仍被执行且整体退出码非零

#### Scenario: dsh 轮经 bundle 走 headless 车道
- **WHEN** dsh 轮启动夹具 SPEC 实现
- **THEN** 实现经 fenix-dsh-bundle（`dsh headless`）派发，模型显式配置三要素（provider/baseURL/apiKeyEnv/model）取自注入的环境变量，缺任一要素时该轮 fail-loud

### Requirement: 三插件面安装与使用验证
真实模式与 smoke 模式 MUST 均执行三插件面验证：
1. **skill**：install.sh 装配的 fenix-* skills 在 `~/.claude/skills/` 可见、`fenix-init` 在 PATH、框架 SPEC 生成器（`.fenix/bin/fenix_spec.py`）在夹具项目内可成功运行；
2. **dashboard**：`fenix_dashboard.py --serve` 启动后 HTTP 可达（默认 :8787），夹具项目注册后经 API/页面可见；
3. **dsh web 插件（完整 GUI 验证）**：容器内以 `dsh web` 启动 dsh web 服务，装载源自 dsh-plugins 仓的 fenix-dsh-dashboard-bridge 插件，经 Playwright 打开 dsh web 页面，断言 fenix 面板桥以 iframe（`embed=1` 指向 dashboard 服务）真实挂载且 dashboard 前端在 iframe 内渲染出可断言元素。插件验证任一面失败 MUST fail-loud 报告失败面，MUST NOT 静默跳过。

#### Scenario: skill 与 dashboard 面验证通过
- **WHEN** 容器内完成框架安装与夹具项目初始化后执行插件检查
- **THEN** skills 软链与生成器检查通过；dashboard 服务返回 HTTP 200 且夹具项目可经其接口查询到

#### Scenario: dsh web 面板桥 iframe 挂载断言
- **WHEN** dsh web 服务与 dashboard 服务均在容器内运行、bridge 插件已装载
- **THEN** Playwright 打开 dsh web 页面后能定位 fenix 面板桥注入元素，其 iframe src 含 `embed=1`，且进入 iframe 后能断言 dashboard 前端根节点渲染

#### Scenario: 插件仓不可达时明确报告
- **WHEN** `FENIX_IT_PLUGINS_REPO` 指向的仓库克隆失败或插件构建失败
- **THEN** dsh web 插件面判失败并在摘要中给出失败阶段与原始错误，整体退出码非零（不静默降级为通过）

### Requirement: smoke 免凭据模式
系统 SHALL 提供 `run.sh --smoke` 模式：不执行任何真实 LLM 调用与 SPEC 闭环轮次，仅完成镜像环境自检（双 harness CLI、Playwright、基础工具）、框架克隆与安装、夹具项目创建与 daemon 启动、三插件面验证（含 dsh web 完整 GUI 挂载断言），全部通过后以 0 退出。该模式 MUST 可在无 LLM 凭据的环境下重复执行，并作为本 SPEC 自身验证场景的确定性执行目标。

#### Scenario: smoke 模式免凭据全绿
- **WHEN** 在仅构建好镜像、未注入任何 LLM 凭据的环境执行 `run.sh --smoke`
- **THEN** 镜像自检、克隆安装、夹具初始化、daemon 启动与三插件面验证全部通过，退出码 0

#### Scenario: smoke 模式被验证引擎复用
- **WHEN** 本 SPEC 进入验证阶段，验证场景以 CLI 形态执行 `tests/integration/run.sh --smoke`
- **THEN** 该命令成为本 SPEC 验证场景的可断言执行目标，退出码即判定依据

### Requirement: 产物落盘与退出码契约
每轮运行 MUST 在宿主机挂载目录落盘产物：运行摘要 JSON（含模式、两轮终态/耗时/判定、三插件面结果）、daemon 与编排日志、验证报告、dsh web GUI 截图。产物默认输出至 `.history/integration-runs/<时间戳>/`（遵循仓库临时文件约定，gitignored，`FENIX_IT_ARTIFACTS_DIR` 可覆盖）。退出码契约：0=全绿；1=判定失败（fail-loud，摘要内含失败明细）；2=用法/装置错误。

#### Scenario: 产物完整落盘
- **WHEN** 任一轮运行结束（无论成败）
- **THEN** 挂载目录下存在摘要 JSON、日志与（GUI 验证执行时的）截图文件，摘要 JSON 可被 `python3 -c "import json;json.load(...)"` 解析且包含模式与各轮判定字段

#### Scenario: 退出码语义
- **WHEN** 集成运行以不同结局结束
- **THEN** 全绿退出 0；任一判定失败退出 1 且摘要含失败明细；参数/环境装置错误（如 Docker 不可用）退出 2
