## Deliverables

```yaml
- path: core/agent_runner/prompt_builder.py
  kind: modify
- path: core/agent_runner/result_gate.py
  kind: modify
- path: core/dashboard/data/quality_gates.py
  kind: new
- path: core/dashboard/data/__init__.py
  kind: modify
- path: core/dashboard/data/summary.py
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: core/dashboard/static/src/pages/projects/detail.tsx
  kind: modify
- path: core/dashboard/static/src/pages/projects/list.tsx
  kind: modify
- path: tests/test_quality_gates_progress.py
  kind: new
- path: core/dashboard/static/tests/qualityGates.test.mjs
  kind: new
- path: tests/test_dashboard_data.py
  kind: modify
```

## 1. 测试先行（TDD 红）

- [ ] 1.1 新建 `tests/test_quality_gates_progress.py`：合法 quality-gates.json（run 内 3 项落盘、frontend-build 为 skipped+reason）解析用例——items 恒 6 道且顺序符合契约（full-suite/frontend-build/code-review/interaction-contract/result-artifact-gate/deliverable-guard）、done=passed+skipped、total=6、未写入条目为 pending
- [ ] 1.2 容错用例：文件缺失→run 内 3 项 unknown、不抛异常、无 error 字段；JSON 损坏→同上；枚举外 status 或契约外 gate-id（含实现者误写的 code-review 键）→该项按 unknown/容错渲染处理且不崩
- [ ] 1.3 框架 3 项合成用例：STATE=implemented/testing/verified/done/pushed→result-artifact-gate 与 deliverable-guard 均 passed；最新 impl run 为 gate-blocked→result-artifact-gate failed 且 detail 含截断归因；implementing 在飞且无 gate-blocked 痕迹→两守卫项 pending；ocr 车道产物 running→code-review running、completed→passed（detail 含 findings 计数）、unavailable→skipped（detail 含 reason）、产物不可见→pending、指纹陈旧→pending
- [ ] 1.4 worktree 优先用例：implementing 且 worktree 内 quality-gates.json 存在→读 worktree 版本（主树无文件也可见）；worktree 不存在→读主树拷回版本；worktree 存在但 worktree 内无该文件、主树有（fast-track 直落主树形态）→读主树版本；code-review 项对车道产物同策略（worktree 优先、主树兜底）
- [ ] 1.5 `tests/test_dashboard_data.py` 新增 spec_summary 扩展用例：implementing+全勾+门禁可见未了结→`progress_phase: "gates"` 且 gates_done/gates_total/gates_current 透传；任务未全勾→"impl"；门禁全了结→"impl"；quality-gates 不可见（exists=false）→"impl"；testing+ocr 车道 running→"gates"（优先于 verify）；testing+车道非 running→"verify" 回归不变（预期先失败）

## 2. 后端读侧（TDD 绿）

- [ ] 2.1 新建 `core/dashboard/data/quality_gates.py`：契约常量（gate-id 全集与顺序、status 枚举、固定中文 desc）+ 解析合成函数（fail-open、implementing 时 worktree 优先读取、框架守卫 2 项按 run 终态/STATE 合成、code-review 按 ocr 车道产物三态合成并校验指纹、current 进展文案）
- [ ] 2.2 `core/dashboard/data/__init__.py`：新增 re-export 并按 D8 约定在门面文档块登记 patch 缝
- [ ] 2.3 `core/dashboard/data/summary.py`：`spec_detail` 新增 `quality_gates` 字段（exists/done/total/current/items）；`spec_summary` 新增 `gates_done`/`gates_total`/`gates_current` 并在 `progress_phase` 判定单点处扩展 gates 分支（机械条件两支：implementing ∧ 任务全勾 ∧ 门禁可见 ∧ 未全了结；testing ∧ ocr 车道 running，后者优先于 verify）
- [ ] 2.4 跑通 1.x 全部新用例及 `tests/test_dashboard_data.py`、`tests/test_dashboard_mode.py` 既有用例（spec_summary/spec_detail 既有字段零回归）

## 3. 写侧：prompt 注入与守卫宽松对账

- [x] 3.1 `core/agent_runner/prompt_builder.py` implementer 收尾检查注入段（新增独立段，与已退役的内联 ocr 段无耦合）：补 quality-gates.json 契约段——逐字固化路径 `.fenix/verify-progress/<spec>/quality-gates.json`、顶层 schema（gates/updated_at）、gate-id 全集（run 内 3 项：full-suite/frontend-build/interaction-contract，**无 code-review**）与 status 四值枚举、渐进更新要求（每完成一项即全量重写）、frontend-build 仅涉前端改动时执行否则 skipped+非空 reason、写前先创建 `.fenix/verify-progress/<spec>/` 父目录（worktree 内该子目录可能不存在）；注明读侧对 worktree/主树双位置 fail-open 兜底（fast-track 持主树 verify-progress 写授权，允许直落主树）
- [x] 3.2 `core/agent_runner/result_gate.py` impl 产物硬门链路：quality-gates.json 存在时仅做机械合法性检查（JSON 可解析、status 在枚举内、gate-id 在全集内），违规仅记 WARNING 放行；缺失零拦截；不新增任何失败终态与打回路径
- [x] 3.3 写侧单测：注入段含契约路径与键名字面断言；result_gate 对缺失文件零告警零拦截、对坏 JSON 仅 WARNING（caplog 断言）且 run 判定结果不受影响

## 4. 前端类型与详情页「质量门禁」Card

- [x] 4.1 `core/dashboard/static/src/services/dashboard.ts`：`SpecDetail` 增 `quality_gates` 类型（exists/done/total/current/items: {id,desc,status,detail}）；`SpecSummary` 增 gates_done/gates_total/gates_current 可选字段
- [x] 4.2 `core/dashboard/static/src/pages/projects/detail.tsx`：任务清单 Card 之后、验证进度 Card 之前新增「质量门禁」Card——`ProgressBarTile` 参数化可选 strokeColor（门禁橙 #fa8c16）+ 6 道门禁勾选列表（与任务清单同款 Checkbox disabled；passed 勾选+删除线；failed 红色+detail 归因辅助文案；running「进行中」标识；pending 灰色；skipped「不适用」样式区分；unknown「无记录」灰色）；drafted/ready 且 exists=false 不渲染本 Card；其余状态 exists=false 显示「暂无质量门禁记录」空态
- [x] 4.3 前端 node:test 新建 `core/dashboard/static/tests/qualityGates.test.mjs`：状态→渲染语义映射用例（done 计数含 skipped、failed 归因展示、空态与不渲染条件、未知 gate-id 容错不崩、ocr 车道三态映射呈现）

## 5. 前端列表 gates 阶段渲染

- [x] 5.1 `core/dashboard/static/src/pages/projects/list.tsx`：`phasePct` 增 gates 分支（pct(gates_done, gates_total)）；`strokeColorFor`/`trailColorFor` 增门禁橙 `#fa8c16` 与淡橙底轨；文案 `gates_done/gates_total` + `gates_current` 辅助文案（非空才渲染）；run 层线索不渲染；列 sorter 按 phase 切换为门禁完成度；impl/verify 两分支 JSX 与数据源零改动
- [x] 5.2 前端 node:test：gates 阶段渲染映射用例 + impl/verify 渲染零回归断言

## 6. 构建、回归与真实数据冒烟

- [ ] 6.1 worktree 内 `npm run build` 构建通过（dist 不提交，merge 后由框架重建）；`npm test` 全绿
- [ ] 6.2 pytest 后端相关文件全绿（`tests/test_quality_gates_progress.py`、`tests/test_dashboard_data.py`、`tests/test_dashboard_mode.py`）
- [ ] 6.3 worktree 内以独立端口起 daemon + fixture 项目（伪造 quality-gates.json 各状态样本、ocr 车道产物 running/completed/unavailable 样本与 gate-blocked 归因），playwright 截图冒烟：详情页 Card 六状态渲染、进度条从零走、列表 gates 橙条两窗口（implementing 收尾窗 + testing ocr 窗）与辅助文案（截图入 `.history`，不提交）
