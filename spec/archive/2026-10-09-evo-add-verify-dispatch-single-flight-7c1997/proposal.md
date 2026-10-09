# add-verify-dispatch-single-flight

## 背景

neutralize-pack-static-fingerprints 验证窗（2026-10-03T16:49-17:21Z）整链：16:49:01.835Z 与 16:49:02.093Z 同 spec 双路验证入队（相隔 0.258s，active_runs 1→2；同一次 repair 链成功尾段的确定性双重入队——spec_implemented 事件＋尾段显式 _enqueue_front，第一路约 13ms 即被 pop 派发、队列去重看不到在飞）→ 两路 prepare 并发跑共享主树 build/（run_prepare_steps cwd=project_root 无锁），一路 clean 擦掉另一路刚归档的 libvdec_app.a → 16:49:26Z 一路 fail-fast 误置 blocked＋verify_env_blocked 升级告警＋预算豁免回退，另一路 7 秒后 prepare 正常通过 → admin 诊断 run 墙钟 703s；17:01:10Z admin 复位直通道第三路入队（active_runs: 3）→ 17:07-17:10Z judge 车道碰撞（1791047232 纯退避 210s 空转）→ gave up 降级旧版 verifier（$1.36/568s）→ 新流程报告缺失由框架代合成 → 迟到 judge 裁决（$1.86/835s）作废。单飞只存在于 worktree 锁层（core/worktree_manager/lifecycle.py:150-158）；派发层无在飞预判（core/pm_engine/dispatch/queue.py:70 裸计数、:206-213/:227-256 去重只查未派发条目、:930-932 verifier 分支无条件派发）；在飞集合先例只有 review/parallel-plan/ocr 车道（queue.py:83-97）。

## 目标

1. verify 车道同 spec 单飞：按 spec 单键维护在飞集合，重复入队拒绝并留痕，覆盖全部三条汇聚路径（spec_implemented 事件、repair 链尾段 _enqueue_front、admin 复位直通道），形态仿 _active_reviews/_active_parallel_plans 先例。
2. prepare 并发护栏：验证契约 prepare 对共享主树构建目录的并发执行加主机级互斥（复用 full-suite.lock fcntl 先例）或 per-run 隔离构建目录。
3. 碰撞退避预算自适应：固定 (30,60,120) 总 210s 与 peer run 实际时长（同窗 835-988s）失配，按锁龄（_lock_since/has_active_lock）自适应延长或提前放弃（配置封顶）。
4. 降级分支分流：worktree 竞争类异常先重试新流程一次再降级 legacy，非竞争类维持直接降级；降级计数与 degrade_context 留痕保留。

## 非目标

- 不重复实现退避等待（evo-add-worktree-acquire-backoff 已落地 (30,60,120) 序列，本条只做预算自适应）。
- 不改 worktree 并发保护语义（dual-dispatch guard 保留，延续 evo-worktree-conflict-recovery-1789359846 非目标）。
- 不做跨 spec 全局并发度控制（只做同 spec 单飞）。
- 不改状态机 testing 幂等转移语义（它不构成派发闸门，闸门加在派发层）。

## 验收

- 构造同 spec 双路入队：第二路被拒并留痕，active_runs 不再同 spec 双计；三条触发路径各一例验证。
- 并发 prepare（单飞被显式绕过或 prepare 复用于其它车道时）：不再出现 clean 擦除并发产物导致的 fail-fast 误报。
- 长锁场景退避不再 210s 定额耗尽；超封顶快速放弃并结构化留痕。
- worktree 竞争类异常不再直接落 legacy（先重试新流程一次），降级留痕保留。
- 既有 worktree backoff、conflict-recovery、admin-cross-type 相关测试零回退。