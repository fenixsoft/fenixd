## ADDED Requirements

### Requirement: verifier 重试时注入断点进度

框架在构造 verifier Agent 提示词（`_build_prompt` verifier 分支）时 SHALL 检查 `.fenix/verify-progress/<spec>.json` 是否存在且可解析。当该文件存在、JSON 合法且 `done` 为该 SPEC 验证会话的累积已进度（>0）时，框架 SHALL 将断点信息注入提示词，包含：`total`（场景总数）、`done`（已完成场景数）、`current`（上次进行中的场景描述）。收到断点的 verifier SHALL 从 `done+1` 的场景继续执行：跳过已完成场景，场景总数保持 `total` 不变，每完成一个场景将 `done` 递增 1 并更新 `current`，直至全部完成。

#### Scenario: 存在有效断点时从断点继续
- **WHEN** attempt 1 的 verifier 在 `total=32, done=5` 时因 max_turns 被终止，attempt 2 的 verifier 提示词被构造
- **THEN** 提示词包含断点信息（total=32, done=5, current=<上次场景描述>），且 verifier 从第 6 个场景开始执行

#### Scenario: 无断点时全新开始
- **WHEN** `.fenix/verify-progress/<spec>.json` 不存在，或 `done` 为 0
- **THEN** 提示词不包含断点信息，verifier 按既有流程从第 1 个场景开始完整验证

#### Scenario: 断点文件损坏时安全降级
- **WHEN** `.fenix/verify-progress/<spec>.json` 存在但内容不是合法 JSON，或缺少 `done`/`total` 字段
- **THEN** 框架将损坏文件视作无断点：不注入断点信息、不报错，verifier 全新开始验证，且框架 SHALL 移除或忽略损坏内容以免污染后续 attempt

### Requirement: 断点续跑保持进度文件语义稳定

沿用到断点的 verifier 在首次写入进度时 SHALL 将断点值作为起点（`done=<断点值>`）而非重置为 0，之后按场景逐一递增；全部场景完成后 SHALL 写入 `done=total` 与最终结果。进度文件同一时刻仅由一个运行中的 verifier 写入；不同 attempt 之间对同一 SPEC 的 done 值 SHALL 单调不减。

#### Scenario: 断点续跑最终达到 total
- **WHEN** 断点注入 `total=32, done=5` 且后续 27 个场景全部通过
- **THEN** 最终进度文件为 `{"total": 32, "done": 32, "current": "…"}`，验证结果正常写入 `.fenix-run-result.json`

#### Scenario: 首次写入保留断点起点
- **WHEN** attempt 2 的 verifier 首次执行进度写入
- **THEN** 写入的 `done` 为该 attempt 起始断点值（如 5），而非 0