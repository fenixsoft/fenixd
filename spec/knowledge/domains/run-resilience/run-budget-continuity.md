<!-- knowledge: capability=run-budget-continuity rev=1 sources=spec/archive/2026-09-19-fix-run-hang-amplification -->

# run 预算连续性（跨 attempt 共享预算）

同一 SPEC 的重试 attempt 共享 spec 级累计预算并继承上轮结构化诊断：重派不重置满额预算，也不从零重复探测同一阻塞。

## 现行规则

- 同一 spec 因超时/被杀产生的多次 attempt 计入同一 spec 级预算口径（累计墙钟时长与累计续期次数）；派发新 attempt 前以该累计值扣减本次可用预算，不得让每次重派重新获得完整的 `run_timeout + max_extensions × extension_seconds` 满额预算。
- spec 级累计预算（跨 attempt 求和）耗尽时，spec 收口为可判定终态（blocked 或 failed，沿用既有终态语义）并记录预算耗尽归因，不再按满额重派新 attempt。
- 重派诊断继承：派发新 attempt 时，将上一轮 attempt 的结构化诊断摘要注入新 attempt 的 prompt 上下文——至少包含上一轮终态与归因（超时/被杀/失败）、上一轮已得出的定性结论（若已写入）、上一轮已提交的进度（分支与已勾选任务），使新 attempt 可直接据此改变策略而非重跑同样的探测。
- 继承内容为结构化字段而非上一轮转录原文（控制注入体积），写入 run 文件或等价可读位置供独立查看与审计；首个 attempt（无前置 attempt）不注入占位内容，行为与无继承时一致。

## 溯源

- 2026-09-19 fix-run-hang-amplification（spec/archive/2026-09-19-fix-run-hang-amplification） — 确立跨 attempt 的 spec 级累计预算扣减、耗尽终态收口与上一轮结构化诊断摘要的 prompt 继承
