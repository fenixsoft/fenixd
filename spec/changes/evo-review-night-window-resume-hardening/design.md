# Design

## 背景与证据

近 3 轮周期审查 2 轮死于夜间断窗收尾（code-review-1791997425：82.983 美元，本地 10-15 04:32；code-review-1792170059：136.197 美元，本地 10-17 04:33），均 ENOTFOUND/CLI Exit 1。两轮死亡派发均发生在 evo-add-review-night-defer-snapshot-writeoff 落地的跨窗顺延守卫（引入 commit 8ca3b2b1f，10-11）生效之下：10-17 01:00:59 派发时守卫取近 3 轮均值 9577.2s（样本 10893/12500/5338），预计结束 03:40:36 判「不相交」放行，实跑 12778s 低估 33%。

## 估计器：均值改 max

- 落点：core/admin_monitor.py:1865-1921（样本采集）与 :1921（sum/len 改 max）。样本数常量 NIGHT_QUIET_DURATION_SAMPLE_LIMIT=3（core/code_fix.py:3254）沿用。
- 3 样本下不做 p90（无统计意义），todo 建议①的「max 或 p90」取 max 形态。
- 已知代价（立项时写明）：审查时长单调上行（近 5 轮 5338→9225→10893→12500→12778s）下，max 估计会把多数 01:00 派发判为跨窗顺延（含 10-16 那轮本会成功的审查）——代价是审查后移至窗后数小时，收益是消除约 110 美元/轮量级的死亡期望；审查为周期任务，后移不丢工作量，核销清锚同步后移不扩大悬置。宁可窗后跑，不可窗内烧。

## 续审：给锚接上既有剃余机制

- 锚 API 已有：core/code_review.py:1669-1692（writeoff-pending.json 读写）；写点 core/agent_runner/maintenance_runs.py:2184-2196、清除点 :2142，本 SPEC 不改。
- 剃余机制已有：core/admin_monitor.py:2116-2138（429 重派以 remaining_manifest 组装剩余清单；core/code_review.py:260 remaining_manifest、:247 cumulative_covered_files），重派 worker :2179-2189。本 SPEC 只把触发条件从「429 意图」扩展到「待核销锚存在」。
- 收尾判定不改：core/agent_runner/maintenance_runs.py:2037-2060 覆盖守卫按 cumulative_covered_files 累计判定，覆盖完整解锁核销、部分覆盖维持抢救红线（两条红线不触碰）。
- todo 建议②（在飞分片边界停等）经架构核实不可靠：分片推进在 agent 侧（agents/code-review.md:28-38 谁审谁写纪律），框架无法可靠暂停 CLI 会话，进程级停等风险高——本 SPEC 以「保守估计拦在派发前＋死后锚驱动剃余续审」组合实现同一意图：穿窗 run 要么被拦在派发前，要么死后只补未落分片。

## 契约与边界

- tests/test_code_fix_night_quiet_window.py:512-513 对 maintenance_runs.py/event_bus.py 有 night_quiet 关键字缺席契约；本 SPEC 改动限于 core/admin_monitor.py（关键字已在册）与测试文件，不触碰该契约。
- 不改 error 收场抢救红线、不改估计样本窗口、不动其他车道窗守卫与缺省窗（归 night-window-guard-coverage-closure）。