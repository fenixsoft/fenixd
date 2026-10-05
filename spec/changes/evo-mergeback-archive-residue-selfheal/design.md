## 设计

### 自愈评估挂点

core/pm_engine/dispatch/queue.py 的 _defer_merge_back（:2559）熔断出口（window_exceeded or count >= max_rounds，:2610，该分支 :2610-:2622；:2638/:2648 实为配置访问器 docstring，勿引）前插入 _assess_archive_residue()：

- 判据实现复用/抽取 engine 的 _archive_move_residue（core/pm_engine/engine.py:2941）为共享辅助，落点定 core/archive_commit.py（该归档收口辅助模块已存在），避免两处特征漂移。注意 helper 自身判据是「任一侧即算残留」（engine.py:3015：deleted or (in_archive and added)，单侧删除也计入），自愈授权必须在其上加**同 spec 两侧成对**校验——spec/changes 删除侧与 spec/archive 新增/未跟踪侧同 spec 名成对（git R 重命名行天然成对，engine.py:2990-2997）；仅单侧的半提交形态不授权自动收尾，落回原熔断等人工，防把来历不明的 spec/changes 删除误当残留提交。
- 命中 → 补提交（add 限定为共享辅助返回的**精确残留路径清单**，对齐 engine.py:3061-3067 的逐路径收窄，禁止退回 `git add -- spec`/双前缀通配——code-review 88209fa06ce0 已证前缀式会把其它 spec 在途草案卷进提交；提交消息沿用 `[fenix] archive: <spec 名列表> 归档入库` 形态，engine.py:3060）→ 立即重放既有 merge-back；成功则清理 _merge_retry_* 记账并正常收尾。补提交由重放成功的 merge-back push 携带入库，重放失败时与 _archive_auto_commit 同语义留待后续 push（engine.py:3078-3082），不单独加推。单条至多自动尝试一次的记账用进程内集合，对齐 _spec_dir_inflight_stuck_notified（queue.py:2617）范式，daemon 生命周期内每条目至多一次（重启后至多再试一次）。
- 未命中/失败 → 原路径熔断；_report_mergeback_spec_dir_inflight_stuck（rollback.py:553、:596-599）的告警 evidence 增补自愈评估摘要。

### 周期消费者

新增 _recheck_inflight_deferred_merges：120 秒节拍挂主循环（对齐 _recheck_wip_deferred_merges queue.py:2870 范式），只接手「已超熔断阈值（window_exceeded 或 count >= max_rounds，与 queue.py:2610 同判式）且仍 _merge_retry_pending 且无 _wip_gate_deferred」的条目，重试或保持熔断降级。理由：超阈值后 _defer_merge_back 提前 return 不再排 Timer（:2622），此类条目保证无 Timer 驱动，接手不存在双驱动；未超阈值的条目由 60 秒 merge-only Timer 链驱动（:2623），消费者必须跳过——否则与存活 Timer 链同拍双驱动重试同一分支，git index.lock 竞争的失败会被 bump_counters（:2587）误计入顺延轮数提前熔断。消费者接手重试同样有界：每条目 daemon 生命周期内至多一次额外重试，失败维持既有熔断告警（去重幂等，:2617）与人工通道，不无限节拍重试。记账字段与 WIP 车道混用是代码已明示的接受项（rollback.py:511，原稿误引 queue.py:510-511），不新增字段。

### 与归档侧的关系

归档收口 fail-open（engine.py:3071）不改动——自愈消费者天然覆盖其残留：归档侧收口失败悬置后，下次任何 merge-back 撞上时会被自动收尾；push 尾部兜底（engine.py:3046）继续保留，双保险不互斥。

### 风险

- 误判非归档脏文件为残留：判据要求删除态与 archive 侧新增同时成立且全落 spec/ 路径，测试覆盖混合脏文件用例；单次尝试上限限制误判代价（失败即回人工）。
- 与归档自身收口并发：add 前重查工作区状态，收口已完成则跳过补提交直接重放 merge。