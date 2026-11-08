# 时间轴处置链节点渲染

<!-- knowledge: capability=timeline-chain-nodes rev=1
     sources=spec/changes/fix-timeline-chain-nodes-invisible -->

SPEC 详情页运行时间轴对处置链事件节点（`kind="chain"`）的前端渲染面：链上里程碑（派发→转单→拍板/复现→闭环/上升）以紧凑卡片肉眼可读、配额轨迹可回放。后端节点契约与台账联查 fail-open 归 [处置链可观测](../admin-ops/chain-observability.md) 页。

## 规则

- 节点判定与分支位置：时间轴 kind 分发以 `item.kind === "chain"` 判定链事件节点，走链事件卡片分支（ChainNode）；该分支先于兜底守卫判定。兜底守卫照常生效——真正未知的 kind 仍降级为裸灰点，不崩时间轴渲染。
- 卡片形态：复用 Bento 磁贴范式（`cardBox`：12px 圆角、发丝边、软阴影、纯白底）。标题行 = 时间 + `chain_kind` 中文标签 Tag + `signal_type` 副标签（次要色，缺省省略）；正文一行展示 `summary`（台账处置动作/升级理由摘要，后端已截断 200 字符）。不在链卡片内渲染 markdown 全文（完整台账由运维页处置链视图承载）；纯展示块，无交互形态。
- 六种 `chain_kind` 里程碑标签与着色（圆点色与标签着色同源）：`chain-dispatch`→链派发（blue）、`chain-handoff`→转单 Arbiter（gold）、`chain-closed`→链闭环（green）、`chain-escalated`→链终点上升（orange）、`chain-recurrence`→复现（orange）、`chain-choice-failed`→choice 执行失败（red）。
- 未知 `chain_kind` 安全兜底：台账未来新增而前端未跟的形态渲染中性「处置链」灰标签卡片，summary 照常展示，不报错。`chain_kind` 键查找用自有键防御（hasOwnProperty），防 `'constructor'` 等原型链继承键误命中映射表；`default` 非时间轴圆点合法色，圆点侧归一 gray。
- 命名防混淆红线：state 折叠节点的 `item.chain`（状态序列数组）字段与处置链节点无任何关联，两处消费互不触碰；链节点判定仅以 `item.kind === "chain"` 为准，不得在 state 分支或公共工具层按字段名猜测互串。
- 折叠与零回归：链节点非 state，天然打断连续前向状态转移的折叠（折叠逻辑对链节点零特判）；时间轴数据不含链节点时，四类既有节点（state/admin/verify/run）的渲染与折叠行为与链分支零耦合。

## 代码锚点

- 主实现：`core/dashboard/static/src/pages/projects/components/SpecTimeline.tsx`（`CHAIN_KIND_META` 映射表、`chainKindMeta` 单源取值、`ChainNode` 卡片组件、timeline.map 的 chain 分支）
- 守卫测试：`core/dashboard/static/tests/specTimelineChainNodes.test.mjs`（esbuild + SSR 桩，断言标签/着色/summary 渲染与未知形态兜底）
- 上游节点契约：`core/dashboard/data/timeline.py`（`_CHAIN_EVENT_KINDS` 全集，`get_spec_timeline` 下发 `kind="chain"` 节点）

## 溯源

- 2026-11-08 fix-timeline-chain-nodes-invisible（spec/changes/fix-timeline-chain-nodes-invisible/） — 新增本页：链节点前端渲染分支与六形态标签/着色映射、未知形态中性兜底、命名防混淆红线；此前链节点落兜底守卫渲染为不可见空条目，配额轨迹不可回放
