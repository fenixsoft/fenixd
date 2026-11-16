# spec: verdict-run-result-fallback — Dashboard 验证裁决兜底三路候选

## ADDED Requirements

### Requirement: 兜底读取器三路候选链

Dashboard 侧裁决兜底读取（`core/dashboard/data/artifacts.py` `_load_run_result`）按固定优先级依次尝试三路候选，命中即返回：

1. `.fenix/verify-progress/<spec>/.fenix-run-result.json`（full 模式私有裁决副本）
2. `.fenix/verify-progress/<spec>/impl-result.json`（fast-track per-spec 实现收口快照）
3. `.fenix/.fenix-run-result.json`（共享结果文件，须 `spec` 字段严格匹配）

##### Scenario: fast-track 快照被兜底读取

- **WHEN** SPEC 目录无 `verification-report.md`、私有 `.fenix-run-result.json` 不存在，且 `.fenix/verify-progress/<spec>/impl-result.json` 存在并含 fast-track 形态验证段（`verification.verdict` ∈ verified/bug-found 等）
- **THEN** 兜底读取命中该快照，`parse_verdict` 返回 `exists: True` 及对应裁决状态与三桶计数，Dashboard 列表「验证」列与详情页 VerdictPanel 正常渲染

##### Scenario: 升级 full 后新裁决压过旧快照

- **WHEN** 同一 SPEC 既有 fast-track 期遗留的 `impl-result.json`，又有 full 模式验证落盘的私有 `.fenix-run-result.json`
- **THEN** 读取结果取私有 `.fenix-run-result.json` 的裁决（候选序 1 先于候选序 2），不回读旧快照

### Requirement: 快照归属 fail-closed 校验

`impl-result.json` 候选仅在其顶层 `spec` 字段等于当前 SPEC 名时采信；字段缺失、不匹配、文件损坏或非 dict 形态一律忽略该候选继续下一路，全部未命中返回空（`parse_verdict` fail-closed 返回 `exists: False`，不伪造结论）。

##### Scenario: 归属不符的快照被忽略

- **WHEN** `.fenix/verify-progress/<spec>/impl-result.json` 存在但顶层 `spec` 字段缺失或不等于当前 SPEC 名
- **THEN** 该候选被跳过，读取链继续尝试共享候选，仍无命中则 `exists: False`

##### Scenario: 损坏快照不阻断读取链

- **WHEN** `impl-result.json` 为非法 JSON / 非 dict 形态
- **THEN** 视为候选缺失，读取链继续，不抛异常、不中断响应

### Requirement: 裁决语义与既有形态契约不变

裁决值提取复用既有 `_run_result_verdict_and_bugs`（fast-track 的 `verification.verdict`/`verification.bugs` 嵌套形态），三桶计数合成沿用 int 形态契约（含 0、`product_bugs=len(bugs)`、`env_issues=None`）；无合法裁决值时维持 `exists: False`。不触碰验证/裁决写链，不产生 `verification-report.md`。

##### Scenario: 无裁决值的快照不伪造通过

- **WHEN** `impl-result.json` 合法但 `verification.verdict` 缺失或取值非法
- **THEN** `parse_verdict` 返回 `exists: False`，维持空态呈现
