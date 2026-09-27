## Deliverables

```yaml
- path: core/dashboard/data/timeline.py
  kind: modify
- path: core/dashboard/data/quality_gates.py
  kind: modify
- path: core/dashboard/static/src/pages/projects/detail.tsx
  kind: modify
- path: core/dashboard/static/src/pages/projects/qualityGates.ts
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: core/dashboard/static/tests/qualityGates.test.mjs
  kind: modify
- path: core/dashboard/static/dist/index.html
  kind: reference
```

## 1. 后端时间轴透出（timeline.py）

- [x] 1.1 `core/dashboard/data/timeline.py` run 节点透出车道摘要：`agent_type == 'impl-ocr'` 的 run 节点读其 run 转录 start 事件既有 message，放入节点字段（如 `lane_summary`）；转录缺失/无 start/message 为空时静默省字段，不报错、不新增端点（复用既有 run 元数据读取路径）
- [x] 1.2 最新「→ testing」状态节点附 ocr 门状态：判定时间轴最新的状态转移节点且 `to == 'testing'` 时，import 复用 `core/dashboard/data/quality_gates.py` 的公开入口 `parse_quality_gates`（取 `items` 中 `id == 'code-review'` 项的 `status`/`detail`），节点附 `ocr_gate: {status, detail}` 字段；MUST NOT 复制第二套三态判定、MUST NOT import 私有 `_code_review_status`（绕过 entry/runs 解析）。`get_spec_timeline` 增可选 `entry` 参并由调用方 `spec_detail`（summary.py 调用点已持有 entry）透传，`parse_quality_gates` MUST 与门禁 Card 同参调用（entry 一致才能保证 worktree 候选与指纹校验逐字同源）；非最新/非 testing 节点不附该字段
- [x] 1.3 ocr 门在飞检测补全（`core/dashboard/data/quality_gates.py`，注记可达性前置）：现状 `_code_review_status` 只读磁盘产物，而车道仅在 `run_impl_ocr` 收尾一次性 tmp+replace 落盘 `code-review.json`（status 白名单 `completed|unavailable`，maintenance_runs.py），在飞期磁盘无 `status=="running"` 产物 → running 分支不可达、注记永不渲染。补在飞判据：`parse_quality_gates` 作用域内的 `runs` 中存在 run_id 前缀 `impl-ocr-` 且无终态（`result`/`error` 事件缺失，与既有 no-terminal→running 判定同约定）的 run → `("running", "ocr 并行审查进行中")`，在飞判据优先于磁盘产物状态（重审轮 head 前移后上一轮产物指纹陈旧不可采信）；需将 `runs` 参透传进 `_code_review_status`（parse_quality_gates 已持有，避免二次扫描）。契约源为 quality-gates-progress 既有条文「车道在飞或产物 `status == "running"` 为 running」，属实现补全非新需求；门禁 Card 与 progress_phase 的 ocr running 语义随之恢复契约本义（同源受益，回归点见 3.2）

## 2. 前端呈现（qualityGates.ts 纯函数 + detail.tsx）

- [x] 2.1 `core/dashboard/static/src/pages/projects/qualityGates.ts` 新增注记纯函数（如 `ocrJoinNote(status: string): string | null`）：`running` → 「ocr 审查车道进行中，完成自动推进」，其余状态 → `null`；零 import 约束保持（node:test 可加载）
- [x] 2.2 `core/dashboard/static/src/pages/projects/detail.tsx` 标签补正：`AGENT_LABEL` 增 `'impl-ocr': '代码审查 Agent'`；`RUN_ID_PREFIX_LABEL` 在 `['impl-', …]` 之前插入 `['impl-ocr-', '代码审查 Agent']`（表注释的长前缀优先约定保持）；既有 `impl-` 节点标签行为不变
- [x] 2.3 `core/dashboard/static/src/pages/projects/detail.tsx` 节点渲染：run 节点渲染 `lane_summary` 内容行（缺失不渲染）；状态节点在 `ocr_gate.status === 'running'` 时经 2.1 纯函数渲染注记（含 detail），其余状态不渲染
- [x] 2.4 `core/dashboard/static/tests/qualityGates.test.mjs` 补注记函数断言：running → 注记文案；pending/skipped/completed/unknown → null
- [x] 2.5 `core/dashboard/static/src/services/dashboard.ts` 时间轴节点类型补 `lane_summary?: string`（run 节点）与 `ocr_gate?: { status: string; detail?: string }`（state 节点）——timeline 为闭合 Array 类型形状，缺项时 detail.tsx 读新字段 tsc 编译失败、`npm run build` 不可过

## 3. 构建与回归

- [x] 3.1 `npm run build` 通过且 dist 产物更新（前端改动必须构建落地，验证目标读主树 dist）
- [x] 3.2 定向回归全绿：`qualityGates.test.mjs` node 测试、既有 timeline 相关定向测试、既有 `parse_quality_gates` 定向测试（补/延展 ocr 门在飞合成用例：在飞 `impl-ocr` run → running、completed/unavailable/产物缺失 → 原三态、指纹陈旧 → pending）通过；人工核对点（验证场景覆盖）：时间轴车道节点标签为「代码审查 Agent」、运行中含审查区间内容行、testing 停等注记与门禁 Card 同态且随车道完成翻转消失
