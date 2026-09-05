## Deliverables

```yaml
- path: core/v2_dev_server.py
  kind: modify
- path: core/agent_runner/v2_server.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: core/pm_engine/dispatch.py
  kind: modify
- path: core/worktree_manager.py
  kind: modify
- path: core/pm_engine/verification.py
  kind: modify
- path: core/verify_contract.py
  kind: modify
- path: fenixd.py
  kind: modify
- path: tests/v2/dev-server.mjs
  kind: modify
- path: tests/test_v2_dev_server.py
  kind: new
- path: tests/test_agent_runner.py
  kind: modify
- path: tests/test_worktree_stray_and_identical.py
  kind: modify
- path: tests/test_pm_verification.py
  kind: modify
- path: .fenix/verify-serving/servers.json
  kind: reference
```

## 1. 停止原语与端口加固（core/v2_dev_server.py）

- [ ] 1.1 dev-server spawn（v2_dev_server.py:144-151）加 `start_new_session=True`（独立进程组）
- [ ] 1.2 `_kill`（v2_dev_server.py:188-200）升级为杀整树：`os.killpg(getpgid(pid), SIGTERM)` → 等待 → `killpg SIGKILL` → 单进程兜底；全程 try/except 包裹（ProcessLookupError 竞态安全）
- [ ] 1.3 `_port_in_use`（v2_dev_server.py:50-61）bind 前 `setsockopt(SO_REUSEADDR)`，消除 TIME_WAIT 假性占用
- [ ] 1.4 `allocate_port`（v2_dev_server.py:64-89）耗尽时不再抛 `V2DevServerError`：复用 `_find_free_port`（core/verify_contract.py:249，上移为共用助手）回退系统临时端口 + WARNING 留痕；封死"静默回退 8787 主树"路径

## 2. 豁免修复与周期清扫（core/v2_dev_server.py + fenixd.py）

- [ ] 2.1 将 `_is_claude_process` 判定（worktree_manager.py:18 附近）抽取到公共模块防循环依赖；`_worktree_has_live_referencing_process`（v2_dev_server.py:261-276）豁免判定接入 claude 过滤——同 worktree 双孤儿互引不构成有效豁免
- [ ] 2.2 daemon 主循环定时器族（fenixd.py:215+，对齐 config_check_ts 模式）新增 ≤10 分钟间隔周期调用 `cleanup_orphans`

## 3. ppid 自杀绑定（tests/v2/dev-server.mjs）

- [ ] 3.1 dev-server.mjs 增加 `setInterval` 轮询 `process.ppid === 1` → `process.exit()`（孤儿自灭）；不使用 PDEATHSIG（per-dispatch 线程 spawn 会误杀）

## 4. 终态收割（core/agent_runner/runner.py + core/pm_engine/dispatch.py）

- [ ] 4.1 `_execute_agent`（runner.py:985-1530）包 try/finally：运行作用域维护 `used_wts`（本 run 创建/复用的 wt_path）与 `handed_off`（显式枚举三个 keep 分支：fast-track/repair 延迟 runner.py:1437-1438、keep 分支 :1492-1497、取消 keep :1063-1071）
- [ ] 4.2 finally 对 `used_wts - handed_off` 且仍在注册表的条目执行收割：`_v2_stop_for_worktree` + `_kill_worktree_strays`（幂等，双调无害）——覆盖 frozen 早退（:1043）、chain_exhausted（:1135）、熔断拦截（:1154）、日限 raise（:1093）、任意异常
- [ ] 4.3 dispatch 层 worker 级 try/finally 兜底：`_run_fast_track_worker`（dispatch.py:1039）与 repair worker 在 runner success 返回后的 hand-off 边界内异常时收割 `result.worktree_path` 注册条目
- [ ] 4.4 `_v2_launch_for_worktree`（v2_server.py:39）改幂等 ensure 语义：worktree 无存活注册条目时一律补启——修复 repair 复用载体轮无 dev-server、`_v2_inject_env` 返回空、测试静默打 8787 主树的缺陷

## 5. 游离进程清扫升级（core/worktree_manager.py）

- [ ] 5.1 `_kill_worktree_strays`（worktree_manager.py:1157-1190）在 cmdline 匹配外增加 `/proc/<pid>/cwd` readlink 归属匹配（覆盖 argv 不含 worktree 路径的进程，如 Bash 起的 npm run dev）
- [ ] 5.2 SIGTERM 后短等待，无响应进程补 SIGKILL 兜底

## 6. command 型被测实例登记制（core/pm_engine/verification.py + core/verify_contract.py）

- [ ] 6.1 新增 `.fenix/verify-serving/servers.json` 读写（`.fenix/` 既有 lock 模式）：`CommandVerifyServer` 创建时登记（pid/port/spec/worktree）、stop 时移除
- [ ] 6.2 `_ensure_app_reachable` 兜底 spawn（verification.py:393-395）同登记纳入管理
- [ ] 6.3 spec 推进 done/verified：`_on_spec_verified` 调用点同步 stop 登记服务 + 驱逐 `_contract_static_servers[spec]` + `_remove_serving_worktree`
- [ ] 6.4 daemon 启动与周期清扫按 /proc liveness 收割"无在飞 spec 但进程仍存活"的登记项并移除登记

## 7. 测试

- [ ] 7.1 新建 tests/test_v2_dev_server.py（当前零专项覆盖）：allocate_port 确定性/used 跳过/耗尽回退临时端口；SO_REUSEADDR 下关闭 listener 立即 rebind 成功；start/stop 真起停 node；start_new_session 后 killpg 不误伤同组外进程；豁免矩阵（存活 claude 豁免/非 claude 引用不豁免/双孤儿互引不豁免）
- [ ] 7.2 tests/test_agent_runner.py 补终态收割：frozen 早退/chain_exhausted/日限 raise/任意异常路径断言注册条目清空（fake proc）；fast-track keep 分支不误收割；重复收割幂等
- [ ] 7.3 tests/test_worktree_stray_and_identical.py 补：cwd 在 worktree、argv 无路径的进程可被杀；SIGTERM 无视者 SIGKILL 兜底
- [ ] 7.4 tests/test_pm_verification.py 补：spec verified 后 `_contract_static_servers[spec]` 驱逐 + serving worktree 移除 + stop 被调；servers.json 登记/清扫回路（含兜底 spawn 登记）
- [ ] 7.5 dev-server.mjs ppid 绑定：杀父后子进程在轮询间隔内退出（ppid 检查逻辑可抽出单测）

## 8. E2E 与验证

- [ ] 8.1 E2E（对齐事故）：起 daemon → 派 run → 中途重启 daemon → run 结束 → 断言 ≤1 个清扫周期内 dev-server 被回收，此后 allocate_port 全段可用
- [ ] 8.2 repair 轮 UI 验证请求全部落该轮专属 dev-server 实例，零请求落主树 8787
- [ ] 8.3 全量单测通过（注意 test_admin.py 等既有环境敏感用例的端口段隔离，必要时 monkeypatch `_port_in_use`）
