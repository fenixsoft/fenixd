# verify-progress-sourcing 能力增量（fix-verify-progress-fasttrack）

> 验证进度数据源契约：进度文件（`.fenix/verify-progress/<spec>.json`）优先；缺失时回退 fast-track 裁决结果文件的 `verification.scenarios` 嵌套键合成。保证 fast-track SPEC 在 spec 列表「验证」列与详情页「验证进度」卡片展示真实验证结果，而非恒 `0/0` 空态。

## ADDED Requirements

### Requirement: 验证进度数据源回退合成

Dashboard 读侧（`core/dashboard/data.py` 的 `parse_verify_progress`）返回验证进度时，MUST 按以下优先级取数：

1. 进度文件 `.fenix/verify-progress/<spec>.json` 存在且可解析 → 使用之（现状，full 模式 verify_engine 逐场景推进路径不变）。
2. 进度文件缺失时 → 回退读取裁决结果文件 `.fenix-run-result.json` 的 `verification.scenarios`（fast-track schema，`core/fast_track_result.py`），合成进度：`total` = 场景条目数；`done` = 含 `status` 字段的场景条目数（fast-track 一次性判定，正常等于 total）；`current` = 终态文案「验证完成: N通过, M失败, K错误」（对齐 full 模式 verify_engine 终态文案格式），N/M/K 按场景 `status` 归类计数——`pass` 计通过，`fail`/`failed` 计失败（对齐 `verdict_check.py` 既有双用词兼容），`error` 计错误，`warning`/`exempt` 为豁免类不计入三桶（与裁决链豁免语义一致）。结果文件查找顺序：`.fenix/verify-progress/<spec>/.fenix-run-result.json`（专属副本）→ `.fenix/.fenix-run-result.json`（主树共享文件，携带 spec 与当前 SPEC 不符时忽略——复用既有匹配语义）。
3. 进度文件与结果文件皆不可得 → 返回 `exists: false`（现状空态语义不变，前端「暂无验证进度」与列表兜底展示继续生效）。

回退合成成功时返回对象 MUST 携带 `source: "run-result"` 标记（进度文件路径返回则携带 `source: "file"` 或不携带，由实现自定，但两形态 MUST 可区分），供展示层与测试区分数据来源。

#### Scenario: fast-track 结果文件合成验证进度

- **WHEN** 某 fast-track SPEC 无进度文件，其 `.fenix/verify-progress/<spec>/.fenix-run-result.json` 含 `verification.scenarios`（8 条，全部 `status: "pass"`）
- **THEN** `parse_verify_progress` 返回 `exists: true`、`total: 8`、`done: 8`、`current` 含「验证完成: 8通过, 0失败, 0错误」语义文案、`source: "run-result"`；spec 列表「验证」列显示 `8/8`，详情页「验证进度」卡片显示完整进度条

#### Scenario: 进度文件优先不回归

- **WHEN** 某 full 模式 SPEC 的进度文件存在（`total: 11, done: 5`），同 SPEC 的结果文件亦存在
- **THEN** `parse_verify_progress` 返回进度文件数值，不触发回退合成，行为与修复前一致

#### Scenario: 双缺省维持空态

- **WHEN** 进度文件缺失，结果文件缺失/不可解析/`verification.scenarios` 为空或非法
- **THEN** `parse_verify_progress` 返回 `exists: false`（total/done 为 0），不抛异常；前端列表验证列与详情页空态展示不变

### Requirement: 列表验证列空数据展示兜底

spec 列表「验证」列在验证数据整体缺失（`verify_total` 为 0）时 MUST 展示 `—` 而非 `0/0`，消除「数值计数」与「尚无验证数据」两种语义的混淆；`verify_total > 0` 时维持 `done/total` 数值展示不变。

#### Scenario: 未验证 SPEC 显示占位符

- **WHEN** 某 SPEC 尚无任何验证数据（进度文件与结果文件皆缺，`verify_total: 0`）
- **THEN** 列表「验证」列显示 `—`；点击不再弹出误导性的 0/0 计数 Popover（或 Popover 内容为空态文案，取实现简者）

#### Scenario: 已验证 SPEC 数值展示不回归

- **WHEN** 某 SPEC 验证数据非空（`verify_total > 0`，无论 full 进度文件路径还是 fast-track 回退合成路径）
- **THEN** 列表「验证」列显示 `done/total` 数值（如 `8/8`、`5/11`），行为与修复前一致
