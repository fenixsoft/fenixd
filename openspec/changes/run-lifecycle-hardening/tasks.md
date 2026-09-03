## Deliverables

```yaml
- path: core/pm_engine/dispatch.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: core/agent_runner/liveness.py
  kind: modify
- path: core/config.py
  kind: modify
- path: core/pm_engine/budget.py
  kind: modify
- path: core/verify_engine/engine.py
  kind: modify
- path: tests/test_run_lifecycle_hardening.py
  kind: new
- path: .fenix/config.yaml
  kind: reference
```

## 1 归档自动提交（archive-auto-commit）

- [x] 1.1 push 流程（main-first 尾部）新增归档收口步骤：检测 `openspec/changes/` 下归档移动残留（`git status --porcelain` 过滤该路径前缀的删除与 archive 未跟踪/修改项），存在则 `git add` 限定该路径 + 单 commit（信息 `[fenix] archive: <涉及 spec 名列表> 归档入库`）+ push；无残留零动作
- [x] 1.2 失败降级：归档 commit/push 失败记 WARNING（含 stderr 摘要）并继续流程，spec 终态不受影响，残留留给下次 push 重试；提交内容不含 openspec/changes 之外的任何路径
- [x] 1.3 单测：残留存在→单 commit 收口且 openspec 路径干净；无残留→零 commit 零 push；夹带源码修改时不被卷入；commit 失败→WARNING + 流程继续

## 2 CLI 秒挂退避熔断（cli-retry-backoff）

- [x] 2.1 runner 失败分类：attempt 失败时按进程存活时长判定秒挂（< `agents.instant_fail_threshold_seconds`，默认 60s），框架主动 SIGTERM 的 run 不计入；连续计数挂在 spec 维度（内存表 + 收工时清理）
- [x] 2.2 派发前冷却闸门：连续秒挂 ≥ `agents.instant_fail_cooldown_after`（默认 3）→ 该 spec 冷却 `agents.instant_fail_cooldown_seconds`（默认 300s），冷却期内 implementer/fast-track/repair 派发跳过（DEBUG 日志、不耗预算、不起进程），到期自动恢复且计数清零；成功或存活超阈值的失败均重置计数
- [x] 2.3 告警：首次冷却触发发 major 告警（signal_type=instant_fail_storm，含 spec 名/次数/冷却时长），重复冷却由既有 15 分钟 throttle 抑制
- [x] 2.4 单测：3 次秒挂→冷却生效（派发被跳过、预算不消耗）；到期自动恢复；非连续失败计数归零；告警一次；与 provider 熔断互不干扰

## 3 run_timeout 按 agent_type 覆盖（per-agent-timeout-override）

- [x] 3.1 config.py：新增 `agents.timeout_overrides` 解析与白名单校验（键 ∈ KNOWN_AGENT_TYPES + supervision-judge；值为 ≥300 整数），非法键值整条忽略打 ERROR，新增生效值查询 API（override → 全局默认回退）
- [x] 3.2 runner 生效点：`_execute_agent` 与 `_run_claude` 的 timeout 取值改走生效值查询（七类 agent 全覆盖），supervision 的 extension 总额与 absolute_max 护栏按生效值派生（低于时抬升兜底 + ERROR 留痕）；stuck 阈值派生保持全局默认值语义
- [x] 3.3 liveness.py：`JUDGE_TIMEOUT_SECONDS=120` 常量改读 `agents.timeout_overrides.supervision-judge`（缺省回退 120），不参与 absolute_max 派生
- [x] 3.4 单测：覆盖值生效/未配置回退/非法值整条忽略不崩溃；absolute_max 抬升兜底；stuck 阈值不随覆盖变化；supervision-judge 超时可配置

## 4 生命周期卫生（lifecycle-hygiene）

- [x] 4.1 `_execute_agent` attempt 循环每轮启动前统一检查 spec 的 frozen 字段（覆盖 judge failover 换网关重试等全部重试路径，不止 worktree 失败路径）：frozen 为真立即终止链路、不派发 attempt，run 失败收场保留错误记录；未冻结行为零变化
- [x] 4.2 STATE 路径唯一化：删除 `.fenix/STATE.md` 空文件；全库 STATE 路径引用收敛到项目根单源（grep 审计 `.fenix/STATE.md` 残留引用并修正）
- [x] 4.3 budget.py 对账自动校正：无豁免因素（保留上限/死亡豁免均不适用）的 used 与 runs 实际计数偏差，以 runs 计数为准改写 used 并留 INFO 校正日志（含前后值）；有豁免因素时沿用既有 WARN 不改数
- [x] 4.4 单测：frozen 终止 judge 重试链/未冻结链路不变；对账校正 4→2 与豁免场景不改数

## 5 回归与验收

- [x] 5.1 全量回归：tests/ 既有套件全绿（重点关注 test_state_machine、test_agent_runner、test_mergeback_repair_lane、admin 相关）
- [x] 5.2 真实环境验收：归档残留场景实测（构造一个归档移动 → 触发 push 流程 → 确认自动 commit + push 且主树 openspec 路径干净）；config 追加 timeout_overrides 热加载后生效值打点确认
