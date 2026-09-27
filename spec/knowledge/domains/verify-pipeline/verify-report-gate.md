# 验证报告门
<!-- knowledge: capability=verify-report-gate rev=1 sources=spec/archive/2026-09-04-add-verify-report-gate -->

验证裁决放行时的人读报告产物闸门：`spec/changes/<spec>/verification-report.md` 在状态推进时必然存在，共享合成器兜底。

## 现行规则

- 闸门时点：验证裁决产生终局结论（`.fenix-run-result.json` 的 status 为 `verified` 或 `bug-found` 且被框架采纳、状态即将推进）时，框架校验 `spec/changes/<spec>/verification-report.md` 存在。
- Agent 报告优先：文件已存在时放行，框架不覆盖、不改写该文件（内容与 mtime 均不动）。
- 框架兜底合成：文件缺失时框架调用共享合成器，从结构化数据（`.fenix/verify-progress/<spec>/report.json` 与 `.fenix-run-result.json`）确定性生成报告后放行；合成兜底静默化，不发人工升级告警。
- 结构化数据缺失 fail-closed：报告缺失且 report.json / .fenix-run-result.json 均缺失或不可解析时，状态推进被阻止（fail-closed），error 字段记录「验证报告缺失且无法合成」，并发人工升级告警等待处置；不凭空生成空报告放行。
- 不变量：任何被修复任务引用的 `verification-report.md` 必然存在——要么由裁决 Agent 写入，要么由框架合成。

## 溯源

- 史前复原（存量基线） — 验证报告为产物闸门：共享合成器兜底合成报告，合成兜底静默化不发人工升级告警
- 2026-09-04 add-verify-report-gate — 闸门机械化：裁决放行前强校验报告存在、缺失由共享合成器从结构化数据兜底、结构化数据不可用则阻断推进（裁决 Agent 漏写报告曾致 fix SPEC 盲目引用不存在路径，implementer 只能从第一性原理重复诊断）
