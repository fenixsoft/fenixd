# 设计（add-verify-dispatch-single-flight）

## 现状与根因

- 单飞只在 worktree 锁层：core/worktree_manager/lifecycle.py:150-158（lock_key=spec:agent_type，命中即拒）。
- 派发层无在飞预判：core/pm_engine/dispatch/queue.py:70 _active_runs 裸 int；:206-213 _enqueue 与 :227-256 _enqueue_front 去重只查未派发队列条目（本案第一路入队到派发仅约 13ms，队列去重天然看不到）；:930-932 verifier 分支无条件 transition(testing)＋派发，状态机幂等转移不构成闸门；在飞集合先例 _active_reviews/_active_parallel_plans（:83-97）无 verify 车道。
- 三条触发路径：core/pm_engine/engine.py:470/:1457-1478（spec_implemented 事件）、core/pm_engine/dispatch/repair_lane.py:620/:679（repair 链成功/异常尾段 _enqueue_front）、core/admin_monitor.py:4816-4894（复位直通道「verifier 入队重验」）。
- prepare 无护栏：core/verify_contract.py:965-1041 run_prepare_steps cwd=project_root 逐条执行无锁；core/pm_engine/verification/serving.py:926（纯 cli）/:989（web/api）主树路径；唯一主机级锁先例 .fenix/full-suite.lock fcntl（regression.py:114,644）只盖回归套件。
- 退避固定：core/agent_runner/runner.py:3386 (30,60,120)、:3388-3455 _create_worktree_with_backoff；锁侧自带 _lock_since（lifecycle.py:77,158）与 has_active_lock（:346）可支撑锁龄自适应。
- 降级无差别：core/pm_engine/engine.py:2563-2597（:2567 开关、:200 计数、:2583 告警、:2587 legacy 接管）捕获任意异常即降级。
- 实测失配：peer judge 835-988s vs 退避总预算 210s（必然耗尽）；本案代价链=整轮验证作废＋升级告警＋703s admin run＋预算豁免回退＋$1.86 迟到裁决作废＋$1.36 legacy 接管。

## 方案决策

1. 单飞落派发层：DispatchQueue 增 verify 在飞集合（键=spec_name），_enqueue/_enqueue_front 双查「未派发队列∪在飞」；出队分流锁内原子「查在飞→命中即拒绝留痕并丢弃条目→未命中即登记」——在飞登记 MUST 与出队同 _queue_lock 锁段完成（对齐 _active_reviews「出队时置位」先例与 _reviews_dispatching 过渡窗口教训，queue.py:77-97），MUST NOT 延后到线程启动后的「派发成功」点（:930-937）：本案第一路 13ms 即被 pop，若登记晚于出队，第二路恰在「已出队未登记」窗口入队则双查双双落空；收工/异常回滚（:937-950）摘除；repair 尾段与 admin 直通道共用同一守卫入口，存在旁路则在入口补查。
2. 拒绝＋留痕优于排队：「在飞即排队」需引入延迟派发语义；改为拒绝＋结构化留痕＋admin 通道显式放行（对齐 fix-admin-cross-type-duplicate-dispatch 先例）。
3. prepare 护栏二选一：优先 per-run 隔离构建目录（worktree 已隔离的 run 侧成本更低）；不可行处（主树路径 serving.py:926/:989）对 prepare 加 fcntl 主机锁（复用 full-suite.lock 形态，带超时与 pid 记录，残留可诊断）。
4. 退避自适应：预算=max(固定序列, 按锁龄推算的 peer 剩余时长估计)，配置封顶；耗尽走既有 gave up 通道（:3336 文案不变）。
5. 降级分流：engine.py 降级分支按异常分类（worktree 竞争特征），竞争类先重入新流程一次（重试前校验 worktree 锁已释放：lifecycle.has_active_lock/_lock_since——派发在飞集合对同 spec 自指、自身条目必然在飞，无 peer 判别力），仍败才 legacy；非竞争类维持现状。

## 风险

- 单飞误拒合法重验：拒绝留痕＋admin 显式放行兜底。
- fcntl 锁残留/死锁：超时＋pid 记录，复用 conflict-recovery 锁归属诊断思路。
- 自适应等待过长占住派发线程：配置封顶＋超限快速放弃。
- 竞争类重试翻倍烧钱：仅低频竞争类启用且重试前查在飞，频率可控。
- 迟到裁决作废成本（stale 丢弃守卫 pipeline.py:2376-2388 已有）不在本条扩权，仅作成本提示。