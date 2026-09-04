# Proposal: add-interaction-contract-and-per-assert-triage

## Why

v2-overview-page 事故复盘（2026-08-30）：首页项目卡片渲染成可点击外观（amis 卡片默认 link 样式）却从未实现跳转——spec 没写这个需求、验证场景因此没测、6 个失败场景又被整体豁免为 harness 缺陷而放行。暴露两个流程缺口：(1) 「视觉上可交互的元素」可以有未声明的行为期望，实现与验证都无从覆盖；(2) 裁决豁免以场景为单位，单条失败断言背后隐藏的其他缺失行为被连带放行。

## What Changes

- 需求/场景生成阶段引入**交互契约显式化**：页面类 SPEC 的场景集 MUST 覆盖每个「渲染为可交互形态」的元素（按钮/链接样式卡片/可点击行等），或在该元素定义处显式声明「纯展示、不可交互」；既不可交互又无声明的不合格
- 裁决豁免改为**逐断言归因**：failed 场景的每条失败断言 MUST 单独归类（product-bug / test-defect / flaky / env）并附证据；场景级整体豁免仅允许当且仅当其全部失败断言均被单独豁免
- 豁免报告新增「断言级豁免清单」小节（逐条列出断言、归类、证据），供人工复核豁免是否吞掉了真实缺陷
- 实现侧配套：实现 agent 任务书要求「凡渲染可交互形态的元素必须在任务书中定义行为或声明纯展示」——与需求侧契约呼应

## Capabilities

### New Capabilities
- `interaction-contract`: 交互契约显式化（需求起草与场景生成的覆盖要求）+ 裁决逐断言豁免归因

### Modified Capabilities

（无——add-verdict-evidence-taxonomy 的四分类机制是本变更的上游依赖，其规格不需修改；本变更是豁免粒度的细化）
