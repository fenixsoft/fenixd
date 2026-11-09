## Deliverables

```yaml
- path: core/dashboard/data/summary.py
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: core/dashboard/static/src/pages/projects/list.tsx
  kind: modify
- path: core/dashboard/static/src/pages/projects/detail.tsx
  kind: modify
- path: tests/test_dashboard_blocked_phase.py
  kind: new
- path: core/dashboard/static/tests/blockedPhase.test.mjs
  kind: new
```

## 1. 后端相位判定字段

- [ ] 1.1 `core/dashboard/data/summary.py` spec summary builder 新增 `blocked_phase` 单点判定（`repairing`/`queued`/`null`）：在飞处置 run 按 `RUN_ID_AGENT_PREFIXES`（`core/agent_runner/run_files.py`）`admin-`/`arbiter-` 前缀过滤并复用 run 元数据 memo 与末行终态/新鲜度口径；链在办件（in_flight 区 `admin`/`arbiter` 相、排除 stale 超时残留）与挂起待处置件（`admin_alerts.json` pending disposition 经 by_run 归并单点、in_flight 区 `deferred` 让行条目；链派发队列无持久载体不作判定源）读既有单源路径；升级 kind 告警不计 `queued`；告警/链文件缺失或损坏时 fail-open 降级（绝不沿 `/api/specs` 链路抛 500）
- [ ] 1.2 新增 `tests/test_dashboard_blocked_phase.py`：覆盖 repairing（在飞 admin/arbiter run、链在办）、queued（挂起待处置、无在飞 run）、null（无任何 agent 迹象/仅升级告警/frozen 等待面）、数据源缺失与损坏容错回退、字段对 STATE.md 真实状态与调度零影响；夹具参照既有 `tests/test_dashboard_data.py` 模式

## 2. 前端三态渲染

- [ ] 2.1 `core/dashboard/static/src/services/dashboard.ts`：`SpecSummary` 类型补 `blocked_phase` 字段并新增相位渲染辅助（`repairing`→「修复中」进行中蓝、`queued`→「排队中」等待橙、其余/缺席/非法值→`statusMeta` 原样），`STATUS_META` 键域与 `statusMeta` 本体不变
- [ ] 2.2 `core/dashboard/static/src/pages/projects/list.tsx` 桌面 Table 状态列与移动端卡片流两处状态标签（`statusMeta` 两个消费点，桌面约 :1096、卡片 `renderItem` 约 :763）：`status=blocked` 且相位命中时经渲染辅助覆盖标签；筛选 Select 选项、状态计数页签、`LIST_STATUSES` 全部不变
- [ ] 2.3 `core/dashboard/static/src/pages/projects/detail.tsx`：详情页头部状态标签与 spec 快速切换下拉共用 2.1 的渲染辅助三态渲染，无平行实现
- [ ] 2.4 新增 `core/dashboard/static/tests/blockedPhase.test.mjs`：三态标签与 tone、`blocked_phase` 缺席/null/非法值回退「阻塞」、非 blocked 状态渲染不受影响

## 3. 回归验证

- [ ] 3.1 跑通后端 pytest 相关面（`tests/test_dashboard_blocked_phase.py`、`tests/test_dashboard_data.py`）与前端 `core/dashboard/static/tests/` 测试，前端构建（`tsc`/产物构建）无类型报错
