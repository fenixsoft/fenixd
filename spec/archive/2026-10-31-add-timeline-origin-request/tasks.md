# Tasks: add-timeline-origin-request

## 1. 写侧：fenix-new 立项写入 request.md

- [x] 1.1 修改 `skills/fenix-new/SKILL.md`：在「§3.1 创建 change 脚手架」之后新增「写立项原话」子步骤——把用户本次 /fenix-new 的 ARGUMENTS 原文写入 `spec/changes/<name>/request.md`（UTF-8、原文照录、不做工程化改写）；并写明两条纪律：`--modify` 不更新 request.md（立项原话是历史快照）；request.md 由 skill 步骤运行时产出，不写进 tasks.md 的 Deliverables 声明段

## 2. 读侧：时间轴附着 origin_request

- [x] 2.1 `core/dashboard/data/timeline.py` 的 `get_spec_timeline`：在排序与折叠完成后，经门面 `resolve_spec_dir` 解析 spec 目录（活跃/归档通吃）读取 `request.md`——文件缺失、读取异常、内容 strip 后为空、时间轴无任何 state 节点均静默省字段/不附着（fail-open，对齐 lane_summary 模式；无 state 节点时 MUST NOT 退化挂到 run/verify/admin 等其它 kind 节点）；非空时把原文附到首个 state 节点的 `origin_request` 字段（含折叠链节点），其余节点不携带
- [x] 2.2 新增 `tests/test_spec_timeline_origin_request.py`：覆盖有/无 request.md、归档目录路径解析、折叠链首节点附着、读异常 fail-open、空文件省字段、有 request.md 但时间轴无 state 节点不附着七类场景（fixture 形态参照既有 tests/test_spec_timeline_name_isolation.py）
- [x] 2.3 回归既有时间轴测试（`tests/test_spec_timeline_name_isolation.py` 及 timeline 相关全部用例）零回归

## 3. 前端：渲染原话引用块

- [x] 3.1 `core/dashboard/static/src/services/dashboard.ts`：`TimelineItem` 类型补可选字段 `origin_request?: string`
- [x] 3.2 `core/dashboard/static/src/pages/projects/components/SpecTimeline.tsx`：state 节点渲染分支——节点携带非空 `origin_request` 时，在内容区 from→to 状态行下方渲染原话引用块（多行 `white-space: pre-wrap` 保留换行、次级引用样式与回退 reason 行视觉分层）；字段缺失或空字符串不渲染任何引用块结构
- [x] 3.3 新增前端测试 `core/dashboard/static/tests/specTimelineOriginRequest.test.mjs`（参照既有 static/tests/*.test.mjs 形态）：断言携带 origin_request 的节点渲染引用块、缺失字段不渲染

## 4. 端到端验证

- [x] 4.1 fixture 项目端到端验证：造含 request.md 与不含 request.md 的两个 SPEC（含归档形态各一），调 spec_detail 组装函数断言 origin_request 的出现/缺席与归档路径可达；验证方式参照 dashboard fixture 配方（假项目 + 伪造 STATE.md + spec 目录）
- [x] 4.2 前端 `npm run build` 与 static/tests 全量通过；后端 pytest 时间轴相关用例全量通过

## Deliverables

```yaml
- path: skills/fenix-new/SKILL.md
  kind: modify
- path: core/dashboard/data/timeline.py
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: core/dashboard/static/src/pages/projects/components/SpecTimeline.tsx
  kind: modify
- path: tests/test_spec_timeline_origin_request.py
  kind: new
- path: core/dashboard/static/tests/specTimelineOriginRequest.test.mjs
  kind: new
```
