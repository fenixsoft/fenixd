# Run 耗时解析口径
<!-- knowledge: capability=run-duration-parsing rev=1
     sources=spec/archive/2026-09-02-fix-dashboard-duration-and-verify-gate -->

run 耗时由 run_id 内的开始时间戳与产物文件 mtime 推出，口径单源供表格列与统计共用。

## 规则

- **start_ts 解析适配 attempt 后缀**：`get_runs()` 从 run_id 提取开始时间戳时正确解析 `-a<attempt>` 后缀（run_id 形如 `impl-<spec>-<unix秒>-a2`，时间戳为倒数第二段、10 位 unix 秒）；以该时间戳段为 start_ts，`duration_seconds = max(0, 文件 mtime - start_ts)`，started 不取文件 mtime。不含 attempt 后缀的旧格式（形如 `impl-x-<unix秒>`）保持原解析方式兼容。不得因正则不匹配将 start_ts 退化为 mtime 致 duration_seconds 恒为 0。
- **时间轴归属同步适配**：`get_spec_timeline()` 中从 run_id 剥离 spec 名与时间戳的逻辑同步适配 attempt 后缀（`spec_part` 不残留时间戳/尝试段），时间轴运行节点的归属、排序、过滤按正确 spec 名工作。
- **total_duration 真实求和**：`spec_summary()` 的 `total_duration` 等于该 SPEC 全部 run 的真实 `duration_seconds` 之和；前端「耗时」列在 SPEC 存在任意真实时长（>0）运行记录时显示人类可读的非零时长，不得恒显示「—」。有运行记录但全为 0 只能是解析缺陷，修复后须显示真实数值。
- **耗时真实性断言**：验证涉及「耗时」列时，对有运行记录的 SPEC 必须断言耗时非 0，区分「无记录占位 —」与「计算缺陷 0」。

## 溯源

- 史前基线 — 运行耗时由 run 起止时间解析，started 不取文件 mtime；耗时口径单源供表格与统计共用。
- [2026-09-02 2026-09-02-fix-dashboard-duration-and-verify-gate](spec/archive/2026-09-02-fix-dashboard-duration-and-verify-gate/) — start_ts 正则适配 attempt 后缀（run_id 带 `-a<n>` 后缀曾被漏解析致耗时恒 0），确立 total_duration 真实求和、耗时列非零展示与验证器真实性断言口径。
