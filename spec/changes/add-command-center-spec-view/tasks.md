## Deliverables

```yaml
- path: core/dashboard/data/command_center.py
  kind: modify
- path: core/dashboard/routes/command_center_routes.py
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: core/dashboard/static/src/pages/command-center/index.tsx
  kind: modify
- path: core/dashboard/static/src/pages/command-center/OrgGrid.tsx
  kind: modify
- path: core/dashboard/static/src/pages/command-center/shared.ts
  kind: modify
- path: core/dashboard/static/tests/commandCenter.test.mjs
  kind: modify
- path: tests/test_command_center_aggregation.py
  kind: modify
- path: core/dashboard/static/dist/index.html
  kind: reference
```

## 1. 后端：org 需求数量名单派生

- [x] 1.1 `aggregate_org` 的 `summary` 块新增 `specs` 键：现 `spec_count` 统计循环同循环派生 `{project, spec}` 名单，窗口过滤与 created 缺失/脏值规则完全跟随既有口径，排序 created 新→旧（缺失垫底）；既有键（含 `spec_count`）语义零变动
- [x] 1.2 `tests/test_command_center_aggregation.py` 补用例：窗过滤与 created 降序（窗外/已归档 SPEC 不入名单）、全部项目视图跨项目同名双条目、org 既有响应键与改动前等价

## 2. 后端：spec-runs 聚合与端点

- [x] 2.1 `core/dashboard/data/command_center.py` 新增 spec-runs 聚合函数：两步收集——①全史定序（不限窗扫 live+archive 全量产物、LANE_ALIASES 归并、archived_names 剔除同口径、started 升序编 seq=1..N）；②窗内出列（started ≥ win_start 或 all 全史、输出 started 降序）；每轮 `{seq, run_id, started_ts, inflight}`（inflight=IN_FLIGHT_STATUSES 读侧判定）；started 解析失败行跳过不占 seq；lanes 花名册全量出列（零 run 也出、ROSTER 序+观测 lane 殿后）
- [x] 2.2 `core/dashboard/routes/command_center_routes.py` 新增 `GET /api/command-center/spec-runs`：mixin 方法 + `_API_GET_ROUTES` 表驱动追加；project/spec 必填寻址复用 `_command_center_scope` 既有契约（未知项目 200+error 字典）、window 缺省 today 非法值回落
- [x] 2.3 后端测试覆盖 spec-runs 五 Scenario：全史定序窗内出列（today 窗 1 轮显 seq=全史末轮）、花名册全量出列与 dispute-judge→judge / repair→code-fix 归并、归档剔除与损坏行跳过不占 seq、未知项目错误契约、必填参数缺失同族错误契约（不回落跨项目聚合）

## 3. 前端：服务层与纯函数

- [x] 3.1 `services/dashboard.ts` 新增 `commandCenterSpecRuns(project, window, spec)` 与响应类型（lanes/rounds/seq/inflight），`CommandCenterOrg` summary 类型同步 `specs` 名单字段
- [x] 3.2 `shared.ts` 新增纯函数（轮次行 label 组装、选中态与 `summary.specs` 匹配判定、需求数量格可点击态/新派生色常量）+ `core/dashboard/static/tests/commandCenter.test.mjs` 补 node --test 用例（shared.ts 保持零 react/antd import 红线）

## 4. 前端：spec 视图交互与渲染

- [x] 4.1 `index.tsx` specView 选中态提升并深链 URL（`spec` + `spec_project` 双参数写读单点，与 project/window 同款管理；直达链 spec 不在名单时清参数回实时模式），下发 OrgGrid
- [x] 4.2 `OrgGrid.tsx` 需求数量格可点击（cursor pointer + hover 纯色提亮 + 轻量视觉暗示，toggle 退出）+ antd Popover 下拉（Input 本地过滤 + 限高滚动列表 + created 降序 + 全部项目 `project/spec` 消歧/单项目只显 spec 名）
- [x] 4.3 `OrgGrid.tsx` 车道卡活动区 spec 视图分支：spec-runs 走 `useScreenResource`（active=屏激活且选中，refreshKey=`project|win|spec`，60s 轮询防乱序随既有 hook）；有 run 车道渲染 `.cmdcenter-lanescroll` 限高轮次列表（`spec名 · 第N轮` 最新在前、点击行开 `RunRecordModal(run_id, spec_project)`、hover 提亮、run_id 缺失禁点、在飞轮次照常入列可点开）；无 run 显灰虚线框「未运行」（REST_BORDER 同族）；失败保留上轮数据+加载占位（无动画）；车道卡其余四段实时口径不动
- [x] 4.4 红线与 Scenario 自检：轮次列表 DOM 无 animation/transition 字样；org 既有键消费零改动；specs/command-center-console-ui 七个 Scenario 逐条人工核验通过

## 5. 收尾验证

- [x] 5.1 `pytest tests/test_command_center_aggregation.py` 全绿、`node --test core/dashboard/static/tests/commandCenter.test.mjs` 全绿、前端 `npm run build` 构建成功（dist 为运行时重建产物，声明 reference）
