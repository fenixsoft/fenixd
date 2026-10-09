# 验证报告：evo-fix-v2-devserver-fallback-attribution

> ⚠️ 本报告由框架于 2026-10-03T21:06:33Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-03T21:06:33.137030+00:00+run-result@mtime1791061593166930101

## 结论：✅ 通过（verified）

**状态：verified — 11/11 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 11/11 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 11 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 4.50M |
| 本链增量 Token（输出） | 0.04M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| fbattr-argv-marker-attribution-pytest | 回退形态 argv 归因标记（tasks 1.1）：真起 node 驱动 start()——worktree 缺 core/dashboard/static 时落回主树静态根并在 argv 尾部追加 <wt>/core/dashboard/static 归因标记（dev-server.mjs 位置参数 argv[2]/argv[3] 不可前插），_dev_server_worktree_root 末个命中优先据此归因（框架自身运行于 worktree 的开发态下回退主树静态根 token 同样含 /worktrees/，归属须让位于尾部显式标记）；常态形态（worktree 自带静态根）argv 不追加标记、行为不变；旧版回退存量 argv 仍判不可归因。出处：core/v2_dev_server.py:143-216（start 回退分支与 cmd 组装）、:500-531（解析器）；tests/test_v2_devserver_fallback_attribution.py::TestFallbackAttribution | pass | 0/6 | - |
| fbattr-inflight-run-protected-pytest | 在服 run 免于 skip 告警与收割（验收 1）：归因标记让既有豁免逻辑自然生效——run 在飞（存活 claude 进程引用 worktree）时回退形态 dev-server 不判孤儿、不产生 skip 告警；run 结束（无存活引用）或 worktree 已消失后可判孤儿收割，误报消失同时清力不损失（core/v2_dev_server.py:605-651 豁免/孤儿判定链）。出处：tests/test_v2_devserver_fallback_attribution.py::TestInFlightRunProtected | pass | 0/5 | - |
| fbattr-pid-accounting-wording-probe | pid 记账去重 + 告警文案纠偏独立行为探针（tasks 2.1/2.2，独立于交付测试文件）：spawn 真实 stub 进程（argv0=node，cmdline 含 marker + 主树静态根 token＝不可归因），连续两轮调 _dev_server_orphan_pids——第一轮首见告警恰一条且文案含「勿按存活时长直接 kill」「误杀」风险说明与「首见一次/静默计数」记账说明、不含「可手动 kill」无条件建议；第二轮同 pid 静默（无新告警）；两轮均不判孤儿（永不按记账/裸时长 kill）；记账簿计数随扫描累计（core/v2_dev_server.py:44-50 记账结构、:606-633 记账分支与文案、:652-660 记账簿瘦身）。探针只调 _dev_server_orphan_pids（只读判定），不触 cleanup_orphans。 | pass | 0/10 | - |
| fbattr-project-scoping-probe | pgrep 扫描面按项目收窄独立行为探针（tasks 2.1，双 daemon 不互刷）：他项目 worktree 基路径的 dev-server 进程在本项目 worktree_base 收窄判定下不判孤儿、不告警、不入记账簿；本项目基路径但 worktree 已消失的进程照常判孤儿（收窄不致盲）。daemon 接线：fenixd.py:701-702（启动清扫）与 :990-992（周期清扫）传入 worktree_manager.base_dir。出处：core/v2_dev_server.py:558-604（_argv_touches_worktree_base 收窄判据与分支）。 | pass | 0/7 | - |
| fbattr-warning-wording-guard-pytest | 告警文案守卫（交付测试面，验收 3）：skip 告警 SHALL NOT 含无条件「可手动 kill」建议，须与归因/引用判定联动说明判定局限与误杀在服 run 风险（run 期手动 kill 会打断验证、V2_BASE_URL 悬挂）。出处：core/v2_dev_server.py:620-632 条件文案；tests/test_v2_devserver_fallback_attribution.py::TestWarningWording | pass | 0/3 | - |
| fbattr-restart-reconcile-probe | daemon 重启对账独立行为探针（tasks 2.3，验收 4）：隔离临时项目根写真实 registry，四象限全走 reconcile_v2_servers 真实收割路径——①无主（登记 wt 不存在）→进程被收割、条目摘除、收割告警带 pid；②pid 复用（start_ticks 快照失配）→只摘登记不杀、mismatch 告警留痕；③死 pid →仅摘登记；④有主（wt 存在且有存活 claude 引用）→进程与登记均保留（core/v2_dev_server.py:816-891 reconcile；:756-790 register）。探针 patch _pid_recently_started 越过 60s 启动宽限窗；wt 目录置于 .claude/worktrees/ 下以满足归属引用 pgrep 模式 worktrees/<name>(/\|空白\|$)。 | pass | 0/13 | - |
| fbattr-restart-reconcile-registry-pytest | 重启对账登记契约（交付测试面）：reconcile 四用例（无主收割/有主保留/pid 复用不杀/死条目摘除）+ V2ServerManager launch 成功登记、stop 注销（core/agent_runner/v2_server.py:107-215 _v2_registry_record/_v2_registry_remove 接线）+ 注销幂等与wt_path 过滤 + 登记写失败不阻断派发（best-effort 仅 WARNING）。出处：tests/test_v2_devserver_fallback_attribution.py::TestRestartReconcile | pass | 0/9 | - |
| fbattr-static-symlink-provisioning-pytest | worktree core/dashboard/static 软链 provisioning（tasks 1.2/3.3）：worktree 缺 static 时对框架侧静态根建软链，链接后 start() 走 worktree 路径不再回退主树；已跟踪产物幂等跳过；软链失败仅 WARNING 静默降级、不阻塞 create 派发；EEXIST 竞态容忍；git 不可见性闸门——幂等追加仓库 common dir info/exclude 并 check-ignore 复核（防未跟踪软链击穿空变更 WIP checkpoint 契约）、无法保证忽略时跳过软链。出处：core/worktree_manager/lifecycle.py:32-98（git 判定与 exclude）、:389-397（_provision_worktree_deps 挂载）与 :419-487（_provision_worktree_static_root）；tests/test_v2_devserver_fallback_attribution.py::TestStaticSymlinkProvisioning | pass | 0/8 | - |
| fbattr-v2-devserver-regression-suite | 既有 v2 dev-server 生命周期回归零回退（tasks 3.2，验收 4）：tests/test_v2_dev_server.py 全量通过——归因标记追加不改变既有 argv/pgrep 匹配模式、端口分配与身份收口语义不变（D5 端口段耗尽回退临时端口，不会因在飞 dev-server 占段而失败）。本机实跑基线：23 passed（3.65s）。 | pass | 0/2 | - |
| fbattr-worktree-lifecycle-regression-suite | worktree 生命周期回归零回退（tasks 3.2）：软链 provisioning 挂进 _provision_worktree_deps（create 两出口共用）后，create/reuse/acquire backoff/merge guard 行为不变——tests/test_worktree_reuse.py + tests/test_worktree_acquire_backoff.py + tests/test_worktree_merge_guard.py 全量通过。本机实跑基线：57 passed（3.41s）。 | pass | 0/2 | - |
| fbattr-attribution-full-suite | 专项测试全量（tasks 3.1）：tests/test_v2_devserver_fallback_attribution.py 26 例全绿，覆盖跨类互扰（pid 记账 autouse fixture 用例间清零）与全部七个功能面（argv 归因/在服豁免/pid 记账/项目收窄/文案守卫/重启对账/软链 provisioning）。本机实跑基线：26 passed（1.90s）。 | pass | 0/7 | - |
