# 设计：SPEC 时间轴处置链节点可见化

## Context

后端 `get_spec_timeline`（`core/dashboard/data/timeline.py`）已完整交付链事件节点：

- 节点形态：`{time, kind: "chain", chain_kind, chain_id, signature, signal_type, summary}`（summary 取台账 `action_or_upgrade` 截断 200）。
- `chain_kind` 全集（`_CHAIN_EVENT_KINDS`）：`chain-dispatch` / `chain-handoff` / `chain-closed` / `chain-escalated` / `chain-recurrence` / `chain-choice-failed`。
- 同秒排序：`_timeline_sort_key` 已给 chain 节点 rank=1（与 admin 同层，第三键还原微秒级真实写入序）。
- fail-open：台账缺失/损坏静默省节点。

前端 `SpecTimeline.tsx` 的 kind 分发只处理 `state`/`admin`/`verify`/`run` 四类，其余落兜底守卫（`item.kind !== 'run'` → `return { color: 'gray' }` 裸灰点）——链节点正好落坑，渲染为空 listitem。2026-11-08 浏览器快照实证（add-integration-test-env：e2016/e2080 空条目即 chain-handoff/chain-escalated）。

## Goals / Non-Goals

- **Goals**：六种链事件卡片可见可读；链叙事（派发→转单→拍板/复现→闭环/上升）一眼可回放；与既有 admin 节点、arbiter run 卡片视觉同族。
- **Non-Goals**：不改后端契约与排序；不在链卡片内渲染 markdown 全文（对齐 admin 节点紧凑范式，完整台账仍由运维页处置链视图承载）；不做配额水位图形化（运维页职责）；不处理 spec=null 的链事件（后端已不挂 SPEC 时间轴）。

## Decisions

**D1 分支位置：map 回调中 `item.kind === 'chain'` 分支置于 verify 分支之后、兜底守卫之前。**
兜底守卫语义不变（真正未知 kind 仍降灰点不崩渲染）。

**D2 `chain_kind` → 中文标签与着色映射（模块级常量，对齐 `arbiterOutcomeTone`/`agentLabel` 既有范式）：**

| chain_kind | 标签 | 着色 |
|---|---|---|
| chain-dispatch | 链派发 | blue |
| chain-handoff | 转单 Arbiter | gold |
| chain-closed | 链闭环 | green |
| chain-escalated | 链终点上升 | orange |
| chain-recurrence | 复现 | orange |
| chain-choice-failed | choice 执行失败 | red |

未知 `chain_kind` → 「处置链」中性标签 + 灰 Tag，不报错。圆点色与 Tag 着色同源。

**D3 卡片形态复用 `cardBox`/`headRow`。**
标题行：时间 + 链标签 Tag + `signal_type` 副标签（`Typography.Text` 次要色）；正文：`summary` 一句话（后端已截断）。链节点非 state，天然打断连续前向状态折叠（`_collapse_timeline` 零改动）。

**D4 命名防混淆（实现红线）。**
state 折叠节点已有 `item.chain`（状态序列数组）字段——链节点判定与渲染只走 `item.kind === 'chain'`，MUST NOT 在 state 分支或公共工具层按字段名猜测互串。

**D5 视觉条款对齐 DESIGN.md。**
时间轴节点为 Bento 磁贴形态（2026-11-06 用户指令：12px 圆角、发丝边 `OV_TILE_BORDER`、软阴影 `OV_TILE_SHADOW`、纯白底）——链卡片复用同一 `cardBox`，不引入新视觉语言；设计约束以 DESIGN.md 为准（12px 圆角通用条款）。

## Risks / Trade-offs

- **[卡片密度] 长链多次复现会连续多张卡片** → 接受：链事件本身低频（本案 3 节点），密度即配额轨迹可回放的价值；不做折叠聚合（非目标）。
- **[测试栈] 无 jsdom** → 沿用 esbuild + react-dom/server SSR 桩先例（`specTimelineOriginRequest.test.mjs`），断言标签/着色/summary 渲染输出。
- **[并行改动] `runVisual.ts` 有并行会话在改** → 本 SPEC 交付面不含该文件，映射常量定义在 `SpecTimeline.tsx` 模块内，零交叉。

## 设计约束

设计约束以 DESIGN.md 为准（12px 圆角通用条款）；本 SPEC 无宪法偏离。
