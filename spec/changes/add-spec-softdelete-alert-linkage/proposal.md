## Why

SPEC 经 SPEC 管理软删除后，引用它的未处理裁决告警（如 spec-review-rejected）不会被联动关闭，告警与 spec 真实状态脱钩：告警推荐的 abandon 此后永远执行失败（`spec not found`），用户无法经告警完成收口（实证 2026-11-17：alert `8c715662226d`，spec `evo-fix-self-review-window-gap` 已于前夜软删除，告警点丢弃报「裁决执行失败」，见 `spec/knowledge/_inbox/spec-softdelete-escalation-alert-linkage.md`）。同时，对「已删除 spec」执行丢弃只会反复失败，没有幂等出口。

## What Changes

- **软删除联动关闭告警**：`soft_delete_spec`（`core/dashboard/data/spec_archive.py`，被管理页删除端点与裁决 abandon 执行器共用）删除成功时，联动关闭 `admin_alerts.json` 中 `spec` 字段指向该 spec 的全部未处理告警（escalation/signal 双 kind）：`handled=True`、独立 `handled_by` 标识、中文 `resolve_note` 注记归档去向；已 handled 条目逐位不动；不触碰 disposition 台账；联动失败不阻断删除本体（fail-open，结果对象如实回报）。
- **abandon 幂等化**：裁决执行器 `_exec_abandon`（`core/dashboard/data/admin_actions.py`）对 `soft_delete_spec` 返回 `found=False`（活跃 STATE 与归档清单均无该 spec）不再报 `spec not found` 失败，改为幂等成功并注记「spec 已不存在，视为已丢弃」，使存量悬空告警可经丢弃路径正常收口。
- **不改动**：告警 choices 注册表与选项集、`alert_lifecycle` 周期自动闭环扫描通道（条件注册表及其判定）、`archive_spec` 归档通道语义（是否同样联动属后续独立决策）。

## Capabilities

### New Capabilities

- `spec-softdelete-alert-linkage`: SPEC 软删除与告警台账的一致性契约——软删除成功即联动关闭引用该 spec 的未处理告警；对已不存在 spec 的丢弃裁决幂等成功。

### Modified Capabilities

（无——choices 注册表选项集不变；`adjudication-actions` 既有三个动词的冻结前置不变，本变更只新增 abandon 的幂等出口语义）

## Impact

- `core/dashboard/data/spec_archive.py`：`soft_delete_spec` 成功路径追加告警联动（经 AdminStore 排他锁写回）。
- `core/dashboard/data/admin_actions.py`：`_exec_abandon` 的 `found=False` 分支改为幂等成功。
- `core/admin_store.py`：新增 `handled_by="spec-softdeleted"` 取值（复用既有写回通道；前端徽标渲染对未知 handled_by 已有通用兜底，需核对不硬编码枚举）。
- `tests/test_spec_softdelete_alert_linkage.py`（新增）：联动关闭、幂等丢弃、已处理不动、fail-open 四组场景。
- 兼容面：`alert_routes.py` 端点对 `marked=False`（告警已被联动先行闭环）已幂等容忍（code-review item b0a65fc4cf01），无需改动。
