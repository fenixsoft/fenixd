# 设计 — verifier-result-single-source

## 读取抽象
- verification.py 新增统一入口 _read_verdict(spec_name)：verify-progress/<spec>/.fenix-run-result.json → 缺失或不可读时回退主树共享（经 role/spec 戳 + _verifier_result_is_stale 校验）→ 仍无则返回 unreadable。
- legacy（_run_legacy_verification）与 planner（_read_planner_result 裁决应用处）全部改走该入口，删除各自独立路径。
- 补既有 fail-open 缺口：_verifier_result_is_stale 在 run_id 不匹配 `-\d{10,}-a\d+$` 时直接返回 False（不判陈旧，verification.py:2528-2530），此时 implementer 残留 status=success 仍会落到 blocked 分支。统一入口必须改为「先验 role/spec 戳」，不依赖 run_id 可解析——这是本 SPEC 相对已落地 D5 的真实增量。

## 写入隔离
- 主树共享 .fenix/.fenix-run-result.json 的**唯一写入者**是 core/agent_runner/runner.py 的 _execute_agent 拷回（worktree 根 .fenix-run-result.json → 主树，runner.py:2677-2686），对全部 agent 类型生效，且当前实现无 mtime 守卫（与其上方注释 2674-2676 所述不符）。在该拷回点按 agent_type 注入 role 与 spec 戳，是唯一可靠落点；core/pm_engine/engine.py 不含任何主树共享写路径。
- role 取值 = 实际写者全集：implementer | verifier | planner | judge | repair。role 缺失视为旧格式遗留。
- implementer 收尾落盘已由 engine.py _write_impl_result_snapshot 实现（verify-progress/<spec>/impl-result.json，engine.py:879-914，当前 40 个 spec 已落盘）；本 SPEC 不重复该落点，仅在读侧确认其优先级。

## 回归护栏
- 新增污染自检：裁决读路径命中主树共享文件而 role≠verifier（或缺 role）时，记 deliverable-dispute 而非当作验证裁决。
- 该丢弃**仅限裁决读路径**，不得波及 _read_implementer_result（engine.py:800-827）、_read_planner_result 的主树兼容回退（verification.py:5044-5062）与 family._read_prev_impl_conclusions（family.py:646-652）——三者都合法消费同一共享文件。

## 改动点
- core/pm_engine/verification.py：统一 _read_verdict 入口 + role/spec 戳校验 + 双校验回退（不依赖 run_id 可解析）。
- core/agent_runner/runner.py：主树共享写路径（拷回）按 agent_type 挂 role 与 spec 戳。
- tests/test_verdict_contamination.py：污染回归测试（覆盖 run_id 不可解析这一当前红灯场景）。
