# ADR-042：裁决强制分类 + 证据结构化，LLM 产物由确定性校验器把关

date: 2026-09-06
status: accepted

## Context

裁决链中 warning 无分类依据、failed 场景证据散落合成 md、warning 可无限重复。prompt 约定不能作为防线——LLM 输出漂移会把产品缺陷悬置为 warning，人工考古成本转嫁到下游。

## Decision

- 非 PASS 场景裁决必须四选一分类并附结构化 evidence（从场景执行的 step/assertion 结果中摘取）；分类/证据字段缺失由校验器触发既有裁决重试一次，二次失败 blocked + 告警——宁可不推进也不带病采纳。
- 分类-状态映射在采纳处强制重写：product-bug/test-defect 一律 failed；裁决给 warning 但分类为产品缺陷时以分类为准强制修正并在报告标注「已修正」，防止 LLM 漂移悬置产品缺陷。
- warning 连续性用 verify-progress 侧车文件计数（按 scenario_id），连续 2 轮未消除升级人工告警，并把场景写入下一轮 planner 的「优先复核」注入（与场景冻结基准集同一 prompt 接入点）；场景转 PASS/failed 时清零。
- 校验器为独立纯 Python 模块，LLM 无法经输出文本绕过；旧 report.json 缺新字段按旧逻辑向后兼容解析。

## Consequences

- 产品缺陷不可被输出漂移悬置，证据可机读、可追溯。
- 不合规输出触发重试的额外 judge 调用仅在字段缺失时发生，合规后零成本——比带病采纳后的人工考古便宜。
- flaky 判定滥用（真缺陷标 flaky 悬置）不被分类映射硬拦，由连续性升级 + 告警携带证据摘要供人工甄别兜底。
