# orphaned-state-probe-calibration 设计

## 现状

- core/admin_monitor.py:262 `_RUN_PREFIXES`（子集表）→ :2259 `_spec_from_run_id` 顺序匹配前缀 + 正则 `^(.*)-\d{9,10}(-(?:a|r)\d+)*$`；缺 `repair-` 时返回 None。
- `spec_is_undriven`（:358-396）三条件：① `_has_recent_spec_run`（:331-355，mtime 宽限 ORPHANED_RUN_GRACE_SECONDS=120）② `_pgrep_live_worktree` ③ 待派发族。
- run_administrator 失败：agent_runner 记录 error=claude CLI failed: Exit code: N（日志 :12550 实证），无 stderr。

## 改动设计

1. **前缀归一**：`_RUN_PREFIXES` 从真源（core/agent_runner/run_files.py:RUN_ID_AGENT_PREFIXES）导入或补全 `repair-`，并加单测锁定 repair- 前缀归一。
2. **活跃度判定回归**：为 `_has_recent_spec_run` 补 repair 前缀用例（mtime 新鲜 → True）。
3. **Exit 日志**：run_administrator 捕获 CLI 子进程 stderr 尾部（截断 4KB）+ 退出码 + run 末 3 事件时间戳，写入 error 上下文与告警 evidence。
4. **去重语义文档化**：在 admin_monitor 注释与告警 description 中区分 signal/disposition 阶段；确认窗口查重（AdminStore.latest_signal）覆盖 orphaned_state 同信号重复。

## 兼容与风险

- 前缀归一仅影响匹配广度（修复修复盲区），对既有前缀行为不变。
- Exit 日志为附加信息，不改处置流程。