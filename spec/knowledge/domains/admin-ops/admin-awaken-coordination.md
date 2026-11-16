# admin 唤起并发认领守卫

<!-- knowledge: capability=admin-awaken-coordination rev=1
     sources=spec/changes/evo-admin-awaken-inflight-claim-guard -->

admin run 唤起链路的并发协调防线：提交点二次复查与进程内派发认领集合共同闭合「互斥守卫判定与在飞标记落库异时点」的 TOCTOU 竞态，杜绝共享池排队窗口内的同 spec 并发 admin run。

## 规则

- **判定与标记异时点是竞态根源**：admin 唤起链路（告警摄取 → D2b 互斥守卫 → 共享池排队 → worker 启动落 pending DISPOSITION）中，互斥守卫在摄取线程提交前判定，在飞标记迟至 worker 真正启动才落库；共享池（max_workers=2，与 code-review checkpoint 共池）排队时延可达分钟级，期间同 spec 第二唤起过守卫查不到在飞标记而放行，产生并发 admin run。守卫经两层闭合。
- **提交点二次复查**：`_invoke_administrator`（admin 派发唯一投递点）submit 入队前再查一次同 spec 在飞态（`_has_active_admin_run_for_spec`，spec 单键宽口径），命中即走既有 `_persist_skipped_disposition`（mutex-skip 形态）让位并 return False——保持「未送达」语义，不派发、不产新告警。
- **复查双前置门**（缺一即误伤）：①通道门——仅自动唤起（signal_rec 非空）参与复查，invoke_manual 以 signal_rec=None 直调须豁免（用户显式呼叫是合法并行面）；②spec 门——仅 signal 的 spec 非空才判定，spec=None 的 daemon 级信号不复查（None 哨兵会禁用 `_spec_has_active_admin_run` 的 spec 过滤，不设此门则任意在飞 run 期间全部 daemon 级信号被误让位）。
- **认领前移**：决定派发后、submit 前登记进程内认领条目 `_ADMIN_DISPATCH_CLAIMED_SPECS`（键=spec、值=属主令牌+认领时刻，锁保护），使排队中的 run 对后续唤起可见；复查与登记同一锁临界区原子完成（防两派发线程各自过判再登记互漏），先登记后 submit，submit 抛出即同锁回滚登记。worker 启动后转正式 pending DISPOSITION。
- **属主令牌释放**：worker 终止（成功、失败、异常三路统一）finally 按令牌匹配释放认领键（`_admin_dispatch_release_claim`，不匹配即 no-op）——run_administrator 为人工通道与同步回退共用（其 run 未登记认领），按键无条件删除会在自动 run 仍排队时误放他属认领、重开竞态窗口。同步回退分支（executor 未挂载）无排队窗口，登记/释放两分支同构配对。跨模块接线用惰导入，禁止模块级导入（admin_monitor → agent_runner 为既有依赖向，反向模块级导入成环）。
- **判重键宽口径**：同 spec 在飞守卫维持 spec 单键宽口径（任意 signal_type），不收窄为 (spec, signal_type)——窄口径漏跨类型并发（fix-admin-cross-type-duplicate-dispatch 实证删除在案）。
- **豁免面不变**：invoke_manual 人工通道不经互斥与认领；不同 spec 之间互不影响；arbiter 车道单飞队列自治不动。
- **让位语义与恢复面不变**：让位告警保持「未送达/未消费」语义——spec_amendment_inflight 指纹备忘回滚（成条预写、未送达回滚，冷却期满可再成条）、摄取让位不 mark_escalated、下一巡检周期自然重评、派发失败重试车道、孤儿看护兜底；零新增恢复机制。
- **存活界**：认领集合为进程内存态，daemon 重启即清、不持久化；孤儿看护对象是 store 内 pending DISPOSITION 记录，与认领集合无交集，不承担认领兜底——泄漏面以进程生命周期为界，finally 统一释放即闭环。
- **已知窄窗代价**：让位若发生在重派车道 superseded 审计或 bump_dispatch_retry 投递锚之后，审计文案与未派发事实短暂不符——在飞覆盖在场时让位方向保守正确（防并行优于审计完美），skipped 留痕即对账面。
- **可观测**：认领命中让位记 info 日志（spec、让位对象标识与认领时刻），与既有 mutex-skip 日志格式一致；命中计数留痕（`_ADMIN_DISPATCH_CLAIM_STATS`）供审计面区分「让位」与「派发」。

## 代码锚点

- 主实现：`core/admin_monitor.py`（提交点复查与认领集合 _ADMIN_DISPATCH_CLAIMED_SPECS、释放 _admin_dispatch_release_claim）
- worker 侧释放：`core/agent_runner/maintenance_runs.py`（_release_admin_dispatch_claim 惰导入接线）
- 守卫测试：`tests/test_admin_awaken_claim_guard.py`

## 溯源

- 2026-11-16 evo-admin-awaken-inflight-claim-guard（spec/changes/evo-admin-awaken-inflight-claim-guard/） — 新增本页：提交点二次复查与复查双前置门、进程内派发认领集合（复查登记同锁原子、属主令牌释放、存活界）、让位语义与恢复面不变、命中计数可观测。背景：2026-11-14 两条唤起 18 秒内先后成 run、span 重叠约 3.07 分钟的 TOCTOU 实例（结论相同零损害，竞态敞口实锤）。
