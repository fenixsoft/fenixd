## Deliverables

```yaml
- path: spec/changes/add-workspace-row-project-tooltip/plugin-patch/BASELINE.md
  kind: new
- path: spec/changes/add-workspace-row-project-tooltip/plugin-patch/fenix-dsh-dashboard-bridge.patch
  kind: new
- path: spec/changes/add-workspace-row-project-tooltip/plugin-patch/baseline/fenix-dsh-dashboard-bridge/src/client/projectSync.ts
  kind: new
- path: spec/changes/add-workspace-row-project-tooltip/plugin-patch/baseline/fenix-dsh-dashboard-bridge/src/client/panels.tsx
  kind: new
- path: spec/changes/add-workspace-row-project-tooltip/plugin-patch/baseline/fenix-dsh-dashboard-bridge/tests/srcContract.test.ts
  kind: new
```

## 1. 基线快照

- [ ] 1.1 记录宿主基线：`git -C /root/dsh-plugins rev-parse HEAD` 与 `git -C /root/dsh-plugins status --porcelain` 输出写入本 SPEC `plugin-patch/BASELINE.md`（HEAD、快照文件清单、宿主未提交态与恢复备忘）
- [ ] 1.2 把拟触达文件当前内容只读复制进 `plugin-patch/baseline/fenix-dsh-dashboard-bridge/`（`src/client/projectSync.ts`、`src/client/panels.tsx`、`tests/srcContract.test.ts`）

## 2. 数据面投影（宿主仓直改）

- [ ] 2.1 `src/client/projectSync.ts`：项目清单解析从仅取名称升级为保留 ProjectSummary 精简投影 `{name, path, description, daemon, hosting, exists, discovered, status_counts, task_done, task_total, active_runs}`，60s 周期与既有容错纪律不变（exists:false / error 项保留降级标记供 tooltip 回退判定）
- [ ] 2.2 `tests/projectSync.test.ts`：投影解析单测——正常摘要、缺失 description、exists:false 降级项、字段全缺（null 口径）四类 fixture

## 3. 富提示渲染（宿主仓直改）

- [ ] 3.1 新增富提示渲染模块（如 `src/client/wsTooltip.ts`，可按契约自行拆分）：hover 既有 `data-fenix-wsnav` 拦截层 500ms 后于行右侧 portal 渲染深卡（底 #2C2C2E、圆角 16px、标题 #fff 14/20、次文本 #cfd3d6 12/16、阴影与内距按 design.md Context 实测值），show/hide 纯 display 切换零 animation/transition，mouseleave/滚动/行卸载即收
- [ ] 3.2 富提示内容按原型定稿渲染：名称 + 运行态胶囊（运行中 good/未运行 warning/运行中·未托管 warning + 自动发现 muted）、路径、简介一行（空→「暂无简介」）、非零状态胶囊组（STATUS_META 映射 + 方案B 暗面派生色，>4 折叠 +N，全零不渲染）、`任务 x/y 个 · 活跃 Agent n 个`（null→「—」，真实 0 照显，数值 tabular-nums）
- [ ] 3.3 `src/client/panels.tsx`：接入渲染模块——数据失效（exists:false/error/投影缺失）与非 fenix 行回退原生提示；点击导航行为不变；锚点漂移静默降级纪律不变
- [ ] 3.4 `tests/srcContract.test.ts`：钉值更新——状态→tone 映射与暗面派生色常量表、投影键集合、tooltip DOM 契约（锚属性、回退分支、零动画声明）

## 4. 验证与部署（宿主链路）

- [ ] 4.1 插件 vitest 全量绿（`pnpm test`，含新增投影与 tooltip 契约测试）
- [ ] 4.2 `pnpm build`（tsdown，`lib/` 产物经 symlink 即时映射）后 `systemctl restart dsh-web`，从 `/var/log/dsh-web.log` 尾部取新 token URL 重登，playwright 命名会话逐 Scenario 实拍（fenix 行富提示 hover、非 fenix 行原生不变、点击仍进详情、数据失效回退），截图落 `.history/`，确认实拍与 prototype/ 视觉一致（方案B 暗面胶囊）

## 5. 补丁镜像与收口

- [ ] 5.1 `diff -ruN plugin-patch/baseline/ 宿主现状`（仅拟触达文件）落 `plugin-patch/fenix-dsh-dashboard-bridge.patch`；核对 BASELINE.md 与快照清单一致
