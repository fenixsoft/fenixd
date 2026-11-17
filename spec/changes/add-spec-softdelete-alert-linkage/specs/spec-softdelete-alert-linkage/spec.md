## ADDED Requirements

### Requirement: SPEC 软删除成功联动关闭关联告警

`soft_delete_spec`（`core/dashboard/data/spec_archive.py`，SPEC 管理删除端点与裁决 abandon 执行器的共用底层）对活跃 STATE 存在的 spec 执行软删除成功时，MUST 联动关闭 `admin_alerts.json` 中全部未处理且 `spec` 字段等于该 spec 名的告警条目（kind=escalation 与 kind=signal 同治）。软删除成功含两种既有形态，均适用本联动：目录迁移（`archived=True`，目录迁至 `spec/archive/<name>-<Unix秒>/`、STATE 条目迁出）与仅清状态（目录本就缺失，`archived=False`，仅 STATE 条目迁出，函数既有「目录缺失仅清状态（幂等）」语义）。联动关闭写回形态：`handled=True`、`handled_at` 为联动时刻、`handled_by="spec-softdeleted"`、`resolve_note` 注记软删除事实与归档去向——目录迁移形态注记含归档目录名（形态：`SPEC <名> 已软删除（归档至 spec/archive/<归档目录名>），关联告警联动关闭`）；仅清状态形态如实注记无目录（形态：`SPEC <名> 已软删除（无目录，仅清理状态登记），关联告警联动关闭`）。已 handled 条目 MUST 逐位不动（不覆盖任何人工处置记录与既有自动闭环记录）；MUST NOT 新增告警条目、MUST NOT 改写 disposition 记录本体。

联动关闭为删除本体的 best-effort 后置步骤（fail-open）：告警写回失败（含 AdminStore 拒写、IO 异常）MUST NOT 使软删除失败或回滚目录迁移；`soft_delete_spec` 返回对象 MUST 如实携带联动结果（关闭条数与失败说明，如 `alerts_closed` / `alert_link_error` 字段），供调用方呈现。联动失败说明 MUST 落独立字段（如 `alert_link_error`），MUST NOT 写入返回对象顶层 `error` 字段——该字段是删除本体的既有失败语义键（`_exec_abandon` 据其判成功分类 `admin_actions.py:2333`，删除端点据其报失败），被联动失败占用会把已成功的删除对两个调用方反转成失败，重造本 SPEC 要消除的状态分裂。全局信号判定契约不回归：`spec` 字段为空/`global` 的条目不参与本联动。

#### Scenario: 软删除成功关闭引用该 spec 的未处理告警

- **WHEN** 对存在 1 条未处理 escalation 告警与 1 条未处理 signal 告警（均 spec=<名>）的活跃 spec 执行软删除成功
- **THEN** 两条告警均变为 handled=True、handled_by=spec-softdeleted、resolve_note 含归档目录名，未处理告警计数随之减少；spec 目录已迁移至 spec/archive/<名>-<Unix秒>/

#### Scenario: 已处理告警与 disposition 台账不被触碰

- **WHEN** 对同时存在已 handled 告警与 disposition 记录的 spec 执行软删除成功
- **THEN** 已 handled 告警的 handled/handled_at/handled_by/resolve_note 逐位不变，disposition 记录本体字段不变，台账无新增

#### Scenario: 联动失败不阻断删除

- **WHEN** 告警台账写回失败（如文件拒写）时执行软删除
- **THEN** 软删除本体成功（目录迁移、STATE 迁出不变），返回对象 ok=True 且如实携带联动失败说明，无未捕获异常逸出

### Requirement: 对已不存在 spec 的 abandon 裁决幂等成功

裁决执行器 `_exec_abandon`（`core/dashboard/data/admin_actions.py`）分派 `soft_delete_spec` 返回 `found=False`（目标 spec 既不在活跃 STATE、也不在归档清单 `.fenix/STATE.archive.md`）时，MUST 判定为幂等成功而非失败：返回 ok=True、动作步骤注记「spec 已不存在（STATE 与归档清单均无记录），视为已丢弃」；MUST NOT 再产生 `spec not found` 失败结果。告警收口链路契约不回归：alert-resolve 端点对该成功结果按既有成功路径标记 handled 并写 disposition 留痕；`found=True` 路径行为不变（软删除执行 + 联动关闭告警）。

#### Scenario: 悬空告警执行丢弃幂等成功

- **WHEN** 对 spec 已软删除（STATE 与归档清单均无记录）的告警选择 abandon 并执行
- **THEN** 裁决执行成功（ok=True，步骤含「视为已丢弃」注记），告警被标记已处理，无「spec not found」失败回执

#### Scenario: 存量在册 spec 的丢弃行为不变

- **WHEN** 对仍处于活跃 STATE 的 spec 的告警选择 abandon 并执行
- **THEN** 行为与既有契约一致：软删除执行成功并经联动关闭关闭该告警，无重复失败语义
