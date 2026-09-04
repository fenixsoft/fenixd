# administrator-agent Spec

## ADDED Requirements

### Requirement: Administrator Agent 按需唤起
当监视器检测到困境且节流通过时，Fenixd SHALL 唤起一个 Administrator Agent（`claude -p` 子进程，`--permission-mode bypassPermissions`，`--output-format stream-json`）。其 prompt SHALL 包含：困境信号详情、可用的高级处置手段、以及"仅处置困境、不开发功能"的约束。Administrator 的 run 产物 SHALL 与其他 agent 一样写入 `.fenix/runs/`。

#### Scenario: 检测到困境唤起 Administrator
- **WHEN** 监视器记录到困境信号且节流通过
- **THEN** Fenixd 唤起 Administrator Agent 处置

#### Scenario: 无困境不唤起
- **WHEN** 无任何困境信号
- **THEN** 不唤起 Administrator Agent，不产生 LLM 成本

### Requirement: Administrator 处置权限
Administrator Agent SHALL 拥有以下高级权限，自主处置 Agent 无法脱困的问题：
- 杀死/重启进行中的 Agent 子进程与 fenixd 本身
- 发起 git 清理（`worktree prune`、stash、reset）与 commit
- 修改 Fenixd 自身代码并提交（直接在主树操作）
- 发起新的 SPEC（创建 `spec/changes/<name>/` 并注册 STATE.md）
- 重置/修复 spec 状态（`update_spec` 到 `ready`/`blocked` 等）

#### Scenario: 杀死卡死 Agent
- **WHEN** Administrator 判断某 Agent 子进程卡死
- **THEN** Administrator 杀死该进程，Fenixd 按恢复机制重新调度

#### Scenario: 修复卡死 spec 状态
- **WHEN** Administrator 确认 spec 卡在 `implementing`/`testing`
- **THEN** Administrator 将 spec 重置为 `ready` 并清空陈旧字段

### Requirement: 处置记录
Administrator SHALL 将每次处置写入 `.fenix/admin_alerts.json`（时间、spec、问题、处置动作、结果），供 Dashboard 与人类追溯。

#### Scenario: 处置留痕
- **WHEN** Administrator 完成一次处置
- **THEN** 处置记录追加到 `admin_alerts.json`
