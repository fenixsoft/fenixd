# Capability: admin-awaken-coordination（admin 唤起并发认领守卫）

## 背景与缺口

admin run 唤起链路（告警摄取 → D2b 互斥守卫 → 共享池排队 → worker 启动落 pending DISPOSITION）中，互斥守卫的判定点（摄取线程、提交前，core/admin_monitor.py:4271）与在飞标记的落库点（worker 启动时，core/agent_runner/maintenance_runs.py:489-522）异时点。共享池排队（fenixd.py:765，max_workers=2，与 code-review checkpoint 共池）使时延可达分钟级，期间同 spec 的第二次唤起过守卫时查不到在飞标记而放行，产生并发 admin run。2026-11-14 实例：两 run span 重叠 3.07 分钟、约 8 分钟重复处置。

## 需求

- R1 提交点复查：_invoke_administrator 提交前（submit 入队前；该函数为 admin 派发唯一投递点——全仓 `run_administrator(` 直调仅 core/admin_monitor.py:8429 一处、executor submit 仅 :8641 一处）复查同 spec 在飞态（既有 _has_active_admin_run_for_spec，spec 单键宽口径），命中即让位：走既有 _persist_skipped_disposition（mutex-skip 形态）并 return False，不派发、不产新告警。复查带双前置门（评审补定，缺一即误伤）：①通道门——仅自动唤起（signal_rec 非空）参与，invoke_manual 以 signal_rec=None 直调本函数（:8221），须豁免否则与 R3 冲突；②spec 门——仅 signal["spec"] 非空才判定，spec=None（daemon 级信号）传给 _spec_has_active_admin_run 时 spec 过滤被 None 哨兵禁用（None=不过滤，core/admin_monitor.py:6685-6690 注释在案），不设此门则任意在飞 run 期间全部 daemon 级信号被误让位；四条既有调用车道同款口径先例：摄取 :4333、_handle_signal :5989-5990、重试 :6327、孤儿重派 :6694-6698。
- R2 认领前移：决定派发后、submit 前登记进程内认领条目（spec 维度，锁保护；认领值=属主令牌，登记时生成并随派发上下文携带），使排队中的 run 对后续唤起可见；复查与登记须同一锁临界区原子完成，先登记后 submit，submit 抛出即同锁回滚登记（取代「提交成功才登记」——消除 submit 与登记之间的放行窄窗）；worker 启动后转正式 pending DISPOSITION；worker 终止（成功、失败、异常三路统一）finally 释放认领键，按令牌匹配删除（不匹配即 no-op）。属主令牌为强制约定（评审补定）：run_administrator 为人工通道（invoke_manual）与同步回退共用，其 run 未登记认领，按键无条件删除会在自动 run 仍排队时误放他属认领、重开竞态窗口。同步回退分支（executor 未挂载，fenixd.py:774-777）无排队窗口，登记/释放两分支须同构配对。
- R3 豁免面不变：invoke_manual 人工通道不经互斥与认领（设计内合法并行）；不同 spec 之间互不影响；arbiter 车道单飞自治不动。
- R4 恢复面不变：让位告警保持「未送达/未消费」语义（指纹备忘回滚、巡检周期自然重评、冷却窗、派发失败重试车道、孤儿看护），本能力不新增任何恢复机制。已知窄窗代价（评审登记）：让位若发生在重派车道 superseded 审计（core/admin_monitor.py:6760、:7391）或 bump_dispatch_retry 投递锚（:6411）之后，审计文案与未派发事实短暂不符——在飞覆盖在场时让位方向保守正确（防并行优于审计完美），R5 的 skipped 留痕即对账面（同款问题先例 :6706-6714 已为此把预判前移）。
- R5 可观测：认领命中让位时记 info 日志（含 spec、让位对象标识与认领时刻），与既有 mutex-skip 日志格式一致；命中计数留痕供审计面区分「让位」与「派发」。

## 验收标准

- 同 spec 第二唤起在首 run 已启动 → mutex-skip（现状既有行为，回归保持不回退）。
- 同 spec 第二唤起在首 run 仍在共享池队列（TOCTOU 窗）→ 认领命中，被让位，无第二条 admin run。
- worker 启动失败或异常退出 → 认领释放，后续同 spec 唤起放行。
- invoke_manual 与跨 spec 并行行为与现状一致（不被守卫拦截）。
- 让位后首 run 处置失败时，让位告警按既有未送达语义在下一巡检周期自然重评。