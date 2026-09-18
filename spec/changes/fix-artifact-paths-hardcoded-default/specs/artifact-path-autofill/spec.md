## ADDED Requirements

### Requirement: setup 时自动探测并填写产物路径

`fenix-setup` 技能 MUST 在初始化流程中新增一步：用 LLM 探测项目的构建产物路径，
并把结果写入 `.fenix/config.yaml` 的 `worktree.has_build_artifacts` 与
`worktree.build_artifact_paths`。

探测信息源 MUST 至少包含：`package.json` 的 `scripts`（如 `build`）、
`pyproject.toml`、以及项目目录结构（`dist/`、`build/`、`public/`、`static/` 等）。

该步骤 MUST 与既有「生成项目简介」步骤同构（`fenix-setup` 步骤 5）：

- 信息不足或探测失败时 MUST NOT 阻塞后续步骤，MUST 留空两键（交由运行期兜底起草）；
- 该步骤 MUST 幂等：`worktree.has_build_artifacts` 已在配置中显式存在时 MUST 跳过
  （MUST NOT 覆盖人工设置）；
- 写入 MUST 经 `.fenix/config.yaml` 合并（存在则更新对应键，不存在则跳过）。

#### Scenario: 探测到构建脚本时写入产物路径

- **WHEN** 项目 `package.json` 含 `"build": "vite build"` 且目录存在 `dist/`
- **THEN** `.fenix/config.yaml` 的 `worktree.build_artifact_paths` MUST 被写入
  含 `dist/` 的列表
- **AND** `worktree.has_build_artifacts` MUST 被写入 `true`

#### Scenario: 无构建迹象时留空待兜底

- **WHEN** 项目无可识别的构建配置（如纯文档仓库）
- **THEN** 两键 MUST 留空（未裁决），MUST NOT 因探测失败而中止 setup
- **AND** 后续运行期若需要区分产物，信号兜底路径接管

#### Scenario: 已显式配置时跳过不覆盖

- **WHEN** `.fenix/config.yaml` 已含 `worktree.has_build_artifacts`（人工或前次 setup 写入）
- **THEN** 本步骤 MUST 跳过写入，保留既有值

### Requirement: 运行期未裁决时产生起草信号

系统 SHALL 在 merge-back 的 WIP 重叠闸门处，检测到产物配置未裁决时写入信号
`build_artifact_paths_missing`，呼叫 Administrator 起草产物路径配置。

- 触发条件 MUST 为：判定「未裁决」（`has_build_artifacts` 缺省，或 `true` 但路径为空）；
- 触发点 MUST 为 `_wip_overlap_gate`（merge-back 中真正需要区分产物与语义内容的
  咽喉），MUST NOT 在 daemon 启动等无需分类的时机空转触发；
- 触发 MUST NOT 受「本次 merge-back 无 WIP 重叠」影响：判定 MUST 落在该方法的
  「无重叠即早退」分支**之前**（`mergeback.py:155-157`）——主树干净是常态，若早退
  在判定之前，则最常见的形态永不触发起草，缺口重新被静默掩盖；
- 信号 MUST 带 `spec` 字段（本次 merge-back 的 spec 名），evidence 中另附
  「项目名=<name>」作冗余证据；摄取侧对无 spec 的形态仍 MUST 支持从 evidence 解析；
- 已裁决（`has_build_artifacts=false` 或路径非空）时 MUST NOT 写信号；
- 在途去重 MUST 生效：同项目同 signal_type 的未消费信号已存在时 MUST NOT 重复写。

#### Scenario: 未裁决时闸门产生信号

- **WHEN** merge-back 进入 WIP 重叠闸门，且该 spec 所属项目产物配置未裁决
- **THEN** 系统 MUST 写一条 `build_artifact_paths_missing` 信号，携带 `spec`
  字段并在 evidence 中附项目名
- **AND** 闸门 MUST 按既有策略继续（本信号不改变闸门判定，只呼叫起草）
- **AND** 该触发 MUST 同样成立于「主树干净、无 WIP 重叠」的形态（判定不在早退之后）

#### Scenario: 已声明无产物时不产生信号

- **WHEN** 项目 `has_build_artifacts=false`，merge-back 进入 WIP 重叠闸门
- **THEN** 系统 MUST NOT 写 `build_artifact_paths_missing` 信号

#### Scenario: 已配置路径时不产生信号

- **WHEN** 项目 `build_artifact_paths=["dist/"]`，merge-back 进入 WIP 重叠闸门
- **THEN** 系统 MUST NOT 写 `build_artifact_paths_missing` 信号

#### Scenario: 在途信号去重

- **WHEN** 同项目已有未消费的 `build_artifact_paths_missing` 信号
- **THEN** 系统 MUST NOT 重复写入（MUST 复用既有在途请求）

### Requirement: build_artifact_paths_missing 信号的摄取与唤起

`build_artifact_paths_missing` MUST 登记进 `admin_monitor` 的管理信号表
（`STORED_SIGNAL_TYPES`），由巡检循环摄取并唤起 Administrator。

- 严重度 MUST 登记在严重度表中（建议 `major`，与 `verify_contract_missing` 同级）；
- 处置建议 MUST 登记在 `_SIGNAL_RECOMMENDATIONS`，指向 Administrator 的产物路径
  起草流程；
- 摄取时若信号无关联 spec，MUST 从 evidence 的「项目名=」字段解析项目名
  （与 `verify_contract_missing` 同范式）；
- 摄取后 MUST 先 `mark_escalated` 再唤起（防重复唤起），与既有信号同契约。

#### Scenario: 信号被摄取并唤起 Administrator

- **WHEN** admin store 中出现未 escalated 的 `build_artifact_paths_missing` 信号
  （evidence 含「项目名=xxx」）
- **THEN** 巡检 MUST 摄取该信号，解析项目名，唤起 Administrator
- **AND** MUST 将记录标记 escalated，下一 tick MUST NOT 重捞

#### Scenario: 重复 tick 不重复唤起

- **WHEN** 某条 `build_artifact_paths_missing` 已 escalated
- **THEN** 后续巡检 MUST 跳过该记录（MUST NOT 重复唤起）

### Requirement: Administrator 起草产物路径配置

`agents/administrator.md` MUST 新增产物路径起草手册，指引 Administrator 处理
`build_artifact_paths_missing` 信号：

- 输入源 MUST 包含项目构建配置（`package.json` scripts / `pyproject.toml` /
  目录结构）与 `.fenix/config.yaml` 的 `project.type`；
- 起草流程 MUST 与既有「验证契约起草手册」同构：探测 → 写草稿 → 自证/机械校验
  （路径合法性经 `validate_build_artifact_paths` 同口径）→ 落位 `.fenix/config.yaml`
  → git 提交；
- 确无产物的项目 MUST 写 `has_build_artifacts=false` 结案（MUST NOT 用「路径留空」
  冒充已裁决）；
- 处置动作 MUST 在处置记录 `actions_taken` 留痕。

#### Scenario: 探测到产物时写入配置并提交

- **WHEN** Administrator 收到信号，探测到项目根级 `dist/` 产物
- **THEN** MUST 写 `has_build_artifacts=true` 与 `build_artifact_paths=["dist/"]`
- **AND** MUST 提交配置改动并在处置记录留痕

#### Scenario: 确无产物时写入显式标志

- **WHEN** Administrator 探测确认项目确无构建产物
- **THEN** MUST 写 `has_build_artifacts=false`（而非留空路径）
- **AND** 该项目的后续 merge-back MUST NOT 再产生该信号
