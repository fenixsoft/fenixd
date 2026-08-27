## 1. mergeback-stashpop-self-heal（pop 冲突自愈）

- [ ] 1.1 `core/worktree_manager.py::restore_after_merge`：`git stash pop` 失败且输出含 `CONFLICT` 时判定冲突，用 `git ls-files -u` 枚举 UU 文件；而非仅记 WARNING 返回
- [ ] 1.2 自愈执行：对每个 UU 文件 `git checkout HEAD -- <file>`（丢弃 stash 版本、保留 merge 结果），随后 `git reset`；成功后主树无 UU、index 无残留冲突、git 写命令恢复正常
- [ ] 1.3 返回结构改为 `(ok, conflict_files)`（或等价 result 对象）：成功返回 `(True, [])` 行为与现状兼容；冲突自愈后返回 `(True, [file,...])` 携带清单，stash 条目保留不 drop
- [ ] 1.4 `core/pm_engine.py` merge-back 流程：`restore_after_merge` 返回 conflict_files 非空时，在该 spec 的 `error` 字段追加 `stash pop conflict: files=[...]`（中毒前先清 UU），触发 admin 告警通道
- [ ] 1.5 无冲突/无 stash 路径回归：pop 成功或 `No stash entries` 时行为与现状完全一致
- [ ] 1.6 单测（`tests/`）：构造 pop 冲突（stash 改动 A 文件 + merge 推进改同文件）→ 断言 UU 被清、index 干净、conflict_files 正确、stash 仍可见；无冲突路径返回 True

## 2. provider-fault-fuse（4xx 快速熔断）

- [ ] 2.1 `core/agent_runner.py` 熔断状态：`provider_circuits` 字典维护每 provider 的滚动窗口 4xx 计数、open 标记与 cooldown_until（常量默认：窗口 5 分钟 / 阈值 3 次 / 冷却 30 分钟）
- [ ] 2.2 计数与触发：claude CLI 输出中解析到 HTTP 4xx（`api_error_status` 400/401/404）时计数并入窗口，达阈值置 open；5xx/网络错误不计数
- [ ] 2.3 派发拦截：选择 provider 时若 open 且未过 cooldown_until，直接返回错误 `provider circuit open: <name> (HTTP <code> x <count>)`，不启动 claude 进程；该失败不递增 spec `_retry_count`/`_merge_streak`，不触发状态机回退（spec 保持原状态，不新增 worktree/autostash）
- [ ] 2.4 半开恢复：cooldown 到期后首个派发作为探针，网关 200 即闭合（状态恢复 closed）；仍 4xx 则重新冷却
- [ ] 2.5 错误透出：熔断错误文本含 provider 名、HTTP code、次数与冷却到期/剩余信息，经既有 error → STATE.md / admin_monitor / dashboard 链路可见
- [ ] 2.6 单测（`tests/`）：阈值触发、熔断期拦截（断言未 spawn claude）、不增 retry/不 flips 状态机、冷却后 200 闭合、5xx 不计数

## 3. 回归与验证

- [ ] 3.1 `python3 -m pytest tests/ -v` 全绿（含既有 262+ 项回归）
- [ ] 3.2 手工验证（可选）：对测试仓库构造 stash pop 冲突场景，确认自愈后 `git status` 干净、后续 `git merge --no-ff` 可执行
- [ ] 3.3 代码 review：确认自愈路径不误伤正常 pop、熔断不误伤 5xx 瞬态与多 provider 共存