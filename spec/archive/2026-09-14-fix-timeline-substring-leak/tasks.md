## Deliverables

```yaml
- path: core/dashboard/data.py
  kind: modify
- path: core/dashboard/static/src/pages/projects/detail.tsx
  kind: modify
- path: tests/test_spec_timeline_name_isolation.py
  kind: new
```

## 1. 时间轴名称精确匹配（后端）

- [x] 1.1 前置核对：grep 全库「Updated SPEC」日志写点，确认文案唯一形态为 `Updated SPEC '<name>'`（引号包裹）；若存在未引号写点先统一文案
- [x] 1.2 `get_spec_timeline` 的 `Updated SPEC` 行判定（core/dashboard/data.py 约 :3018）由 `spec_name in msg` 改为 `f"'{spec_name}'" in msg` 带引号全匹配；`Transition:` 正则与 `spec_name not in line` 快筛不动
- [x] 1.3 单测（tests/test_spec_timeline_name_isolation.py）：日志夹具同时含 `Updated SPEC 'add-foo'` 与 `Updated SPEC 'add-foo-ui'`（后者 implemented→testing→verified→done→pushed 级联），断言 `get_spec_timeline('add-foo')` 零泄漏（无 -ui 来源状态节点）、`get_spec_timeline('add-foo-ui')` 自身级联节点完整

## 2. from 推演与方向字段（后端）

- [x] 2.1 打回重建分支（data.py 合流推演处）：按 `_LIFECYCLE_ORDER` 判定节点方向——前向节点无同行 err 时 reason 置空（移除「状态回退」兜底），有 err 时 reason=err 且 `_precise_reason=True`；回退节点维持现状（err 精确 / `_backtrack_reason` 兜底）
- [x] 2.2 state 节点统一输出 `backward` 布尔（`_LIFECYCLE_ORDER.get(to,9) < _LIFECYCLE_ORDER.get(frm,9)`），Transition 解析与打回重建两条路径一致；就近 error 覆写守卫不改动（前向无 err 节点因 reason 为空天然不在射程）
- [x] 2.3 单测：恢复直写行（implementing→ready 带 error）在前缀隔离修复后 from 推演为 implementing→ready 且 backward=true；前向直写行（无 err，10 分钟内有别行 error）reason 空 + backward=false 不被覆写；既有 Transition 回退节点（testing→implementing）reason/徽标数据回归不变

## 3. 前端徽标方向化（前端）

- [x] 3.1 `detail.tsx` 时间轴卡片 `isRollback` 判定由 `!!item.reason` 改为 `item.backward === true`（字段缺失回退旧判定），「↩ 状态回退」徽标不再挂到带 reason 的前向节点；reason 文案展示逻辑不动
- [x] 3.2 回归：dashboard 前端构建零报错（pnpm build），归档/存量无 backward 字段数据渲染不回归
