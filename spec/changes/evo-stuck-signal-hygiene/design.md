# design — stuck-signal-hygiene

## 现状

- _detect_stuck（admin_monitor.py:605-641）：updated 超阈值 + !_has_recent_progress → stuck 信号；_has_recent_progress（:1400-1413）按 run 文件 mtime（STUCK_GRACE_MINUTES=10，:58）；_spec_from_run_id 已修复 -r<n>（8e510a87）。
- 信号记录层无去重：5 连发实证（15:11/15:16/15:21/15:26/15:31Z，interval_minutes=5）；_throttled（:824-830）只在唤起路径生效（:767）。
- baseline reset（extension 机制）存在但只延后 deadline 不去重（fenixd.log 10507-10510 行实证）。

## D1 进程存活检查

- admin_monitor 新增 _run_process_alive(spec, runs_dir)：解析 spec 最近 run 文件中的 pid（转录/run 元数据携带 agent 子进程 pid），os.kill(pid, 0) 探活；存活 → _detect_stuck 直接跳过。
- 无 pid 记录（旧转录）→ 跳过该检查（退回文件活跃度判据）。

## D2 信号记录层去重

- 落 signal 记录前查 store.latest_signal(spec, signal_type, cooldown_minutes)：存在 → 不重复落记录。
- 保留唤起路径 _throttled 语义不变（双保险：记录层去重 + 唤起层节流）。

## D3 处置后静默期

- store 记录最近 resolved 处置时间；_detect_* 产信号前查 (spec, signal_type) 最近 resolved 处置时间，在 admin.stuck_silence_minutes 内 → 跳过。
- core/config.py admin 段新增 admin.stuck_silence_minutes（默认 120）。

## D4 兼容

- 真实 stuck（run 无进程 + 无文件活跃 + 无近期 resolved）仍正常产生信号；静默期仅限处置后，不掩真阳性。