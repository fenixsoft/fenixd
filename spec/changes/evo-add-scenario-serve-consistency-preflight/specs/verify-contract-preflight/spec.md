# verify-contract-preflight Specification

## Purpose

场景集含 api/web 场景（需被验证应用可服务）而验证契约缺 serve 段时，缺口推迟到验证执行期才以「应用不可达」fail-fast 暴露（实测 3 轮空转 + spec blocked 约 51 分钟等契约补课，且 3 条 verify_contract_missing 信号被宽松前置探测错误闭环）。本能力把「场景 kind 集合 ⊆ 契约 serve/start 能力」的一致性校验前移到出题产物消费期，并收紧 verify_contract_missing 的免唤起前置探测，使确定性配置缺口在出题期打回而非验证期 env-block。

## Requirements

### Requirement: 契约静态检查覆盖 serve 缺失与非 cli 场景的交叉形态

契约静态检查（scan_contract）MUST 支持在契约 serve 段缺失（serve 为 None）时检查场景 kind 集合与 commands.start 兜底：场景集含 api 或 web 场景、serve 缺失且 commands.start 无有效兜底（空或占位哨兵，判定口径与验证执行期 serving.py:1098-1099 旧行为一致）MUST 报 serve 缺失 finding；serve 缺失但 commands.start 非占位（执行期 commands.start 旧行为可兜底的存量形态）MUST NOT 报；serve 段存在时既有三条规则（serve_entry_missing / serve_entry_vs_start_mismatch / serve_entry_no_port_injection）语义不变。

#### Scenario: api/web 场景遇无 serve 契约

- **WHEN** 出题产物场景 kind 集合含 api 或 web，且契约无 serve 段、commands.start 无有效兜底（空或占位哨兵）
- **THEN** 静态检查报 serve 缺失 finding，出题产物验收不通过、打回补契约

#### Scenario: 纯 cli 场景维持合法

- **WHEN** 出题产物场景全为 cli 且契约无 serve 段（历史纯 CLI 项目形态）
- **THEN** 不报 serve 缺失，检查通过（cimbar-airgap-transfer 形态不回归）

#### Scenario: start 非占位的无 serve 存量形态维持合法

- **WHEN** 出题产物场景 kind 集含 api 或 web，契约无 serve 段，但 config commands.start 为非占位命令（执行期 commands.start 旧行为可兜底）
- **THEN** 不报 serve 缺失（与验证执行期「serve（或 commands.start 兜底）必须有效」口径一致，存量零迁移）

### Requirement: 静态检查挂载覆盖冻结复用与并行产物路径

契约静态检查 MUST 在新鲜出题验收、冻结场景复用、并行出题产物消费三类路径上统一执行，任一路径的出题产物不得绕过 serve 一致性检查。

#### Scenario: 冻结复用路径产物被检查

- **WHEN** spec 场景走冻结场景复用或并行出题产物短路路径进入消费
- **THEN** 消费前同样执行契约静态检查，kind 集与契约能力不匹配时打回

### Requirement: verify_contract_missing 免唤起前置探测收紧

前置探测对 verify_contract_missing 信号的满足判定 MUST 不再只验「契约可解析」：须验契约 serve/start 能力（serve 段存在或 commands.start 非占位）可覆盖在途场景的 kind 需求，能力缺口未补齐时 MUST NOT auto-resolve。

#### Scenario: 契约可解析但能力未补

- **WHEN** verify_contract_missing 信号 open、契约文件可解析但无 serve 段，而在途场景集含 api/web
- **THEN** 前置探测不判满足，信号保持 open，正常进入 administrator 唤起流程

#### Scenario: 契约补齐后免唤起恢复

- **WHEN** 契约已含 serve 段且可覆盖在途 kind 需求（或 start 非占位且场景全 cli）
- **THEN** 前置探测判满足，免唤起行为与既有语义一致