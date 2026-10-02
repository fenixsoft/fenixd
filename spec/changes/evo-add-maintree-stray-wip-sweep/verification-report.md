# 验证报告：evo-add-maintree-stray-wip-sweep

> ⚠️ 本报告由框架于 2026-10-02T21:55:29Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-02T21:55:28.727883+00:00+run-result@mtime1790978128760586245

## 结论：✅ 通过（verified）

**状态：verified — 18/18 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 18/18 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 18 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 4.02M |
| 本链增量 Token（输出） | 0.04M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| sweep-grace-exhausted-alerts-once | 正向路径·宽限耗尽恰发一次 major 告警（spec 场景「宽限耗尽恰发一次」，如已滞留 31 分钟超 30 分钟宽限）：真实 git 仓散件 WIP 建档后 first_seen 回拨 1 小时 → 恰发一次告警；重复盘点同指纹先查后记去重不重复发送；记录 severity=major、spec=None、evidence 含文件清单/first_seen/归因证据/盲区注记/零触碰注记、recommended_action 指向 git add/commit 或 stash。出处：core/worktree_manager/stray_wip.py:221（宽限判定+escalated_at 一次性去重）、core/worktree_manager/stray_wip.py:260（_write_alert 型制）；tests/test_maintree_stray_wip_sweep.py:151。 | pass | 0/2 | - |
| sweep-grace-zero-escalate-immediately | 边界路径·宽限=0 耗尽即升级：admin.maintree_stray_wip_grace_minutes=0 是合法配置（耗尽即升级，刷屏风险由同指纹一次性去重兜住），首轮盘点即告警且恰一次。出处：core/worktree_manager/stray_wip.py:44（grace_minutes，0 为合法值）；tests/test_maintree_stray_wip_sweep.py:190。 | pass | 0/2 | - |
| sweep-mtime-rewrite-keeps-first-seen | 回归点·mtime 免疫计时（spec 场景「指纹稳定时保持原计时」）：autostash pop 会批量重写改动文件 mtime（实证纳秒级同刻）——同改动集 mtime 被批量重写而路径集与 diff 内容哈希不变时，指纹不变、first_seen 沿用原值不归零、宽限内零告警（D1：计时绝不用 mtime）。出处：core/worktree_manager/stray_wip.py:212（指纹不变沿用原 first_seen）、design.md D1；tests/test_maintree_stray_wip_sweep.py:197。 | pass | 0/2 | - |
| sweep-content-change-new-fingerprint | 异常路径·内容变化换指纹重起算：散件内容再被编辑 → 新指纹、旧条目清除（不残留）、新条目自本轮 fresh 起算（不沿用旧 first_seen，防旧滞留时长错嫁接到新改动上）。出处：core/worktree_manager/stray_wip.py:239（指纹构成：路径排序集+git diff HEAD 哈希）、core/worktree_manager/stray_wip.py:253（_reset_registry_absent）；tests/test_maintree_stray_wip_sweep.py:215。 | pass | 0/2 | - |
| sweep-change-disappears-reset | 删除/撤销·改动消失即复位（spec 场景「改动消失即复位」）：上一周期在场的指纹（散件被人工 git add/commit 处置后——测试现场模拟处置，sweep 自身不触碰主树）本轮不再出现 → 注册表条目清除、status=clean、不告警不残留。出处：core/worktree_manager/stray_wip.py:253（状态复位）；tests/test_maintree_stray_wip_sweep.py:235。 | pass | 0/2 | - |
| sweep-untracked-only-not-counted | 口径边界·纯 untracked 散件不计入：tracked-only 脏判定复用 stash_guard 同一实现（porcelain 口径、untracked 不计），构建产物类 untracked 噪音天然免疫——宽限=0 哨兵形态下纯 untracked 改动仍 status=clean 零告警零建档。出处：core/worktree_manager/stray_wip.py:154（tracked-only 口径）、design.md Risks；tests/test_maintree_stray_wip_sweep.py:251。 | pass | 0/2 | - |
| sweep-lock-busy-abandon-round | 并发边界·主树锁忙弃轮（spec 场景「锁忙时本轮跳过」）：merge-back 的 stash→merge→pop 临界区正持有 _main_tree_lock 时，sweep 非阻塞 acquire 失败即放弃本轮（返回 None、零建档零告警、不留痕为异常）；锁释放后下一轮正常建档。出处：core/worktree_manager/stray_wip.py:128（锁忙放弃）、core/worktree_manager/stash_guard.py:629（同款 acquire(blocking=False) 纪律）、design.md D4；tests/test_maintree_stray_wip_sweep.py:262。 | pass | 0/2 | - |
| sweep-holder-hit-vs-zero-hit | 交互对照·归因命中与零命中分流（spec 场景「在飞车道命中则不告警」+「零命中开始宽限计时」）：同一真实 worktree 车道现场（fenix/spec-x 分支已提交对同一文件的改动、目录名 impl-spec-x-<ts>），传在飞 run_ids → 归因命中（宽限=0 哨兵下必须 status=holder、零告警零建档、重复盘点仍不计时）；不传车道 → 同一现场零命中按无主立即升级（证明夹具交集真实存在、归因器真分流，盲区方向对照）。出处：core/worktree_manager/stray_wip.py:184（identify_wip_occupant 复用，不重造求交）、core/worktree_manager/mergeback.py:675；tests/test_maintree_stray_wip_sweep.py:283（命中）/:298（零命中对照）。 | pass | 0/3 | - |
| sweep-engine-wiring-contract | 接线契约·engine 包装方法供参（2.1 接线）：PMEngine.sweep_maintree_stray_wip 未绑定调用最小装配验证——把 agent_runner._running_agents 的 run_ids 传入归因、WorktreeManager 句柄透传盘点器、盘点器按 wm 句柄身份缓存复用（first_seen 注册表进程内延续，D5）；且刻意无 _active_runs 空闲预检（design D2：加了空闲预检就永远看不到在飞车道、全部按无主升级）。出处：core/pm_engine/engine.py:4492（包装方法）、fenixd.py:896（60s 节拍块挂接）；tests/test_maintree_stray_wip_sweep.py:306。 | pass | 0/2 | - |
| sweep-zero-touch-byte-identical | 零触碰契约·告警前后主树逐字节一致（spec 场景「告警前后主树逐字节一致」）：建档轮→告警轮→复检轮全程 git status --porcelain 输出逐字节一致、stash 栈零变化、HEAD 未动——盘点与升级链路不执行任何 stash/checkout/clean/reset（R4：仅报告，处置权完全留给人工程序）。出处：core/worktree_manager/stray_wip.py:100（_git 只读白名单，模块 docstring 零触碰契约）；tests/test_maintree_stray_wip_sweep.py:343。 | pass | 0/2 | - |
| sweep-admin-monitor-registration | 登记完备性·admin_monitor 三表+摄取形态（spec 场景「告警经监视器摄取唤起」）：SIGNAL_SEVERITY[maintree_stray_wip_stale]=major、SIGNAL_RECOMMENDATION 非空（处置建议：人工提交/stash）、STORED_SIGNAL_TYPES 收录（缺一则记录落 store 后无人摄取、Administrator 不唤起——姊妹信号 mergeback_wip_orphan_stuck 同族对账同为 major）；落盘记录满足摄取门前提：kind=SIGNAL、evidence 以「项目名=」开头且经单源 evidence_project 解析出项目名（无 spec 信号按项目名解析收录）。出处：core/admin_monitor.py:324（SIGNAL_SEVERITY）/:404（SIGNAL_RECOMMENDATION）/:472（STORED_SIGNAL_TYPES）、core/admin_monitor.py:2209（项目名解析收录）与 :2189（摄取门）；tests/test_maintree_stray_wip_sweep.py:366。 | pass | 0/3 | - |
| sweep-grace-config-fallbacks | 配置解析·宽限键缺省与回退：admin.maintree_stray_wip_grace_minutes 经 ConfigLoader 点号键读取，缺省 30；0 合法（耗尽即升级）、45 生效；解析失败/负值/NaN/inf/超一天上限一律回退缺省（配置事故 MUST NOT 放大成「无限期静默等待」极端）。出处：core/worktree_manager/stray_wip.py:44（grace_minutes 守卫语义，对齐 code_fix._orphan_grace_minutes 先例）；tests/test_maintree_stray_wip_sweep.py:126。 | pass | 0/2 | - |
| sweep-full-suite-regression | 回归点·散件 WIP 盘点单测套件全量绿：tests/test_maintree_stray_wip_sweep.py 全部 14 用例（宽限配置/盘点生命周期/归因/零触碰/登记完备 6 组）一次性通过（含真实 git 仓夹具、无环境性跳过）。出处：tests/test_maintree_stray_wip_sweep.py（tasks.md 3.1）。 | pass | 0/2 | - |
| sweep-probe-alert-ondisk | 独立探针·正向告警链路落盘产物（R3 端到端复核，非复跑单测）：以真实 WorktreeManager 全装配（core/worktree_manager/__init__.py:95，含 _main_tree_lock 真锁）+ 真实临时仓散件、宽限=0 耗尽即升级：两轮盘点恰发一次告警（第二轮 orphan-timed 证明一次性去重）；AdminStore 落盘文件 .fenix/admin_alerts.json 真实存在且原文含 maintree_stray_wip_stale；记录 severity=major、evidence 以「项目名=proj」开头、含 first_seen=/文件清单 a.tsx/盲区注记/「未执行 stash/checkout/clean/reset」零触碰注记、recommended_action 同时给出 git add/commit 与 git stash push；全程 git status --porcelain 逐字节一致。探针 stdout 仅输出 JSON 摘要供 json_output 断言。出处：core/worktree_manager/stray_wip.py:260（_write_alert）、core/admin_store.py:116（落盘路径 .fenix/admin_alerts.json）。 | pass | 0/16 | - |
| sweep-probe-clean-and-untracked | 独立探针·干净主树零产出 + untracked 免疫（R1「主树干净时零产出」复核）：干净仓以宽限=0 哨兵形态（若误计任何改动会立即告警）首轮盘点 status=clean、指纹空、注册表零残留、.fenix/admin_alerts.json 不产生、零告警；追加纯 untracked 文件（构建产物噪音形态）后仍零产出零告警——tracked-only 口径（对齐 stash_guard）。出处：core/worktree_manager/stray_wip.py:163（空集直接返回 clean）；design.md Risks。 | pass | 0/9 | - |
| sweep-probe-fingerprint-timing | 独立探针·mtime 批量重写免疫与换指纹重起算（R2「指纹稳定时保持原计时」端到端复核）：宽限 30 建档后以 autostash pop 形态批量重写改动文件 mtime（同一历史时刻、内容不变）→ 指纹不变、first_seen 保持原值不归零、宽限内零告警；随后改动内容改写 → 新指纹、旧条目清除、新条目 fresh 起算（1 分钟内）、注册表恰一条、全程零告警。出处：core/worktree_manager/stray_wip.py:203（first_seen 沿用）/:239（指纹）、design.md D1。 | pass | 0/9 | - |
| sweep-probe-holder-attribution | 独立探针·真实车道现场归因分流（R2「在飞车道命中则不告警」复核）：真实 git worktree 车道分支现场（worktree 目录 impl-spec-x-1700000000、分支 fenix/spec-x-1700000000 已提交对 a.tsx 的改动）+ 主树同文件散件，宽限=0 哨兵：传在飞 run_id impl-spec-x-1700000000-a1 → status=holder、holder_run_ids 命中、注册表零建档、零告警、重复盘点仍不计时；同一现场不传车道 → 零命中立即 alerted（证明夹具交集真实存在的方向对照）。出处：core/worktree_manager/mergeback.py:675（identify_wip_occupant）、core/worktree_manager/types.py:14（WipOccupantInfo + BLIND_SPOT_NOTE）。 | pass | 0/8 | - |
| sweep-probe-lock-discipline | 独立探针·主树锁非阻塞纪律（R1「锁忙时本轮跳过」复核）：外部持有 _main_tree_lock（模拟 merge-back stash→merge→pop 写临界区）→ sweep 非阻塞弃轮返回 None、注册表零建档、零告警；锁释放后下一轮正常建档（orphan-timed、注册表恰一条）——盘点绝不与写临界区并发、也绝不阻塞调用方主循环（design D4，对齐 stash_guard 同款 acquire(blocking=False)）。出处：core/worktree_manager/stray_wip.py:128（锁忙放弃）、core/worktree_manager/lifecycle.py:99（_main_tree_lock 构造）。 | pass | 0/6 | - |
