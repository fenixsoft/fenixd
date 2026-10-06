## Deliverables

```yaml
- path: core/hook_engine.py
  kind: modify
- path: core/dashboard/static/src/pages/settings/components/HooksPanel.tsx
  kind: modify
- path: tests/test_hook_engine.py
  kind: modify
- path: core/dashboard/static/tests/hooksPanel.test.mjs
  kind: new
- path: core/dashboard/static/dist/index.html
  kind: reference
```

## 1. 内置条目注入与动作健壮化（后端）

- [x] 1.1 `hook_config()` 注入内置默认条目 `builtin-push-restart-dashboard`（`events: [pushed]`、`action: restart-dashboard`、global 作用域头部）：配置键 `hooks.push_restart_dashboard` 为 `false` 时不注入；用户 global 列表已有同 id 条目时用户条目优先（不重复注入）
- [x] 1.2 `_action_restart_dashboard` 加 60s 去抖（进程内 monotonic 时间戳）：窗口内且上次成功 → 跳过 respawn 并记 skipped 审计；重启失败不写时间戳（窗口内可重试）；tmux 会话不存在 → 静默跳过（skipped 语义 + debug 日志，不产 failure 审计）；会话存在但 respawn 失败仍记 failure。**返回通道约定**：动作现返回 `Tuple[bool, str]`、`_execute_action` 的 restart-dashboard 分支二元解包映射 success/failure（`hook_engine.py:656-658`）——须扩展为可表达三态（success/failure/skipped），解包与审计映射同步适配；MUST NOT 以 `(True, "skipped: ...")` 形式把 skipped 冒充 success 审计
- [x] 1.3 `tests/test_hook_engine.py` 新增用例：pushed 事件匹配到内置条目（global 作用域）、`push_restart_dashboard: false` 不注入、用户同 id 条目不重复注入、任意其它状态事件（done/error 等）不触发、去抖窗口内第二次触发 skipped、失败后窗口内重试、无会话静默跳过无 failure 记录（mock subprocess/tmux）

## 2. 逃生键设置页控件（前端）

- [x] 2.1 `HooksPanel.tsx` 增加 `hooks.push_restart_dashboard` 开关（checkbox，缺省 true，文案说明「SPEC push 后自动重启 dashboard 以加载最新代码」），经既有配置读写链路持久化
- [x] 2.2 新建 `core/dashboard/static/tests/hooksPanel.test.mjs`：开关渲染缺省态、切换触发配置写回调用、false 时不注入语义由后端用例覆盖（前端只测控件与写回参数）

## 3. 构建与回归

- [x] 3.1 前端构建产物重建落位 `core/dashboard/static/dist/`（reference）
- [x] 3.2 后端测试通过：`python3 -m pytest tests/test_hook_engine.py tests/test_dashboard_hooks_api.py -x -q`
- [x] 3.3 前端测试通过：`core/dashboard/static/tests/` 全量绿
- [x] 3.4 端到端冒烟：本地 dashboard 运行中，用一个测试 SPEC 状态迁移至 pushed（或直接调用 HookEngine.dispatch），观察 dashboard 进程重启（ps 启动时间更新）且端口恢复可服务；60s 内第二次 dispatch 确认 skipped
