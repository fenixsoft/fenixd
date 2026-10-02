# 迟到验证结果终态丢弃守卫

<!-- knowledge: capability=verify-late-result-terminal-guard rev=1
     sources=spec/archive/2026-10-02-fix-verify-late-result-terminal-clobber -->

verifier 结果应用前的状态复核防线：只有 SPEC 仍处 `testing` 才允许应用结果，任何非 testing 状态下到达的迟到结果一律零副作用丢弃——终态不可被在飞结果覆写。

## 规则

- 状态复核全覆盖：所有会写 SPEC 状态的 verifier 结果应用分支，先于任何 `update_spec`（含状态覆写、error 写入、infra 记账）复核当前状态——仅当状态为 `testing` 才允许应用；否则以 DEBUG 日志丢弃（记录丢弃原因与当前状态），不改变任何状态字段、不触发 re-dispatch、不记账 infra failure。
- 覆盖三分支：foreign-role/foreign-stamp 分支、unknown-status 且 stale 分支、成功路径 stale 守卫分支；判据 `_cur != "testing"` 与同文件 bug-found/verified/进程失败分支既有判据同构。
- 复核为分支内首个判据：先于 `_verified_gate_refuses` 等既有门禁，终态 SPEC 不再消耗门禁判定与日志噪音。
- 丢弃零记账：丢弃时不调 `_record_infra_failure`——终态 SPEC 记 infra 是噪音，且该记账附带预算豁免，对终态无意义。
- 入口判据不替代二次复核：结果处理入口的「派发时是 testing」判据保持不变，但它只保证派发时刻的状态；在飞 run 可长达数十分钟，期间状态可合法流转至终态——终态被迟到结果覆写会触发状态抖动与一轮冗余全量重验，结果应用时的二次复核不可省。
- testing 内语义不变：结果到达时 SPEC 处于 `testing`，stale/foreign 判定的既有行为保持——回退 implemented、写 re-dispatch error、infra 记账、重派新验证；本能力为纯增防御，不改变 testing 内并发车道语义。

## 溯源

- 2026-10-02 fix-verify-late-result-terminal-clobber（spec/archive/2026-10-02-fix-verify-late-result-terminal-clobber） — 新增 foreign / unknown-status+stale / 成功路径 stale 守卫三个结果应用分支的应用前状态复核：非 testing 的迟到结果一律 DEBUG 丢弃，零状态覆写、零记账、零重派（2026-09-24 实证机械车道已推送终态后，42 分钟在飞 LLM verifier 完成时把 pushed 覆写回 implemented）
