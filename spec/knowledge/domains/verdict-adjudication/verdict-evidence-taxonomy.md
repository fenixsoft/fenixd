<!-- knowledge: capability=verdict-evidence-taxonomy rev=1 sources=spec/archive/2026-09-06-add-verdict-evidence-taxonomy -->

# 裁决证据分类

验证裁决对失败场景的强制分类与结构化证据契约：每个非 PASS 场景必须归入四分类之一并附可核查证据，产品缺陷不得悬置。

## 现行规则

- 每个非 PASS 场景裁决 MUST 输出 `classification` 字段，取值限 `{product-bug, test-defect, flaky, env}`；缺分类或取值非法时裁决输出校验失败，系统以持久化场景集重试一次裁决，二次仍失败则本轮验证按 blocked-env 处理并告警，不产生 bug-found 推进。
- 分类与状态映射约束：`product-bug` 与 `test-defect` MUST 映射为场景状态 failed；`flaky` 与 `env` MAY 映射为 warning；禁止 product-bug 映射为 warning（产品缺陷不得悬置）。
- 每个非 PASS 场景 MUST 在 report.json 条目中附结构化 `evidence`：失败断言列表（type/selector/期望/实际）、截图相对路径、首个失败步骤；证据字段为空按分类缺失同样处理（校验失败重试）。合成验证报告的「真实产品 Bug」小节引用该证据，不重复渲染。
- warning 连续悬置升级：同一场景连续 2 轮判定为 warning 时，第 2 轮裁决采纳处发送 human-escalation-alerts 告警（内容含 spec、场景、连续轮次与最近证据摘要），并将该场景计入下一轮验证的优先复核清单。

## 溯源

- [2026-09-06 add-verdict-evidence-taxonomy](spec/archive/2026-09-06-add-verdict-evidence-taxonomy/) — 确立非 PASS 场景强制四分类、分类-状态映射约束、结构化证据落盘与连续两轮 warning 升级告警
