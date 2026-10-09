# 验证报告：evo-stray-untracked-session-attribution

> ⚠️ 本报告由框架于 2026-10-09T19:23:49Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-09T19:23:48.299413+00:00+run-result@mtime1791573828332869378

## 结论：✅ 通过（verified）

**状态：verified — 8/8 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 8/8 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 8 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 2.94M |
| 本链增量 Token（输出） | 0.05M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| untracked-attr-session-hit-resets | R1+R2 越阈归因命中：untracked 越阈集合（6 个≥阈值 5）含活跃会话在场（近窗提交路径交真实现场：isess 身份近窗提交触碰 stray_0.log 后转 untracked），grace=0 下两轮盘点均返回 session-attributed、指纹计时条目被 pop（registry 空）、零 stale/escalated 信号、主树工作区零触碰。出处：core/worktree_manager/stray_wip.py:657-755（_untracked_signal 现状）、:449-500（tracked 流归因同型分支）、core/worktree_manager/mergeback.py:1081-1155（近窗提交判据：身份一致+近窗+路径交） | pass | 0/5 | - |
| untracked-attr-keep-config-legacy | R2 keep 配置回退：同会话现场 + admin.maintree_session_attribution_action=keep，归因视同零命中照常走宽限流——grace=0 即发 info 告警（status=alerted）、计时条目保留（registry 非空、不 pop）、无 escalated。出处：core/worktree_manager/stray_wip.py:197-216（session_attribution_action 读取器与守卫）、spec R2「配置为 keep 时完全回退现状行为」 | pass | 0/4 | - |
| untracked-attr-zero-hit-escalation-evidence | R3 零命中升级 evidence 注记：无会话现场（仓未配身份→归因零命中）越阈集合，第一轮 timed 建档；回拨 first_seen 25h 后第二轮 escalated——升级信号 evidence 含「归因探测已执行」与「零命中」注记字样，info 一次性告警恰一条（宽限流不变）。出处：core/worktree_manager/stray_wip.py:1219-1301（_write_untracked_escalated_alert evidence 组装）、design.md 改动要点 3 | pass | 0/5 | - |
| untracked-attr-threshold-gating | R1 阈值闸门：低于阈值（4<5）集合归因器零调用（spy 计数=0，status=below-threshold）；越阈集合（6≥5）归因器恰调用一次且入参为完整散件路径排序集（status=timed 宽限流不变）。出处：core/worktree_manager/stray_wip.py:673-709（below_threshold 早退分支）、design.md 改动要点 2/4、spec 验收 4（stub 计数断言） | pass | 0/4 | - |
| untracked-attr-runids-threading | tasks 1.2 透传：sweep(running_run_ids=(...)) 时 untracked 流调用归因器收到的 running_run_ids 与传入一致（spy 捕获），且 tracked 干净现场仅 untracked 流调用一次。出处：core/worktree_manager/stray_wip.py:355-424（_sweep_locked 调用点 :424 现状未透传）、design.md 改动要点 1 | pass | 0/3 | - |
| untracked-attr-exemption-clock-reset | tasks 1.3 豁免=时钟复位非永久：stub 归因器三轮换轨（零命中→会话命中→零命中），grace=0 下第一轮 alerted（info 一次性落档）、第二轮 session-attributed 且条目 pop、第三轮重新建档计时再次 alerted（info 告警恰两条）——若豁免是永久保留条目则第三轮不会重复告警。出处：design.md 边界与取舍「豁免=复位而非永久」、core/worktree_manager/stray_wip.py:478（tracked 流 pop 同型） | pass | 0/4 | - |
| untracked-attr-deliverable-test-file | tasks 2.1/2.2 交付物：tests/test_stray_untracked_session_attribution.py 在位且全量通过（四态+evidence 注记覆盖由该文件承载，行为级验收由其余探针场景独立兜底）。出处：spec/changes/evo-stray-untracked-session-attribution/tasks.md Deliverables | pass | 0/3 | - |
| untracked-attr-legacy-regression | R4 tracked 流零改动+回归：tests/test_maintree_stray_wip_sweep.py 与 tests/test_stray_whitelist_untracked.py 既有用例全量通过。出处：spec 验收 5、tasks 2.3 | pass | 0/2 | - |
