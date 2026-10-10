# 设计：知识蒸馏批次持久化与崩溃续跑

## D1 台账形态与写入点

- 文件：`<proot>/.fenix/knowledge-distill-pending.json`，结构 `{"batches": [{"names": [...], "queued_at": "<ISO8601>"}]}`。
- 写入点收在 DistillManager.dispatch 单点（单条/批量入口经 _dispatch_via_mgr 汇聚于此），与既有 flock（.fenix/knowledge-distill.lock）不同文件、不互相阻塞——台账写入毫秒级，无需跨进程锁；竞态窗口由「单写者 = 持 self._guard 的 dispatch 线程」消除。
- 原子写复用 core/knowledge_backfill.append_todo_line 同款 tmp+os.replace 手法；读失败/JSON 损坏按空表 fail-open（宁可丢台账不可阻归档——台账丢失的后果退回现状而非更糟）。

## D2 条目清除时机

- 成功路径：_run_batch 拿到 commit（含空串=无变更）后清除。
- 放弃路径：_give_up 中 _discard_output 返回 True（清理确认）后清除；返回 False（回滚未确认）保留条目——工作区可能有残留半成品，重启续跑让校验链重新裁决比留死条目诚实。
- 提交失败滞留路径：保留条目（现行为只登 todo 台账，续跑兜底叠加而非替换）。
- 清除实现为「整文件重读-过滤-原子回写」，避免并发归档入队时整文件覆盖丢条目。

## D3 恢复入口与进程归属

- 新增 `DistillManager.recover_pending(proot) -> int`：读台账 → 逐条调用既有 dispatch 入队（复用全部门控最简；已入库完成的批次条目已被 R2 清除，不存在重蒸风险）→ 清空台账 → 返回恢复数。
- 调用点：FenixDaemon.initialize（fenixd.py:427）末尾，daemon 专属；dashboard --serve 不调用。双进程并存时（dashboard 先起）恢复只等 daemon 下次启动，可接受（蒸馏本就非紧急车道）。
- 恢复日志：「knowledge-distill 恢复重派（N 批：<names>）」。

## D4 _is_idle 第六维度

- 实现：getattr 取蒸馏管理器（命名按现有成员归属，若无独立成员则经 knowledge 模块单例访问器），worker.is_alive() 或 pending 队列非空 → 判非空闲。
- 容错：属性缺失按空闲（与既有「裸对象缺属性视为空」维度同款）；异常按非空闲（宁紧勿松，对齐既有「内部状态不可读按非空闲」）。
- 有界性：RUN_TIMEOUT_SECONDS=1800 × (1+MAX_FIX_ROUNDS=2) 轮 ≈ 90 分钟上界，之后 worker 必然退出，空闲判定恢复——不会复刻「评审车道失明致自愈永久不触发」类风险。
- 注意：台账文件存在但 worker 未起（如恢复前窗口）不判非空闲——判据只看进程内活体状态，避免死台账钉住自愈。

## D5 与既有机制的边界

- knowledge_backfill 回填车道不受影响：其台账独立；回填期排队门控（_gate_distill）拒绝的批次不进 pending。
- 散件巡检（maintree_stray_wip_stale）保留不动：本能力把兜底从「事后 30 分钟宽限 + admin run」前移到「管线内续跑」，巡检退化为真正的最后防线。
- dashboard --serve 与 daemon 的蒸馏 flock 互斥不变；恢复重派的 run 与在飞 run 串行。