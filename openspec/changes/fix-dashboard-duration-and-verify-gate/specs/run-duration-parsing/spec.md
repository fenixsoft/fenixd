## ADDED Requirements

### Requirement: run_id 时间戳解析适配 attempt 后缀

`get_runs()` 从 run_id 提取运行开始时间戳时 MUST 正确解析 `-a<attempt>` 后缀格式。实际 run_id 形如 `impl-add-parallelism-1787757864-a2`（`agent_runner.py` 每次 attempt 追加 `-a{n}`），时间戳位于倒数第二段；解析 MUST 以该时间戳段（10 位 unix 秒）作为 start_ts，`duration_seconds = max(0, 文件 mtime - start_ts)`。对不含 attempt 后缀的旧格式（形如 `impl-x-1787757864`）MUST 保持原解析方式兼容。不得再因正则不匹配将 start_ts 退化为 mtime 导致 duration_seconds 恒为 0。

`get_spec_timeline()` 中从 run_id 剥离 spec 名与时间戳的逻辑 MUST 同步适配 attempt 后缀（`spec_part` 不应残留 `-1787757864-a2` 这类时间戳/尝试段），确保时间轴运行节点与排序、过滤按正确 spec 名工作。

#### Scenario: attempt 后缀 run 的时长真实计算

- **WHEN** 存在 run 文件 `impl-add-parallelism-1787757864-a2.jsonl`（该 attempt 从 1787757864 秒开始，文件 mtime 为 1787758000 秒）
- **THEN** `get_runs()` 返回的该 run `duration_seconds` 为 136，且 `spec` 字段为 `add-parallelism`

#### Scenario: 旧格式 run 不受影响

- **WHEN** 存在 run 文件 `impl-old-1787750000.jsonl`（无 attempt 后缀，mtime 为 1787750100 秒）
- **THEN** `duration_seconds` 为 100，行为与原逻辑一致

### Requirement: total_duration 反映真实运行时长

`spec_summary()` 的 `total_duration` MUST 等于该 SPEC 全部 run 的真实 `duration_seconds` 之和；前端「耗时」列 MUST 在 SPEC 存在任意有真实时长（>0）的运行记录时显示人类可读的非零时长，不得恒显示「—」。有运行记录但全部时长为 0 只因解析缺陷的场景 MUST 在修复后显示真实数值。

#### Scenario: 有运行记录的 SPEC 耗时非零

- **WHEN** 某 SPEC（如 `add-parallelism`）存在多条运行记录且修复后各 run `duration_seconds` 均大于 0
- **THEN** `/api/specs` 返回的 `total_duration` 大于 0，前端「耗时」列显示对应人类可读时长（如「12分36秒」），且按该列排序（数值）可区分不同 SPEC