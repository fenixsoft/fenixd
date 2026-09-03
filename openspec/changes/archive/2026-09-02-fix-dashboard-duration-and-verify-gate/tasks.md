# Tasks: 修复 dashboard 耗时列恒空与验证失败未被发现

## 1. 修复 run 耗时解析（spec: run-duration-parsing）

- [x] 1.1 `core/dashboard/data.py` `get_runs()`：start_ts 提取改为两级 fallback——优先 `re.search(r"-(\d{9,10})-a\d+$", run_id)`，回退 `re.search(r"-(\d{9,10})$", run_id)`，再无则保持现有 mtime 兜底；`spec_part` 先 `re.sub(r"-a\d+$", "", spec_part)` 再剥离时间戳段
- [x] 1.2 用现有 run 文件验证：对 `.fenix/runs/*.jsonl`（如 `impl-add-parallelism-*‑a1.jsonl`）逐一计算 `duration_seconds`，确认全部 > 0 且等于 `max(0, mtime - start_ts)`；无回归（旧格式兼容）
- [x] 1.3 端到端验证：`/api/specs?project=fenixd` 返回的 `total_duration` 大于 0（有运行记录的 spec），前端「耗时」列显示人类可读时长，按「耗时」表头排序可用

## 2. dashboard 端口占用接管（spec: dashboard-instance-lifecycle）

- [x] 2.1 `serve()` bind 失败（EADDRINUSE）时：通过 `/proc/<pid>/fd` 软链接 + `/proc/net/tcp` inode 定位占用者，若 cmdline 匹配 `fenix_dashboard.py` + `--serve` 且监听目标端口 → SIGTERM 终止（等待 ≤3s）后重新 bind 一次
- [x] 2.2 占用者为非 dashboard 进程或二次 bind 仍失败 → stderr 打印占用进程信息并以非 0 退出（≤5s 内），不得僵挂
- [x] 2.3 集成验证：先启动一个 dashboard 实例（端口 29003），再启动第二个同端口实例 → 第二个接管成功；用无关进程（http.server）占用另一端口验证报错退出路径

## 3. 验证完成度闸门（spec: verification-completion-gate）

- [x] 3.1 `core/pm_engine.py` `_on_spec_verified()` 新增 `_check_verification_gate(spec_name)`：读 `.fenix/verify-progress/<spec>.json`，存在且 `done < total`（或字段缺失/解析失败）→ 拦截 verified→done，原因（done/total + current）写入 spec `error` 字段；文件不存在 → 放行
- [x] 3.2 与既有 `_check_task_completion_gate` 组合：结论一致时合并为单个拦截原因，不出现双 error 覆盖
- [x] 3.3 单测：构造 `verify-progress/<spec>.json` 为 `{"total":34,"done":0}` 触发 `_on_spec_verified` → spec 保持 verified 且 error 含「0/34」；`done==total` → 正常推进 done；无进度文件 → 正常推进

## 4. 验证器耗时真实性断言（spec: verification-completion-gate）

- [x] 4.1 `agents/verifier.md` 增补规则：验证「耗时」列时若 SPEC 在 `.fenix/runs/` 存在运行记录而 `total_duration` 为 0 或显示「—」，must 判定缺陷并记录 run 数与判定依据
- [x] 4.2 验证归因：在验证报告模板/字段中记录被检查 SPEC 的 run 数量，使「有记录而空」与「无记录占位」可区分

## 5. 验证与打包

- [x] 5.1 运行框架单元测试（`python3 -m pytest tests/ -q`）确认无回归
- [x] 5.2 执行 `bash scripts/package.sh` 生成最新扩展包并确认 dist 产物含本次修复
- [x] 5.3 重启/接管 dashboard 实例后人工确认：8787 返回含 `total_duration` 且非 0 的 `/api/specs`，表头排序（含耗时列）在生产端口可用