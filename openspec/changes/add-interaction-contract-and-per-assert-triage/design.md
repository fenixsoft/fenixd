# Design: add-interaction-contract-and-per-assert-triage

## Context

v2-overview-page 事故：卡片有链接样式（amis 默认）但 spec 未定义点击行为 → 实现未做跳转 → 场景集（由 spec 生成）无导航场景 → 6 个失败场景被整体豁免为 harness 缺陷 → pushed。事故后人工热修了跳转（84de42e，app.js 壳层委托）。本 SPEC 防两类复发：需求/场景层的交互覆盖缺口、裁决层的场景级豁免粒度。

## Goals / Non-Goals

- Goals：交互契约显式化（场景生成 + 实现任务书两端）；豁免逐断言归因；断言级豁免清单可复核
- Non-Goals：不做 UI 元素的自动交互探测（扫描渲染树识别可交互形态——成本高误报多，靠场景覆盖要求兜底）；不改四分类定义本身（add-verdict-evidence-taxonomy 已定）；不追溯已 pushed 的 SPEC

## Decisions

### D1 交互契约落在场景生成校验器（与 scenario-freeze 同型）
`.fenix/core/` 新增契约校验逻辑：场景集生成后，校验器检查场景清单对「页面定义中渲染为可交互形态的元素」的覆盖。元素可交互形态的判定采用声明式：SPEC/页面定义中 button/按钮组/含 link 字样 className/卡片渲染循环等模式 → 视为可交互候选；每个候选需有对应交互场景（场景 description 或断言引用元素）或纯展示声明。声明式模式的清单在实现中维护为常量（首版：button-group、button、cards 循环、href/link 字段），可扩展。

### D2 场景-元素映射记入 scenarios.json 元数据
planner 产出时在场景条目上记 `covers` 字段（元素标识），纯展示声明记 `declared-display`。校验器 diff 二者与候选集。旧场景集（无元数据）不追溯，仅新验证轮生效。

### D3 逐断言归因改造裁决输出结构
failed 场景的 `assertion_triage` 数组：每条 {assertion, classification, evidence}。裁决 prompt 要求逐条输出；校验器（verdict_check.py 扩展）验证 failed 场景必有完整 assertion_triage。场景豁免逻辑从「场景级 classification」改为「全断言非 product-bug 才豁免」。

### D4 报告豁免清单由合成器渲染
verify_report.py 从 assertion_triage 汇总「断言级豁免清单」小节。历史报告无此字段时小节缺省（向后兼容）。

### D5 实现任务书模板加契约条款
agent_runner implementer prompt 增加固定条款：可交互形态元素需有 SPEC 定义或任务书声明；发现「待裁决交互」写入 run-result 的 findings（既有 findings 机制）。收工守卫不因此拦截（声明即合规）。

## Risks / Trade-offs

- 声明式候选识别会漏非典型可交互形态 → 与事故场景（卡片类）匹配度已够；清单可迭代
- 逐断言归因增加裁决输出长度（每断言一条）→ 换取豁免可复核性；token 增量 ~10-15%
- 旧 SPEC 场景集无元数据不追溯 → 首轮重验证时自然补齐

## Migration Plan

1. 契约校验器 + planner prompt 注入 + scenarios.json 元数据（一次提交）
2. 裁决 assertion_triage + verdict_check 扩展 + 报告清单渲染
3. implementer prompt 契约条款
无配置变更、无数据迁移。

## Open Questions

（无）
