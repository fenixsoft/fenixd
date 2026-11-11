## Deliverables

```yaml
- path: core/dashboard/data/command_center.py
  kind: modify
- path: core/dashboard/data/timeline.py
  kind: modify
- path: core/dashboard/static/src/utils/runVisual.ts
  kind: modify
- path: core/dashboard/static/src/pages/projects/components/SpecTimeline.tsx
  kind: modify
- path: core/dashboard/static/tests/runVisual.test.mjs
  kind: modify
- path: tests/test_command_center_aggregation.py
  kind: modify
- path: tests/test_timeline_arbiter_visibility.py
  kind: new
- path: core/dashboard/static/dist/index.html
  kind: reference
- path: restart_request
  kind: new
```

设计真相源：本 change `design.md`（fast-track 单 Agent 交付）。设计约束以仓库根 `DESIGN.md` 为准（既有界面小改：标签归并 + 节点附加块，无新页面/布局重构，无偏离条款）。台账结构真相源：`core/pm_engine/arbiter.py`（add-arbiter-lane）。

## 1. 指挥中心：arbiter 归并质量裁决

- [x] 1.1 `core/dashboard/data/command_center.py`：`LANE_ALIASES` 新增 `"arbiter": "judge"`（与既有 dispute-judge/repair 同族），注释补记归并理由与消费面边界（组织网格 + spec 视图轮次；时间线/拓扑保持原生 agent_type 的定稿口径不变）；`aggregate_org`/`aggregate_spec_runs` 零逻辑改动（既有归并消费点自动生效）
- [x] 1.2 `tests/test_command_center_aggregation.py` 补用例：含 arbiter run 观测时 org 响应 zones 无 lane=arbiter 卡、judge 卡 runs 计入 arbiter run、judge 卡在飞归属（attributables）含 arbiter run_id；spec-runs 轮次中 arbiter run 以归并后车道出列

## 2. SPEC 时间轴：arbiter 标签与处理记录富展示

- [x] 2.1 `core/dashboard/static/src/utils/runVisual.ts`：`AGENT_LABEL` 加 `arbiter: '质量裁决 Agent'`、`RUN_ID_PREFIX_LABEL` 加 `['arbiter-', '质量裁决 Agent']` 前缀兜底（排在与前缀表顺序敏感性不冲突处）；新增纯函数（如 `arbiterOutcomeLabel(kind)`：disposition→「自主处置」/escalation→「升级人工」/其余→原样透出）供渲染层单源消费
- [x] 2.2 `core/dashboard/data/timeline.py`：`get_spec_timeline` 对 agent_type=arbiter 的 run 节点联查处置台账——台账读侧 MUST 复用 `core.pm_engine.arbiter.load_arbiter_ledger` 单源（自带文件缺失/损坏行 fail-open，防双实现漂移），每次时间轴请求整台账读入一次、循环内内存匹配（MUST NOT 逐 run 重读文件）；run_id 全等匹配、kind 限 disposition/escalation、同 run_id 多条取 created 最新，命中时节点附 `arbiter: {kind, root_cause, action_or_upgrade, signal_type}`（root_cause/action_or_upgrade 截断 200 字符下发）；未命中 fail-open 静默省略（对齐 lane_summary 模式），spec-proposed 条目（run_id=null）不命中
- [x] 2.3 `core/dashboard/static/src/pages/projects/components/SpecTimeline.tsx`：run 节点卡片条件渲染 arbiter 块——结论行（`arbiterOutcomeLabel` 着色区分自主处置/升级人工）+ 根因摘要行 + 处置动作/升级理由摘要行（字段缺失静默省略对应行）；无 `arbiter` 字段的节点渲染逐字节等价现状
- [x] 2.4 测试配套：`core/dashboard/static/tests/runVisual.test.mjs` 补 agentLabel arbiter 两路（agent_type 直配 + 前缀兜底）与 arbiterOutcomeLabel 三分支；新增 `tests/test_timeline_arbiter_visibility.py`（临时工程伪造台账与 run 产物）：disposition/escalation 命中附块且文本截断、spec-proposed 不命中、文件缺失 fail-open、损坏行容错跳过、同 run_id 多条取 created 最新、非 arbiter run 节点零新增字段

## 3. 收尾验证与重启信号

- [x] 3.1 `pytest tests/test_command_center_aggregation.py tests/test_timeline_arbiter_visibility.py` 全绿、`node --test core/dashboard/static/tests/runVisual.test.mjs` 全绿、前端 `npm run build` 构建成功（dist 为运行时重建产物，声明 reference）
- [x] 3.2 restart_request 信号落位（仓库根，JSON：reason/origin/date，reason 注明「指挥中心 arbiter 归并与时间轴 arbiter 富展示为 daemon 内存代码，需重启加载」）+ 消费预演（全新进程 import 链 + org/timeline 两数据函数冒烟自检），实际重启由 supervisor 消费信号完成
