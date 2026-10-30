# proposal：周期审查零产物止损——限次重派、升级信号与提示词自救

## 背景

2026-10-23T16:06:06Z 周期审查 run code-review-1792771331 空转 16 轮（9 次 ToolSearch、0.5535 美元）产出零结果行，产物硬门 repo-code-review-gate（core/agent_runner/result_gate.py:1200）拦下空产物入账后，链路仅记 INFO 完成行即收场：无重派、无升级信号，当晚 316 个 manifest 文件、44 个 fix 提交的复审缺口静默悬置 24 小时。硬门拦截同型「拦截后无止损」已三发（2026-09-23 两次产物缺失变体、本次零有效行变体）。

根因核查裁决（对照前夜成功 run code-review-1792684949）：两晚 init 装配与 stderr 完全一致，前夜 agent 同样遇到 ToolSearch 对基础工具回 No matches、随后直接调 Bash 成功；失败 run 9 次调用全耗 ToolSearch、从未直调基础工具。ToolSearch 只索引延迟加载工具，对 Bash/Read/Write/Grep 等回 No matches 属按设计——失败根因是 agent 凭检索空推断工具缺失而放弃，属模型行为方差 × 提示词无自救指引的复合。

## 提案

1. 零产物止损：_run_code_review_checkpoint（core/admin_monitor.py:1710）在产物硬门拦截（零有效行/产物缺失）后自动重派审查 run 至多 1 次（参照同文件 _schedule_ratelimit_redispatch 的限次先例，core/agent_runner/provider_circuit.py:76）；重派仍零有效行则发 admin 升级信号。
2. 失败面外露：拦截时把 run id、manifest 计数与变体（零有效行/产物缺失）透出到完成行与升级告警字段（档案 jsonl 已完整留存 ToolSearch 查询与返回原文，无需新建留存）。
3. 提示词自救：agents/code-review.md 预注指引——ToolSearch 仅索引延迟工具、对基础工具回 No matches 属按设计，直接调用即可；禁止凭检索空推断工具缺失并放弃。

## 非目标

不改动硬门拦截判定本身；不动 429 重派既有机制；不处理 spec-review 车道（归因已由 evo-add-review-failure-attribution 覆盖）。