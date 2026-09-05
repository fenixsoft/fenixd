# 提案：修复验证裁决可见性断层

## Why

dashboard SPEC 详情页三个页签的数据源行为分裂，导致用户看到矛盾呈现且无处解释：
「运行时间轴」显示验证有失败（如 add-daily-self-review 的 12 通过 1 失败），「失败截图」
页签（`list_screenshots` 直接列目录）照常显示 assert_fail 截图，但「Bug 列表」页签为空——
因为 `parse_bugs` 按 verdict-evidence-taxonomy 的设计正确过滤了非 product-bug 分类
（该失败场景被裁决为 test-defect：断言选择器 `.ant-collapse-content` 在 antd v6 中已改名）。
裁决结论（分类、理由、证据）在前端完全不可见（detail.tsx 未渲染
classification/status_corrected/assertion_triage），用户无法理解「有失败+有截图+无 Bug」。

同一事故的防复发面：verifier 出题时凭训练知识引用框架类名而非实测 DOM，
antd v6 类名改名导致断言选择器失效，已在 add-daily-self-review 与
add-v3-spec-detail-page 两个 spec 连续发生同类 test-defect。

## What Changes

- Bug 列表页签新增「被裁决过滤的失败场景」摘要展示：当存在失败/错误场景被
  分类过滤（test-defect/flaky/env）时，空态不再只显示「暂无 Bug」，
  而是列出这些场景的 id、分类、裁决理由/证据摘要与关联截图。
- 后端 `spec_detail` 响应新增 `filtered_failures` 结构（从 report.json scenarios
  提取 status ∈ fail/failed/error 且 classification ∈ 非 product-bug 分类的场景）。
- verifier 出题约束防复发：出题/断言规则中加入「断言选择器必须来自被测应用
  实测 DOM（playwright 实查），不得凭训练知识引用框架类名」的强制规则
  （antd v6 Collapse 内容类为 .ant-collapse-body/.ant-collapse-panel）。

## Capabilities

### New Capabilities

- `verdict-visibility`: 验证裁决结论在 Dashboard 的可见性——被分类过滤的失败
  场景在 Bug 列表页签以摘要形式可见，消除三页签矛盾呈现。
- `verifier-selector-evidence`: verifier 出题断言选择器的实测来源约束——
  选择器必须来自实测 DOM，防止框架类名知识过期导致的 test-defect 复发。

### Modified Capabilities

（无——verdict-evidence-taxonomy 的分类映射、证据落盘需求不变；本变更只新增
呈现能力与出题约束，不改既有裁决语义。）

## Impact

- `core/dashboard/data.py`：`spec_detail`/`parse_bugs` 附近新增 filtered_failures 提取。
- `core/dashboard/static/src/pages/projects/detail.tsx`：Bug 列表页签空态/摘要渲染。
- `agents/verifier.md`（及 prompt_builder 注入的出题约束段，如需）：新增选择器实测规则。
- 不改裁决语义（enforce_status_mapping、Bug 过滤行为保持不变），不影响 API 兼容性
  （新增响应字段，前端向后兼容旧数据：无 classification 的旧 report.json 不受影响）。
