# SPEC 内容完整性门（空 spec 拦截与已交付分类）
<!-- knowledge: capability=spec-content-integrity-gate rev=2
     sources=spec/archive/2026-09-17-add-spec-content-integrity-gate,spec/archive/2026-09-29-evo-alert-noise-governance -->

派发前校验 SPEC 目录含实质内容，空 spec 不进实现车道、冻结转人工；已交付/终态 spec 不被反向冻结，改产独立信号引导人工裁决。

## 规则

- 派发 implementer 或 fast-track 之前，校验 `spec/changes/<spec_name>/` 是否含认可内容：目录不存在、目录为空、或其中不存在 `proposal.md` / `design.md` / `tasks.md` / `specs/**/*.md` 任一文件时，判为无认可内容；目录内只有非 spec 内容文件（如 `.DS_Store`、日志）时同判。该四类名单即派发内容判据（`spec_has_content`）的唯一口径——验证报告 `verification-report.md` 是验证产物而非起草内容，只可作分类凭据，MUST NOT 进认可名单。
- 按状态分流出四类处置，判定顺序固定：
  1. **blocked 幂等短路**：已处 blocked 的空 spec 再次被派发逻辑评估时不重复发告警，但仍拒绝重派、不回落下一次派发。
  2. **终态豁免**：状态为终态（done/pushed/archived，archived 为向前兼容拼写）时不冻结、不产 spec_content_missing，SPEC 状态保持终态。终态豁免不等于放行派发——只免「冻结 + 告警」处置，不新增任何派发放行语义；终态 spec 出现在派发队列本身属异常，由派发层状态机语义管辖，不由本闸门越权代管。
  3. **「已交付未落盘」分类**：非终态且目录存在 `verification-report.md` 时不冻结，改产独立信号 `spec_delivered_no_content`（major）引导人工裁决——补 tasks.md 归档凭据，或明确废弃后置终态；不冻结是因为冻结会把待裁决 spec 封进 blocked、裁决上下文即丢失。派发拦截语义不变：对该目录 `spec_has_content` 仍判无认可内容，命中即回滚派发槽、不派实现 run，最坏多一条待裁决告警、无预算损失路径。验证报告探测 IO 异常按「无凭据」走既有冻结路径（保守分类）。
  4. **冻结处置**：其余命中经冻结单一入口成对写入——状态置 `blocked` + `frozen`，error 记录「SPEC 内容缺失」原因，回滚队列占用，并发 `signal_type=spec_content_missing`、`severity=major` 的人工裁决告警；唯一出路是补内容后人工解冻。
- 「已交付未落盘」分支自带幂等短路：该分支放弃冻结即失去「status==blocked → 下次短路」的既有幂等保护，而 SPEC 停在 ready 会被恢复精触发（60 秒）与 full_scan 反复命中——已存在同 spec 同 signal_type 的未处理告警时 MUST NOT 追加新告警记录（对齐 admin_monitor 节流的「已有未处理升级告警」判据），仅保持派发拦截，重复命中日志降级 debug 防刷屏。
- 告警生命周期闭环映射：`spec_content_missing` → `spec_terminal_or_unblocked`（SPEC 补内容解冻离开 blocked 或到达终态后自动 resolve）；`spec_delivered_no_content` → 独立条件 `spec_delivered_adjudicated`——仅当关联 SPEC 到达终态才自动闭环，非终态（含 ready/blocked）一律保持原状，待裁决期间告警持续可见。后者 MUST NOT 复用 `spec_terminal_or_unblocked`：该条件仅以 blocked 为未解除出口、对非 blocked spec 一律判「已解除」，复用会使告警在下一轮 auto_resolve 立即闭环、人工无从看见。「补 tasks.md 归档凭据」裁决路径的告警收口为人工 handled 或置终态——闭环判定只读状态表不读目录，不承诺「补内容即自动闭环」。
- 读取目录时 IO 异常（权限、临时不可达）保守放行派发并记 WARNING，不因校验自身故障误伤正常 SPEC。

## 溯源

- 2026-09-17 2026-09-17-add-spec-content-integrity-gate（spec/archive/2026-09-17-add-spec-content-integrity-gate） — 新增内容完整性门：派发前空 spec 判定、冻结处置与 spec_content_missing 告警、告警自动闭环、IO 异常保守放行
- 2026-09-29 2026-09-29-evo-alert-noise-governance（spec/archive/2026-09-29-evo-alert-noise-governance） — 新增终态豁免（done/pushed/archived 短路：不冻结不告警）与「已交付未落盘」独立分类（spec_delivered_no_content 引导裁决、自带查重幂等、派发拦截不变），并注册独立闭环条件 spec_delivered_adjudicated（仅终态自动闭环，不复用 spec_terminal_or_unblocked）
