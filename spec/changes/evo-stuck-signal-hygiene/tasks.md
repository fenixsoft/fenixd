## Deliverables

```yaml
- path: core/admin_monitor.py
  kind: modify
- path: core/admin_store.py
  kind: modify
- path: core/config.py
  kind: modify
- path: core/dashboard/data.py
  kind: modify
- path: core/dashboard/static/src/pages/settings/components/SystemPanel.tsx
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: tests/test_stuck_signal_hygiene.py
  kind: new
```

## 1. 进程存活反证（D1）

- [ ] 1.1 core/admin_monitor.py：`_detect_stuck` 中，经 `AgentRunner.running_run_ids()`（既有公开 API）判定该 spec 是否有存活 run——命中（run_id 经 `_spec_from_run_id`（本模块既有方法，支持 `-r<n>` 瞬态重试后缀）归属该 spec）→ 直接 continue；`agent_runner is None` → 跳过本检查退回文件判据。不新增 pid 解析、不改 `agent_runner`。⚠️ 禁止用 `run_spec_part`（`run_files.py:66`）：该函数不处理 `-r<n>` 后缀，`<base>-a1-r1` 形态归属失败、D1 失效（8e510a87 教训）。

## 2. 去重回归测试（D2，不新增去重代码）

- [ ] 2.1 tests/test_stuck_signal_hygiene.py：锁定既有 `merge_signal` 行为——冷却窗口内同 `(spec, signal_type, status_hash)` 重复触发只保留 1 条 signal 记录、只刷 `last_seen`（09-14 连发场景防回退护栏）。

## 3. 处置后静默期（D3）

- [ ] 3.1 core/admin_store.py：新增 `latest_resolved_disposition(spec, signal_type)`——仅匹配 `kind=DISPOSITION` 且 `result∈{resolved, partially-resolved}`，返回最近记录或 None（不复用 `latest_signal`）。
- [ ] 3.2 core/admin_monitor.py：`_detect_stuck` 产信号前查 3.1，距处置时刻 < `admin.stuck_silence_minutes` → 跳过；`result=escalated` 不触发静默。

## 4. 配置与 Dashboard 界面（D4）

- [ ] 4.1 core/config.py：`get_admin_config` 新增 `admin.stuck_silence_minutes`（默认 120）；校验段加非负护栏。
- [ ] 4.2 core/dashboard/data.py：`stuck_silence_minutes` 必须在以下所有 admin 键同步点新增（缺一不可，否则 Dashboard 读写/校验缺省回显/页面同步不一致）：
  - `:3875-3878` `_SOURCE_KEYS` 白名单；
  - `:3966-3972` `_managed_key_sources` admin 枚举（新增 `"stuck_silence_minutes"`）；
  - `:4000-4004` `_ADMIN_DEFAULTS` 缺省（`"stuck_silence_minutes": 120`）；
  - `:4485-4492` patch 合并循环 admin 键列表；
  - `:4915-4926` 写路径校验规则（非负数值 `v >= 0`，同 `escalation_cooldown_minutes`）；
  - `:5000-5002` `_SYNC_PAGE_KEYS` system 页 admin 列表。
- [ ] 4.3 core/dashboard/static/src/pages/settings/components/SystemPanel.tsx + services/dashboard.ts：系统设置面板增 `stuck_silence_minutes` 输入项（与 `escalation_cooldown_minutes` 同型）+ `AdminConfig` 增字段。

## 5. 测试

- [ ] 5.1 tests/test_stuck_signal_hygiene.py：进程存活（即使文件 mtime 陈旧）→ 0 误报；真实 stuck（无存活 run + 无文件活跃 + 无近期 resolved）→ 仍产生信号。**关键子场景**：存活 run_id 带 `-r<n>` 瞬态重试后缀（`<base>-a1-r1`）且文件 mtime 陈旧 → 仍 0 误报（锁 D1 的 `_spec_from_run_id` 解析，防 `run_spec_part` 回退引入 8e510a87 回归）。
- [ ] 5.2 tests/test_stuck_signal_hygiene.py：`result=resolved` 处置后静默期内不复发、窗口外复发；`result=escalated` 不静默。
- [ ] 5.3 tests/test_admin.py 既有 stuck 断言回归不过即修。
