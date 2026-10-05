## 设计

### 自愈评估挂点

core/pm_engine/dispatch/queue.py 的 _defer_merge_back（:2559）熔断出口（window_exceeded or count >= max_rounds，:2638/:2648）前插入 _assess_archive_residue()：

- 判据实现复用/抽取 engine 的 _archive_move_residue（core/pm_engine/engine.py:2941）为共享辅助（放 core/archive_commit.py 或 dispatch 包内），避免两处特征漂移。
- 命中 → 补提交（add 限定 spec/changes + spec/archive，消息含目标 spec 名）→ 立即重放既有 merge-back；成功则清理 _merge_retry_* 记账并正常收尾。
- 未命中/失败 → 原路径熔断；_report_mergeback_spec_dir_inflight_stuck（rollback.py:553、:596-599）的告警 evidence 增补自愈评估摘要。

### 周期消费者

新增 _recheck_inflight_deferred_merges：120 秒节拍挂主循环（对齐 queue.py:2870 范式），遍历 _merge_retry_pending 且无 _wip_gate_deferred 的条目，到期即重试或按 spec_dir_inflight_grace_minutes（:2626）降级。记账字段与 WIP 车道混用是代码已明示的接受项（queue.py:510-511），不新增字段。

### 与归档侧的关系

归档收口 fail-open（engine.py:3071）不改动——自愈消费者天然覆盖其残留：归档侧收口失败悬置后，下次任何 merge-back 撞上时会被自动收尾；push 尾部兜底（engine.py:3046）继续保留，双保险不互斥。

### 风险

- 误判非归档脏文件为残留：判据要求删除态与 archive 侧新增同时成立且全落 spec/ 路径，测试覆盖混合脏文件用例；单次尝试上限限制误判代价（失败即回人工）。
- 与归档自身收口并发：add 前重查工作区状态，收口已完成则跳过补提交直接重放 merge。