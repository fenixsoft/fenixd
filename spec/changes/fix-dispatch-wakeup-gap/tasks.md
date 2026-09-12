## Deliverables

```yaml
- path: core/event_bus.py
  kind: modify
- path: core/pm_engine/engine.py
  kind: modify
- path: core/pm_engine/recovery.py
  kind: modify
- path: tests/test_event_bus.py
  kind: modify
- path: tests/test_pm_recovery.py
  kind: modify
- path: tests/test_run_lifecycle_governance.py
  kind: modify
```

## 1. 依赖定向唤醒（dispatch-dependency-wakeup）

- [ ] 1.1 `core/event_bus.py::_dispatch_changes`：在检出某 SPEC **转入依赖接受态**（`done`/`pushed`/`implemented`/`verified`）时，追加一次 dependents 重评触发；接受态集合与判定口径与 `PMEngine._dependencies_satisfied` 单点一致，不得另立常量之外的判据
- [ ] 1.2 dependents 反查：遍历本次已读入的 `current_specs`，匹配 `depends_on` 含该 SPEC 名字的条目（复用已读入字典，不额外读盘；百量级规模不建反查索引）
- [ ] 1.3 `core/pm_engine/engine.py`：新增 dependents 重评入口——对每个候选 dependent 调既有 `_dependencies_satisfied`，通过且处于可派发态时走与 `spec_ready` **同源的派发入口**入队（不直接调 `_enqueue`），使预算/内容完整性/冻结/去重闸门与冷却全部生效
- [ ] 1.4 幂等与去重：已有活跃派发或已在飞派发（`_pending_dispatches`）的 dependent 不得重复入队；无 dependents 时零副作用、零日志
- [ ] 1.5 异常隔离：dependents 重评的任一异常在本轮内捕获降级为 WARNING，MUST NOT 中断 `_dispatch_changes` 的其他事件派发（沿用 full-scan-resilience 的单条隔离口径）

## 2. 观察项通过条件收紧与就地派发（post-recovery-patrol）

- [ ] 2.1 `core/pm_engine/recovery.py::check_recovery_watch`：把通过判据由「status 与登记时不同」改为声明语义——已进入 `ready` **之后**的后续态（`implemented`/`testing`/`verified`/`done`/`pushed`）或已有活跃派发才判为「已恢复推进」
- [ ] 2.2 判为「尚未恢复推进」（status 为 ready 且无活跃派发，含「登记时 implementing、窗口内回退 ready」）时，先**就地重新派发**该 SPEC，走与 `spec_ready` 同源的派发入口
- [ ] 2.3 就地派发成立 → 关闭观察项且不产生告警；派发未成立（预算/内容完整性/依赖闸门拦截、冻结，或存在活跃派发）→ 关闭观察项并沿用既有 `dispatch_stalled` 信号分支
- [ ] 2.4 保留既有指纹冷却与「spec 已消失则静默关闭」行为不变；`_save_recovery_watch` 的持久化时机不变

## 3. 回归测试

- [ ] 3.1 `tests/test_run_lifecycle_governance.py`：新增「登记时 implementing、窗口内回退 ready」用例——断言判为尚未恢复推进、触发就地派发、观察项关闭且不产生告警（复现 2026-09-12 `fix-root-init-import-shadow` 事故形态）
- [ ] 3.2 `tests/test_run_lifecycle_governance.py`：新增「就地派发被预算闸门拦下」用例——断言关闭观察项且发出 dispatch_stalled 信号，不得静默关闭
- [ ] 3.3 `tests/test_run_lifecycle_governance.py`：保留既有「复查确认已恢复推进」用例语义（进入后续态或已有活跃派发 → 关闭且不告警），确认未被回归
- [ ] 3.4 `tests/test_event_bus.py`：新增依赖唤醒用例——A `depends_on` B，B 由非接受态转 `pushed` 时 A 被立即入队；B 转 `blocked`/`implementing` 时 A 不被唤醒
- [ ] 3.5 `tests/test_event_bus.py`：新增无 dependents 零副作用用例与已有活跃派发时不重复入队的幂等用例
- [ ] 3.6 全量 pytest 回归：确认 `tests/test_event_bus.py`、`tests/test_pm_recovery.py`、`tests/test_run_lifecycle_governance.py`、`tests/test_pm_engine_dispatch_fixes.py` 全绿（基线：`test_recovery_resumes_dispatch` 为改动前既有失败，不在本次范围）

## 4. 验证

- [ ] 4.1 本地构造最小项目复现两类等待场景，确认唤醒发生在**事件到达当轮**而非下一轮 full_scan（对照：改动前需等满一个扫描周期）
- [ ] 4.2 确认未引入新定时器、未改动 `schedule.poll_interval_minutes` 与 `full_scan` 触发源——核对 `core/event_bus.py` 与 `fenixd.py` 主循环的线程/定时器数量与间隔常量无变化
- [ ] 4.3 真实环境观察：daemon 运行期间若出现「依赖刚满足」或「观察项到期」，日志中唤醒与派发的时间差应 < 10 秒量级
