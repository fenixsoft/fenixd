## Deliverables

```yaml
- path: core/dashboard/routes/architecture_routes.py
  kind: new
- path: core/dashboard/server.py
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: core/dashboard/static/src/pages/projects/components/ArchitectureTab.tsx
  kind: new
- path: core/dashboard/static/src/pages/projects/list.tsx
  kind: modify
- path: core/dashboard/static/src/pages/projects/listFilters.ts
  kind: modify
- path: core/dashboard/static/tests/listFilters.test.mjs
  kind: modify
- path: tests/test_dashboard_architecture_api.py
  kind: new
- path: docs/help/08-dashboard.md
  kind: modify
- path: core/dashboard/static/dist/index.html
  kind: reference
```

## 1. 后端：架构图路由与生成管理器

- [x] 1.1 新建 `core/dashboard/routes/architecture_routes.py`：`ArchitectureManager`
      （per-project 单飞锁、在飞进程句柄、`none/generating/ready/failed` 状态机、
      `.fenix/architecture/status.json` tmp+rename 原子写，结构含
      `state/generated_at/started_at/error/duration_ms/component_count`）+ 3 端点
      （`GET /api/architecture/status`、`POST /api/architecture/refresh`、
      `GET /api/architecture/diagram`，project 走 query string，mixin 形态
      `self._json`/`self._error`；diagram 未生成时返回结构化错误）
- [x] 1.2 spawn 实现：`Popen(["claude","-p",prompt,"--permission-mode","bypassPermissions"],
      cwd=项目根, start_new_session=True)`，env 同 SessionManager 口径剔除
      `FENIX_RUN_PROJECT_ROOT`/`FENIX_RUN_WORKTREE`/`CLAUDE_CODE_ENABLE_TODO_TOOLS`，
      `communicate(timeout=1800)` 超时 `os.killpg` 进程组击杀（孙进程一并），判
      `failed` 且 error 注明超时
- [x] 1.3 archify skill 可用性：spawn 前探测 `$CLAUDE_CONFIG_DIR/skills/archify/SKILL.md`
      与 `~/.claude/skills/archify/SKILL.md` 双路径；缺失时后台线程先跑
      `subprocess.run(["npx","skills","add","tt-a1i/archify","-g"], timeout=120)`，
      失败/超时判 `failed` 且 error 原样含 `npx skills add tt-a1i/archify -g`
- [x] 1.4 中文生成提示词组装：五项形态约束（仅 8–16 个核心组件 / 突出且仅一条主要路径 /
      标出外部依赖与信任边界 / 辅助信息进说明卡片不增加连线 / 节点与说明中文标注）+
      产物写盘绝对路径（`.fenix/architecture/diagram.html`）+ stdout 末行
      `ARCHIFY_DONE <组件数>` marker 协议
- [x] 1.5 产物权威判定链（不信 claude 自述）：退出码 → diagram.html 存在且非空 →
      自包含 HTML 特征（`<!DOCTYPE html`/`<html` 前缀）→ 组件数提取（marker 或产物
      可提取时校验 ∈[8,16]，越界判 `failed` 并注明实际数量；无法提取记
      `component_count: null` 放行）；daemon 重启后 `status.json` 残留 `generating`
      且在飞线程/进程不在时，读侧合成 `failed`（生成被中断）
- [x] 1.6 `core/dashboard/server.py` 接线新 mixin `H13ArchitectureRoutesMixin`
      （对齐 `H12RegressionRoutesMixin` 汇聚方式；H12 编号已被 Regression 占用）

## 2. 前端：项目架构页签

- [x] 2.1 `core/dashboard/static/src/services/dashboard.ts` 新增 3 个 API 函数
      （getStatus / refresh / diagramUrl），对齐既有函数形态与错误处理
- [x] 2.2 新建 `core/dashboard/static/src/pages/projects/components/ArchitectureTab.tsx`：
      `project`+`active` props，active 门控（未选中零请求）；四态渲染——`none` 空态
      文案+「刷新架构图」按钮 / `generating` 3s 轮询+按钮置灰+生成中提示 /
      `ready` `<iframe sandbox="allow-scripts">`（不带 allow-same-origin）加载
      diagram 端点+生成时间元信息+可再刷新按钮 / `failed` 错误信息展示+按钮恢复可点；
      显式 flex 容器定高（桌面/移动两档高度常数，useIsMobile 切换，minHeight 兜底）
- [x] 2.3 `core/dashboard/static/src/pages/projects/list.tsx` 页签数组在
      `regression`（测试回归）之后、`session`（会话接入）之前插入
      `{key: 'architecture', label: '项目架构'}` 项，children 挂 ArchitectureTab
      并按 `activeTab === 'architecture'` 门控（对齐 QualityTab/RegressionTab 注释范式）；
      同步扩展 `listFilters.ts` 的 `ListTab` 联合类型与 `LIST_TABS` 数组补
      `'architecture'`（否则 TS 编译报错，且 URL `?tab=architecture` 会被
      listFilters.ts 的 `LIST_TABS.includes` 校验打回 `dev`）；`static/tests/listFilters.test.mjs`
      中 `assert.deepEqual([...LIST_TABS], …)` 精确断言（现第 22 行）须同步补
      `'architecture'`，漏改则既有测试直接红
- [x] 2.4 `core/dashboard/static` 下 `npm ci`（如 node_modules 缺失）后 `npm run build`
      通过，构建产物无报错（dist 为运行时产物，不入库）

## 3. 测试与文档

- [x] 3.1 新建 `tests/test_dashboard_architecture_api.py`：fake Popen 按 `cmd[0]`
      分发 + 布防门控（对齐测试隔离双陷阱先例），覆盖——受理异步落盘与 ready /
      在飞重复 POST 409 / 产物缺失自述完成判 failed / 组件数越界判 failed /
      skill 安装失败 error 带安装命令 / 超时进程组击杀 / 重启残留 generating 合成
      中断 / failed 后重试覆盖旧错误
- [x] 3.2 跑通新用例与既有 dashboard 路由测试家族（`tests/test_dashboard_*.py`）
      全绿；记录 pytest 退出码 0
- [x] 3.3 `docs/help/08-dashboard.md` 补「项目架构」页签小节：手动生成语义（不自动
      生成）、形态契约（8–16 组件/主路径/信任边界/说明卡片）、失败排查（含
      `npx skills add tt-a1i/archify -g` 手工安装命令与 daemon 重启提示）
