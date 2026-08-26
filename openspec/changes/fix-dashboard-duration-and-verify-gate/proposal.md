# Proposal: 修复 dashboard 耗时列恒空与验证失败未被发现

## Why

`improve-dashboard-sections`（`spec-table-improvements`）要求：SPEC 表格表头点击排序、新增「耗时」列展示真实运行总时长。经调查确认两项在生产环境均未生效且验证器全程未发现：

1. **耗时列恒为「—」**：`core/dashboard/data.py` 的 `get_runs()` 从 run_id 提取开始时间戳的正则 `-(\d{9,10})$` 要求纯数字结尾，但实际 run_id 恒以 `-a<attempt>` 结尾（`agent_runner.py` `attempt_run_id = f"{run_id}-a{attempt}"`）→ 正则全部不匹配 → start_ts 退化为文件 mtime → `duration_seconds = max(0, mtime - mtime) = 0`。实测全部 20 个 run 的 duration 均为 0，`total_duration` 恒 0，前端恒显示「—」。
2. **生产实例跑旧代码**：8787 端口被 13:26 启动的实例（improve-dashboard-sections 合入前）长期占用，其后 4 个新实例 bind 失败却不退出僵挂（16:28 的实例 fallback 到 8799）。浏览器访问 8787 拿到的是旧 data.py 输出（无 `total_duration` 字段）。「表头排序不可用」同样源于旧实例/浏览器缓存旧 app.js——新代码中排序经实测可用。
3. **验证器漏检**：`improve-dashboard-sections` 验证进度 `{"total":34,"done":0}`——34 个场景一个未完成（多次 verify run 均被轮流截断）却被放行至 done→pushed；且耗时列全「—」与 spec 合法的「无运行记录占位」视觉无法区分，验证器无从识别计算缺陷。

## What Changes

- **修复 run 耗时解析**：`get_runs()`/`get_spec_timeline()` 的 run_id 时间戳提取适配 `-a<attempt>` 后缀（如 `-(\d{9,10})-a\d+$`），使 `duration_seconds` 等于真实运行时长；耗时列展示真实数据，排序（按数值）随之生效。
- **dashboard 实例生命周期治理**：`fenix_dashboard.py --serve` 启动时若端口已被占用（旧实例持有），应自动清理旧实例或明确报错退出，不得静默僵挂留下旧代码进程服务生产端口。
- **验证完成度强制闸门**：SPEC 进入 done/pushed 前 MUST 校验验证进度 `done == total`；验证未全量完成时禁止放行，需记录未完成原因。
- **验证器耗时真实性断言**：验证「耗时」列时，对有运行记录的 SPEC 必须断言耗时非 0（区分「无记录占位 —」与「计算缺陷 0」）。

## Capabilities

### New Capabilities

- `run-duration-parsing`：run_id 时间戳解析适配 attempt 后缀，duration_seconds 与 total_duration 真实计算。
- `dashboard-instance-lifecycle`：dashboard 服务端口冲突时的启动/退出语义，杜绝旧代码实例长期占用生产端口。
- `verification-completion-gate`：验证完成度放行闸门（done==total 才可推进），与耗时列真实性检查规则。

### Modified Capabilities

- 无（`improve-dashboard-sections` 的能力不修改其 spec 文本，本次以缺陷修复 spec 形式落地）。

## Impact

- **代码**：`core/dashboard/data.py`（get_runs / get_spec_timeline / spec_summary）、`bin/fenix_dashboard.py` 或 `core/dashboard/server.py`（serve 端口语义）、`core/state_machine.py` / `core/pm_engine.py`（done/pushed 放行校验）、`core/verify_engine/` 与 verifier 提示词（验证规则与断言）。
- **行为**：修复后，生产 dashboard 耗时列显示真实总时长、排序正常可用（新代码生效）；验证器在场景未全量完成或耗时计算异常时阻止 SPEC 前进。
- **关联**：`improve-agent-config-and-verify-resume`（进行中）已提供验证断点续跑（checkpoint/resume）能力；本变更的「完成度闸门」与之互补——前者保证最终能跑完，后者保证跑不完不放行。