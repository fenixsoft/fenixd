# Proposal: fix-admin-disposition-empty-shell

## Why

Administrator 处置 run 异常死亡（CLI 秒挂/网关故障/SIGTERM）时，daemon 落盘的 final disposition 是"空壳"：`summary`/`action_taken`/`recommended_action` 全为空字符串，且 `AdminDisposition.error`（失败原因）被静默丢弃、失败路径无任何日志。运维界面因此出现只有时间与 spec 名的"无信息处置"卡片，事后无法追溯死因。2026-09-02（bigmodel.cn 网关故障窗口，run `admin-add-spec-archive-1788348989`）与 2026-09-03（本机 SIGTERM，run `admin-fix-implementer-task-progress-1788417611`）两条真实空壳记录均无法从记录本身或日志判定死因，调查时不得不做全链路日志考古。

## What Changes

- `run_administrator` 的 `_run_claude` 异常路径新增 WARNING 日志：携带 run_id 与 error，失败不再静默。
- `admin_monitor._invoke_administrator` 落 final disposition 时，对 `result=failed` 的记录：
  - 新增 `error` 字段携带 `disp.error`（CLI 失败原因，如 `claude CLI failed: Exit code: 143`）；
  - `recommended_action` 兜底为 `disp.recommended_action or signal.recommended_action`（当前被 disp 空串覆盖，pending 占位里反而有值）；
  - `description` 保持现有 `disp.problem or signal.description` 兜底语义不变。
- v3 activities 页 disposition 卡片：`error` 字段存在时以醒目样式显示失败原因；空 summary 的兜底文案区同步展示 error，"无信息"卡片变为自解释。

## Capabilities

### New Capabilities

- `admin-disposition-failure-context`：Administrator 处置失败时，final disposition 记录必须携带失败原因与信号上下文（error 字段、recommended_action 兜底、失败 WARNING 日志、UI 展示），使失败处置记录无需日志考古即可自解释。

### Modified Capabilities

（无——既有 admin 相关能力均已在 `spec/archive/` 归档，活跃 specs 目录为空；本修复以新 capability 承载，不改既有 requirement 语义。）

## Impact

- `core/agent_runner/runner.py`（`run_administrator` 失败路径加日志）
- `core/admin_monitor.py`（`_invoke_administrator` 落盘兜底 + error 字段）
- `core/dashboard/static/src/pages/activities/index.tsx`（卡片 error 展示）
- `core/dashboard/static/dist/`（构建产物需重建并提交）
- 数据兼容：`admin_alerts.json` 新增可选 `error` 键，读侧与旧记录（无该键）兼容
- 生效方式：改 `core/*.py` 需重启 daemon（touch `.fenix/restart_request`）
