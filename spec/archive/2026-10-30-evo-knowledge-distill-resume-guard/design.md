# 设计：知识蒸馏批次持久化与崩溃续跑

## D1 台账形态与写入点

- 文件：`<proot>/.fenix/knowledge-distill-pending.json`，结构 `{"batches": [{"names": [...], "queued_at": "<ISO8601>"}]}`。
- 写入点收在 DistillManager.dispatch 单点（单条/批量入口经 _dispatch_via_mgr 汇聚于此），与既有 flock（.fenix/knowledge-distill.lock）不同文件、不互相阻塞——台账写入毫秒级，无需跨进程锁；竞态窗口由「单写者 = 持 self._guard 的线程（dispatch 入队追加与 worker 收尾清除都在锁内）」消除。互斥范围仅**进程内**：daemon 与 dashboard --serve 各持独立管理器实例，跨进程并发派发时 tmp+os.replace 整文件覆盖可能丢对方条目——后果等同台账丢失（该批退回现状的内存态），按同一 fail-open 口径接受，不另引入跨进程锁。
- 原子写复用 core/knowledge_backfill.append_todo_line 同款 tmp+os.replace 手法；读失败/JSON 损坏按空表 fail-open（宁可丢台账不可阻归档——台账丢失的后果退回现状而非更糟）。

## D2 条目清除时机

- 成功路径：_run_batch 拿到 commit（含空串=无变更）后清除。
- 放弃路径：_give_up 中 _discard_output 返回 True（清理确认）后清除；返回 False（回滚未确认）保留条目——工作区可能有残留半成品，重启续跑让校验链重新裁决比留死条目诚实。
- 提交失败滞留路径：保留条目（现行为只登 todo 台账，续跑兜底叠加而非替换）。
- 清除实现为「整文件重读-过滤-原子回写」，避免并发归档入队时整文件覆盖丢条目。
- 合并批次清除粒度：worker 把同项目积压队列整体摘下合并为一次 run（_worker 既有行为），收尾清除按**本批 names 并集**匹配移除台账条目（一次清除多条）——若只清「本批最后一条」会漏清先入队条目，陈旧条目会在下次重启对已入库归档触发重蒸（归档目录仍在、门控放行）。

## D3 恢复入口与进程归属

- 新增 `DistillManager.recover_pending(proot) -> int`：读台账 → **先清空台账** → 逐条走既有门控链（_gate_distill + _dispatch_via_mgr）重新入队 → 返回恢复数。顺序 MUST 为「先清空后入队」：台账写点收在 dispatch 单点（D1），恢复重派本身会触发 R1 把条目重新落盘；若先入队后清空，清空会把刚重写的条目一并抹掉，恢复 run 期间台账裸奔（此时崩溃即重演本 SPEC 要修的丢失）。先清空后，门控放行的条目由 R1 立即重新落盘、生命周期交 R2 接管（收尾前始终在册，运行中崩溃可再次恢复）；已入库完成的批次条目已被 R2 清除，不存在重蒸风险；门控拒绝的条目（归档目录缺失/disabled/回填期排队）随清空消失、不复活。
- 残差窗口：先清空与逐条重派之间（毫秒级）崩溃会丢未及重派的条目——与读损坏 fail-open 同口径（退回现状），不为该窗口引入跨文件事务。
- 调用点：FenixDaemon.initialize（fenixd.py:427）末尾，daemon 专属；dashboard --serve 不调用。双进程并存时（dashboard 先起）恢复只等 daemon 下次启动，可接受（蒸馏本就非紧急车道）。
- 恢复日志：「knowledge-distill 恢复重派（N 批：<names>）」。

## D4 _is_idle 第六维度

- 实现：getattr 取蒸馏管理器（命名按现有成员归属，若无独立成员则经 knowledge 模块单例访问器），worker.is_alive() 或 pending 队列非空 → 判非空闲。
- 容错：属性缺失按空闲（与既有「裸对象缺属性视为空」维度同款）；异常按非空闲（宁紧勿松，对齐既有「内部状态不可读按非空闲」）。
- 有界性：上界是**单批**的——RUN_TIMEOUT_SECONDS=1800 × (1+MAX_FIX_ROUNDS=2) 轮 ≈ 90 分钟/批，超时 killpg 后该批必然收尾；worker 整体存活上界 = 待消费批次数 × 单批上界，另含跨进程 flock 阻塞等待（_acquire_file_lock 无超时，他进程持锁期间等待属正常串行）。积压消化期自愈重启被推迟属期望行为（在飞保护正是本 SPEC 目的），且队列单调收敛、消费完即恢复空闲判定——不是「评审车道失明致自愈永久不触发」类永久失明。
- 注意：台账文件存在但 worker 未起（如恢复前窗口）不判非空闲——判据只看进程内活体状态，避免死台账钉住自愈。

## D5 与既有机制的边界

- knowledge_backfill 回填车道不受影响：其台账独立；回填期排队门控（_gate_distill）拒绝的批次不进 pending。
- 散件巡检（maintree_stray_wip_stale）保留不动：本能力把兜底从「事后 30 分钟宽限 + admin run」前移到「管线内续跑」，巡检退化为真正的最后防线。
- dashboard --serve 与 daemon 的蒸馏 flock 互斥不变；恢复重派的 run 与在飞 run 串行。