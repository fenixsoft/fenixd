## Deliverables

```yaml
- path: core/hook_engine.py
  kind: new
- path: core/event_bus.py
  kind: modify
- path: core/dashboard/server.py
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: core/dashboard/static/src/pages/projects/detail.tsx
  kind: modify
- path: core/dashboard/static/src/pages/settings/index.tsx
  kind: modify
- path: core/dashboard/static/src/pages/settings/components/HooksPanel.tsx
  kind: new
- path: core/dashboard/static/src/components/HookManager.tsx
  kind: new
# core/dashboard/static/dist/index.html 为前端构建产物（.gitignore dist/ 排除、
# 不入 git，由框架重建），声明为 reference 仅审计留痕，不参与守卫缺件硬校验。
# admin 裁决 2026-09-06：原 modify 声明在任何实现分支不可满足，系守卫自伤（admin_disposition-admin-add-spec-hooks-1788685533）。
- path: core/dashboard/static/dist/index.html
  kind: reference
- path: tests/test_hook_engine.py
  kind: new
- path: tests/test_dashboard_hooks_api.py
  kind: new
- path: .fenix/config.yaml
  kind: reference
```

## 1. HookEngine 核心模块（core/hook_engine.py）

- [x] 1.1 新建 `core/hook_engine.py`：hook 配置读取与校验（`hooks.global` 列表 + `hooks.specs.<name>` 列表；events 非空且在十状态枚举内、action 七枚举、webhook 必填 url、shell 必填 command）
- [x] 1.2 事件匹配：`(spec, event_type)` → 命中的全局 hooks + 该 spec 的 spec 级 hooks，`enabled=false` 记 skipped（写审计、不告警、不执行）
- [x] 1.3 审计写入：`.fenix/hook_audit.jsonl` 带锁追加（字段 ts/spec/event/from_status/to_status/hook_id/action/scope/status/detail≤2KB/duration_ms），导出审计尾部读取纯函数（按 spec 过滤 + limit 倒序）
- [x] 1.4 异步执行骨架：每命中 hook 一个 daemon 线程并发执行，单 hook 异常互不影响，不阻塞调用方
- [x] 1.5 失败处理：动作失败写 status=failure 审计 + `admin_store.append()` 产生 `hook_failure` 站内告警（severity major，含 spec/事件/动作/错误摘要），不重试

## 2. 七种消费动作

- [x] 2.1 `restart-daemon`：touch `<project_root>/.fenix/restart_request`，创建成功即成功
- [x] 2.2 `commit`：`git add -A` + `git commit -m <模板渲染>`（模板变量 {spec}/{event}，缺省 `[fenix] hook: {spec} {event}`，未知变量原样保留）；无变更 → noop 成功；git 失败 → 失败
- [x] 2.3 `push` / `commit-push`：`git push`（跟随 upstream）；commit-push 先 commit 后 push，commit noop 时仍 push，push 失败不回滚本地提交
- [x] 2.4 `restart-dashboard`：`tmux respawn-window -k -t <target>`（target 缺省 fenix-dashboard，可配）执行固化启动命令，命令含 `env -u CLAUDE_PID` 且保持 8787 端口与原工作目录；重启后探测端口恢复 HTTP 可服务（超时 → 失败告警）
- [x] 2.5 `webhook`：POST JSON（event/spec/from_status/to_status/ts/error/frozen/hook_id/action/project 字段，Content-Type: application/json，timeout_seconds 缺省 10），2xx 成功，响应体截断 2KB 记审计
- [x] 2.6 `shell`：`bash -c <command>`，cwd=项目根，注入 FENIX_HOOK_EVENT/FENIX_HOOK_SPEC/FENIX_HOOK_FROM_STATUS/FENIX_HOOK_TO_STATUS/FENIX_HOOK_ERROR/FENIX_HOOK_PROJECT_ROOT，timeout_seconds 缺省 60 超时强杀，退出码 0 成功，stdout+stderr 尾部 ≤2KB 入审计

## 3. EventBus 集成与 daemon 装配

- [x] 3.1 `core/event_bus.py`：构造参数新增可选 `hook_dispatcher`；`_dispatch_changes` 状态 diff 处对每条 `old_status != new_status` 调用分发（传 spec/old/new/entry），未注入时行为不变；启动快照语义保持（重启不重发存量）
- [x] 3.2 daemon 装配：daemon 启动时实例化 HookEngine 并作为 hook_dispatcher 注入 EventBus；执行时实时从 config 对象读 hooks 段（享受 30s 热更新）

## 4. Dashboard API（core/dashboard/server.py）

- [x] 4.1 `GET /api/hooks/audit?spec=<name>&limit=20`：读 `.fenix/hook_audit.jsonl` 尾部，按 spec 过滤、时间倒序、limit 截断；文件不存在返回空列表
- [x] 4.2 `POST /api/config` hooks 段校验并入现有受管配置通道：events 非空且合法、action 合法、webhook 必填 url、shell 必填 command，违规 400 且不写入

## 5. 前端（v3）

- [x] 5.1 API client（`services/dashboard.ts`）：新增 hook 审计查询与 hooks 配置读写封装
- [x] 5.2 共享组件 `components/HookManager.tsx`：hook 列表（含来源列「全局/本 spec」、启停开关）+ 新增/编辑/删除表单（事件多选、动作下拉、按动作类型显隐参数：url/command/message/timeout_seconds/target）+ 最近执行记录列表（时间/动作/结果/耗时/摘要）
- [x] 5.3 spec 详情页（`pages/projects/detail.tsx`）：「失败截图」页签之后新增「Hook」页签——生效中的 Hooks（全局+spec 级合并、来源标注）、本 spec 的 Hooks（spec 级 CRUD，写入 hooks.specs.<name>）、最近执行（该 spec 审计）
- [x] 5.4 设置页（`pages/settings/index.tsx` + 新组件 `settings/components/HooksPanel.tsx`）：新增「Hook」菜单项与面板——全局 hooks CRUD（写入 hooks.global）+ 跨 spec 最近执行记录
- [x] 5.5 前端构建产物重建（dist 由框架重建，不提交 dist 源码变更）

## 6. 测试与验证

- [x] 6.1 `tests/test_hook_engine.py`：匹配矩阵（全局/spec 级/多消费者/enabled=false skip）、七动作核心行为（commit noop、push 到本地 bare 远端、webhook 对本地 HTTP 端点、shell env 注入与超时、restart-daemon 请求文件）、审计记录字段、失败告警产生
- [x] 6.2 `tests/test_dashboard_hooks_api.py`：GET /api/hooks/audit 过滤/倒序/limit/空文件；POST /api/config hooks 校验 400 用例
- [x] 6.3 EventBus 集成测试：状态 diff 触发分发、未注入 dispatcher 行为不变、跨进程写入（直接改 STATE.md）被捕获
- [x] 6.4 全链自验：worktree 实例配置全局+spec 级 hook → 伪造状态变化 → 审计与告警按 spec 场景断言；全部既有测试无回归
