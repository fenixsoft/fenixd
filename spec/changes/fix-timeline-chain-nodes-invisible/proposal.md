# 提案：SPEC 时间轴处置链节点可见化

## Why

处置链可观测知识页（chain-observability）承诺「SPEC 运行时间轴将处置链各角色记录作为一等节点……配额轨迹可回放」，后端已完备交付（`get_spec_timeline` 下发 `kind="chain"` 节点，字段齐全，`_timeline_sort_key` 给 rank=1 同秒次序），但前端 `SpecTimeline.tsx` 的兜底守卫（`item.kind !== 'run'` → 裸灰点无卡片体）把所有链节点降级为不可见——实证：add-integration-test-env 时间轴中 `chain-handoff`（Admin→Arbiter 转单）、`chain-escalated`（链终点上升）、`chain-closed`（链闭环）三个节点渲染为空 listitem（2026-11-08 浏览器快照取证），用户据此误判「没有 arbiter 处理节点」，配额轨迹不可回放，知识页承诺落空。

## What Changes

- `SpecTimeline.tsx` 新增 `kind === 'chain'` 渲染分支（先于既有兜底守卫）：紧凑链事件卡片——标题行含时间、链里程碑中文标签 Tag（`chain_kind` 映射：链派发/转单 Arbiter/链闭环/链终点上升/复现/choice 执行失败）、`signal_type` 副标签；正文一行展示 `summary`（后端已截断 200 字符）。
- 标签着色语义化：闭环绿、上升/转单橙、派发蓝、复现橙、choice 失败红；未知 `chain_kind` 走中性灰兜底不报错（对齐 `arbiterOutcomeTone` 的 default 语气）。
- 卡片形态复用既有 `cardBox` Bento 磁贴（12px 圆角、发丝边、软阴影）与 `headRow` 范式，不引入新视觉语言。
- 后端零改动：节点字段契约、排序、台账联查、fail-open 均已就绪。

## Capabilities

- `specs/timeline-chain-nodes/spec.md` — ADDED：时间轴处置链节点前端渲染

## Impact

- **受影响模块**：`core/dashboard/static/src/pages/projects/components/SpecTimeline.tsx`（单组件）+ 新增前端测试 `core/dashboard/static/tests/specTimelineChainNodes.test.mjs`。
- **命名防混淆**：state 节点已有 `item.chain`（折叠状态序列数组）字段消费，链节点分支以 `item.kind === 'chain'` 判定，实现时 MUST NOT 触碰 state 分支的 chain 字段逻辑。
- **零后端、零迁移、无新依赖**；测试沿用既有 esbuild + SSR 桩模式（`specTimelineOriginRequest.test.mjs` 先例）。
- 效果：链上处置史（派发→转单→拍板→复现→闭环/上升）在 SPEC 时间轴肉眼可读，arbiter 介入轨迹与既有「质量裁决 Agent」run 卡片互相印证。
