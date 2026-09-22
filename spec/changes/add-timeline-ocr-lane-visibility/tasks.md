## Deliverables

```yaml
- path: core/dashboard/data/timeline.py
  kind: modify
- path: core/dashboard/static/src/pages/projects/detail.tsx
  kind: modify
- path: core/dashboard/static/src/pages/projects/qualityGates.ts
  kind: modify
- path: core/dashboard/static/tests/qualityGates.test.mjs
  kind: modify
- path: core/dashboard/static/dist/index.html
  kind: reference
```

## 1. 后端时间轴透出（timeline.py）

- [ ] 1.1 `core/dashboard/data/timeline.py` run 节点透出车道摘要：`agent_type == 'impl-ocr'` 的 run 节点读其 run 转录 start 事件既有 message，放入节点字段（如 `lane_summary`）；转录缺失/无 start/message 为空时静默省字段，不报错、不新增端点（复用既有 run 元数据读取路径）
- [ ] 1.2 最新「→ testing」状态节点附 ocr 门状态：判定时间轴最新的状态转移节点且 `to == 'testing'` 时，import 复用 `core/dashboard/data/quality_gates.py` 的 ocr 门合成函数取当前状态，节点附 `ocr_gate: {status, detail}` 字段；MUST NOT 复制第二套三态判定（与质量门禁 Card 同源硬约束）；非最新/非 testing 节点不附该字段

## 2. 前端呈现（qualityGates.ts 纯函数 + detail.tsx）

- [ ] 2.1 `core/dashboard/static/src/pages/projects/qualityGates.ts` 新增注记纯函数（如 `ocrJoinNote(status: string): string | null`）：`running` → 「ocr 审查车道进行中，完成自动推进」，其余状态 → `null`；零 import 约束保持（node:test 可加载）
- [ ] 2.2 `core/dashboard/static/src/pages/projects/detail.tsx` 标签补正：`AGENT_LABEL` 增 `'impl-ocr': '代码审查 Agent'`；`RUN_ID_PREFIX_LABEL` 在 `['impl-', …]` 之前插入 `['impl-ocr-', '代码审查 Agent']`（表注释的长前缀优先约定保持）；既有 `impl-` 节点标签行为不变
- [ ] 2.3 `core/dashboard/static/src/pages/projects/detail.tsx` 节点渲染：run 节点渲染 `lane_summary` 内容行（缺失不渲染）；状态节点在 `ocr_gate.status === 'running'` 时经 2.1 纯函数渲染注记（含 detail），其余状态不渲染
- [ ] 2.4 `core/dashboard/static/tests/qualityGates.test.mjs` 补注记函数断言：running → 注记文案；pending/skipped/completed/unknown → null

## 3. 构建与回归

- [ ] 3.1 `npm run build` 通过且 dist 产物更新（前端改动必须构建落地，验证目标读主树 dist）
- [ ] 3.2 定向回归全绿：`qualityGates.test.mjs` node 测试、既有 timeline 相关定向测试通过；人工核对点（验证场景覆盖）：时间轴车道节点标签为「代码审查 Agent」、运行中含审查区间内容行、testing 停等注记与门禁 Card 同态
