# verify-report-gate 能力增量（add-verify-report-gate）

> 保障 `openspec/changes/<spec>/verification-report.md` 在验证裁决放行时必然存在于磁盘。裁决 Agent 主动写入的报告优先；框架合成仅为兜底，不覆盖既有文件。
>
> 注：原规划的「fix SPEC 派生输入校验」已撤销——闸门在裁决采纳时点先行兜底，派生发生在其后（正常流中恒为 no-op），且 add-inplace-bug-repair 将退役 fix 派生路径。

## ADDED Requirements

### Requirement: 验证报告产物闸门

验证裁决产生终局结论（`.fenix-run-result.json` 的 status 为 `verified` 或 `bug-found` 且被框架采纳、状态即将推进）时，框架 MUST 校验 `openspec/changes/<spec>/verification-report.md` 存在：

- 文件存在 → 放行，框架 MUST NOT 覆盖或改写该文件。
- 文件缺失 → 框架 MUST 调用合成器从结构化数据生成该文件后放行，并产生一条告警（复用 human-escalation-alerts 能力）说明「裁决 Agent 未写报告，已由框架合成」。
- 合成器所需结构化数据（`report.json` / `.fenix-run-result.json`）不可用时 → MUST 阻止状态推进（fail-closed），error 字段记录原因，并发送人工升级告警；不得凭空生成空报告放行。

#### Scenario: 裁决 Agent 漏写报告时框架兜底合成

- **WHEN** 某 SPEC 验证裁决返回 `bug-found`，`openspec/changes/<spec>/verification-report.md` 不存在，但 `.fenix/verify-progress/<spec>/report.json` 与 `.fenix-run-result.json` 完整可解析
- **THEN** 框架在状态推进前合成该报告（含「真实产品 Bug」章节及根因、证据），流程正常继续（原地打回/遗留派生等后续处置均可引用），且产生一条兜底合成告警

#### Scenario: Agent 已写报告则原样保留

- **WHEN** 某 SPEC 验证裁决返回 `verified`，spec 目录下已存在裁决 Agent 写入的 `verification-report.md`
- **THEN** 闸门放行且文件内容与 mtime 均不被框架改动

#### Scenario: 结构化数据缺失则阻断并告警

- **WHEN** 报告文件缺失，且 `report.json` 与 `.fenix-run-result.json` 均缺失或不可解析
- **THEN** 状态推进被阻止，error 字段记录「验证报告缺失且无法合成」，产生人工升级告警等待裁决

