## Deliverables

```yaml
- path: core/dashboard/static/src/pages/projects/components/SpecTimeline.tsx
  kind: modify
- path: core/dashboard/static/tests/specTimelineChainNodes.test.mjs
  kind: new
```

## 1. chain 节点渲染分支（SpecTimeline.tsx）

- [x] 1.1 模块级常量：`chain_kind` → {中文标签, 着色} 映射（六种：链派发 blue / 转单 Arbiter gold / 链闭环 green / 链终点上升 orange / 复现 orange / choice 执行失败 red）+ 未知形态中性兜底（「处置链」灰标签）
- [x] 1.2 新增 ChainNode 渲染分支：`item.kind === 'chain'` 先于兜底守卫；卡片复用 `cardBox`/`headRow`（Bento 磁贴），标题行 = 时间 + 链标签 Tag + signal_type 副标签，正文 = summary 一行；圆点色与标签着色同源
- [x] 1.3 命名防混淆红线落地：链节点判定仅以 `item.kind === 'chain'` 为准，state 分支 `item.chain`（折叠状态序列）消费逻辑零改动（代码注释注明）

## 2. 测试（tests/specTimelineChainNodes.test.mjs，esbuild + SSR 桩模式，参照 specTimelineOriginRequest.test.mjs 先例）

- [x] 2.1 六种已知 chain_kind 卡片渲染断言：各自中文标签、着色、signal_type 副标签、summary 正文可见；裸灰点形态退役断言（listitem 含卡片内容结构）
- [x] 2.2 未知 chain_kind（如 "chain-future-kind"）中性兜底断言（灰标签 + summary 照常 + SSR 不抛错）
- [x] 2.3 无链节点零回归断言：仅 state/admin/verify/run 节点时渲染输出不含链卡片结构；state 节点 `item.chain` 折叠序列渲染不受影响

## 3. 自检

- [x] 3.1 `cd core/dashboard/static && node --test tests/specTimelineChainNodes.test.mjs` 通过；既有 `node --test tests/specTimelineOriginRequest.test.mjs` 回归通过
