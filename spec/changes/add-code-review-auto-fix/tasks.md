# Tasks: add-code-review-auto-fix

## Deliverables

```yaml
- path: core/code_fix.py
  kind: new
- path: agents/code-fix.md
  kind: new
- path: core/agent_runner/prompt_builder.py
  kind: modify
- path: core/agent_runner/run_files.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: core/agent_runner/maintenance_runs.py
  kind: modify
- path: core/config.py
  kind: modify
- path: core/regression.py
  kind: modify
- path: core/code_review.py
  kind: modify
- path: core/event_bus.py
  kind: modify
- path: fenixd.py
  kind: modify
- path: core/dashboard/data/config_admin.py
  kind: modify
- path: core/dashboard/data/code_review.py
  kind: modify
- path: core/dashboard/routes/code_review_routes.py
  kind: modify
- path: core/dashboard/routes/base.py
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: core/dashboard/static/src/pages/settings/components/QualityPanel.tsx
  kind: modify
- path: core/dashboard/static/src/pages/projects/components/QualityTab.tsx
  kind: modify
- path: .fenix/config.template.yaml
  kind: modify
- path: docs/help/09-config.md
  kind: modify
- path: tests/test_code_fix.py
  kind: new
- path: core/dashboard/static/dist/index.html
  kind: reference
```

> 说明：`core/dashboard/static/dist/`（前端构建产物，被 `.gitignore` 的 `dist/` 排除）
> 不入库，由框架在合并后自动重建，属 `reference` 非交付物；本变更只需保证
> `npm run build` 通过。`.fenix/config.yaml`、`.fenix/code-review/fix-progress.json`
> 均为 gitignored 运行时文件，不进声明段。

## 1. 配置层（`admin.code_review_fix.*`）

- [ ] 1.1 在 `core/config.py` 的 `KNOWN_AGENT_TYPES` 追加 `"code-fix"`（附注释：不登记会被 `_hash_gate` 静默跳过 `agents.models.code-fix` 并回退默认网关）
- [ ] 1.2 在 `core/config.py` 新增 `ConfigLoader.get_code_review_fix_config(config)`：读取 `admin.code_review_fix` 段，`enabled` 缺省 False 且严格 bool（非 bool 回退 False）、`batch_size` 缺省 20 且必须为正整数（bool / ≤0 / 非整数回退 20）；段非 dict 视为缺省；docstring 说明缺省语义与「关闭=全链路零动作」
- [ ] 1.3 在 `core/config.py` 的 `_validate_agent_models` 路径确认 `code-fix` 可配（无需另改，仅验证 1.1 生效：`agents.models.code-fix` 不再被拒）；新增 `tests/test_code_fix.py` 断言 `get_code_review_fix_config` 的缺省/非法值回退矩阵与 `code-fix` 在 `KNOWN_AGENT_TYPES` 中

## 2. code-fix agent 注册与提示词

- [ ] 2.1 在 `core/agent_runner/prompt_builder.py` 的 `AGENT_PROMPT_FILES` 追加 `"code-fix": "code-fix.md"`
- [ ] 2.2 在 `core/agent_runner/run_files.py` 的 `RUN_ID_AGENT_PREFIXES` 追加 `("code-fix-", "code-fix")`（位置与 `code-review-` 相邻并附注释）
- [ ] 2.3 新建 `agents/code-fix.md`：修复者角色提示词，含——身份（可改码，仅处理注入清单条目，MUST NOT 顺手重构清单外代码）；输入占位符 `{items}`（本批条目 JSON：`item_id`/`file`/`line`/`severity`/`category`/`title`/`description`/`suggestion`）、`{out_path}`（绝对路径增量产物）、`{worktree}`；输出契约（每处置完一条向 `{out_path}` 追加一行 `{item_id, status, file}`，`status ∈ {fixed, skipped}`）；提交契约（修改提交到当前 worktree 分支，MUST NOT 执行 merge-back、MUST NOT 改 `.fenix/` 下运行时文件或 `items.jsonl`）；失败/无法修复的条目 MUST 写 `status: skipped` 而非静默跳过；MUST NOT 触碰清单外文件
- [ ] 2.4 在 `core/agent_runner/prompt_builder.py` 新增 `_build_code_fix_prompt(spec_name, detail)` 并接入 `_build_prompt` 的 `agent_type == "code-fix"` 分支（形态对齐 `_build_code_review_prompt`）；`{out_path}` 缺省回退 `.fenix/code-review/fix-out-<run_id>.jsonl`
- [ ] 2.5 在 `tests/test_code_fix.py` 覆盖：`infer_run_agent_type("code-fix-123")` 返回 `("code-fix","123")` 且 `code-review-123` 不错配；`_build_prompt` 对 `code-fix` 正确填充 `{items}`/`{out_path}`；`agents/code-fix.md` 存在且 `AGENT_PROMPT_FILES` 含映射

## 3. 回归锁根参数（`core/regression.py`）

- [ ] 3.1 在 `core/regression.py` 的 `run_regression(project_root, spec, logger=None)` 新增可选参数 `lock_root=None`：非 None 时 `_SuiteLock` 的锁根取 `lock_root`（锁文件 `lock_root/.fenix/full-suite.lock`），而 `cwd` 与 `output_abs` 仍取 `project_root`；缺省回落 `project_root`（既有调用点零迁移）；docstring 说明用途（worktree 内回归与主树共用主机级锁）
- [ ] 3.2 在 `core/agent_runner/maintenance_runs.py` 的 `run_regression` 门面透传 `lock_root`（可选参数，缺省 None），并在 `core/regression.run_and_write_regression` 同步透传
- [ ] 3.3 在 `tests/test_regression_execution.py` 或 `tests/test_code_fix.py` 覆盖：`lock_root` 缺省时锁路径与改动前一致；`lock_root=<main>` 时锁路径为 `<main>/.fenix/full-suite.lock` 而命令 cwd 仍为传入的 project_root

## 4. 台账核销原语（`core/code_review.py`）

- [ ] 4.1 在 `core/code_review.py` 新增 `mark_resolved(project_root, item_ids: list[str]) -> int`：把指定 `item_id` 的条目置 `status="resolved"`（形态对齐既有 `_mark_in_spec`：读-改-写走 `_with_lock` + `_atomic_write`，只动命中条目，返回命中数；缺 `item_id` 静默跳过）；docstring 说明其与 `set_item_status`（仅人工 open/ignored）的分工与「只能由合回成功驱动」的约束
- [ ] 4.2 在 `tests/test_code_fix.py` 覆盖 `mark_resolved`：命中多条置 resolved、不误伤未命中条目、空列表安全、并发写不丢条目（复用既有台账并发测试形态）

## 5. 自动修复编排核心（`core/code_fix.py`）

- [ ] 5.1 新建 `core/code_fix.py`：定义进度路径常量（`.fenix/code-review/fix-progress.json`）与 `read_progress(project_root)`（缺失/损坏返回缺省态 `{running:false, phase:"idle", total:0, done:0, current:"", batch_no:0, reason:""}`，不抛异常）与 `write_progress(project_root, **fields)`（原子写）
- [ ] 5.2 在 `core/code_fix.py` 实现 `select_batch(project_root, batch_size) -> list[dict]`：读台账 `open` 条目、按 `first_seen_at` 升序（缺失回退 `item_id`）稳定排序取前 `batch_size` 条；排除已在「失败保留集合」（见 5.7）中的条目
- [ ] 5.3 在 `core/code_fix.py` 实现 `CodeFixOrchestrator` 类：构造注入 `agent_runner`、`project_root`、`config`、`logger`、可选 `executor`；持有单飞锁 `_in_flight` + `threading.Lock`；`checkpoint() -> dict` 实现守卫链（`enabled` → `already_running`（`_in_flight` 或 `_running_agents` 含 `code-fix-` 前缀）→ `no_open_items` → 回归契约 → 投递），返回 `{triggered, reason}` 供测试断言
- [ ] 5.4 在 `core/code_fix.py` 实现批 worker：选批 → 记录本批 `item_ids` → 建 worktree（经 `agent_runner.worktree_manager`）→ 调 `agent_runner.run_code_fix(...)` → 跑全量回归（经 `agent_runner.run_regression(spec, lock_root=<main>)`）→ 回归通过则 `merge_back` + `mark_resolved` + 进度 `done += 批条数` → 未通过走重试（5.6）→ 收尾复位单飞并经 executor 再次投递 `checkpoint()` 推进下一批
- [ ] 5.5 在 `core/code_fix.py` 实现回归契约守卫：经 `load_verify_contract(project_root)` 判定 `regression` 段；缺失/无效时经 `AdminStore.append` 写 `verify_contract_missing` 信号（payload 对齐既有 `_write_verify_contract_missing`：含 `signal_type`/`spec`/`severity:"major"`/`description`/`evidence`/`recommended_action`），进度置 `phase="blocked"`、`reason="regression_contract_missing"`，**不派批、不合回**（fail-closed），返回 `{"triggered": False, "reason": "regression_contract_missing"}`
- [ ] 5.6 在 `core/code_fix.py` 实现回归失败重试：首次回归 `status != "passed"` → 在同一 worktree 内再派一次 `run_code_fix`（prompt 追加失败用例摘要）→ 第二次回归 `passed` 则正常合回；仍非 `passed` → 丢弃该批（不合回、不置 resolved、条目保持 open），进度 `phase="failed"` 附原因，保留 worktree 并写失败告警（见 5.7）
- [ ] 5.7 在 `core/code_fix.py` 实现失败批保留集合：把「两次回归均失败」的批 `item_ids` 与 worktree 路径落盘到 `.fenix/code-review/fix-failed.json`（原子写）；`select_batch` 读取该文件跳过其 `item_ids`（防重复派发同一批）；文件不存在/损坏时视为空集（不阻塞）；提供 `release_failed_batch(project_root, item_ids)` 供人工清理后解除（本变更只提供函数 + 文档说明，不接 UI）
- [ ] 5.8 在 `tests/test_code_fix.py` 覆盖编排核心：守卫矩阵（disabled / already_running / no_open_items / regression_contract_missing / 正常投递）、`select_batch` 排序与排除失败集合、进度读写与缺省态、`mark_resolved` 接线（用 fake runner / 临时目录，MUST NOT 真跑 agent）

## 6. code-fix 执行函数（`core/agent_runner/maintenance_runs.py` + `runner.py`）

- [ ] 6.1 在 `core/agent_runner/maintenance_runs.py` 新增 `run_code_fix(runner, worktree_root, items, run_id=None) -> CodeFixResult`：落盘 items 注入数据 → 经 `runner._build_prompt(run_id, "code-fix", detail={items, out_path, worktree})` 构建 prompt → 模型链解析（`agents.models.code-fix` → `code-review` → `self-review` → `administrator` → `_get_admin_model`，注入 env 形态对齐 `run_code_review`）→ `runner._run_claude(..., spec_name="code-review-fix", agent_type="code-fix")`（cwd 为 `worktree_root`）→ 读取 out 文件
- [ ] 6.2 在 `core/agent_runner/maintenance_runs.py` 新增 `_unique_code_fix_run_id(runner)`（`code-fix-<epoch>`，撞名追加 `-<n>`）与产物硬门 `_check_code_fix_artifact(items, out_path)`（注入清单非空而 out 文件缺失或零有效行 → 判失败，对齐 `_check_repo_code_review_artifact` 形态），返回 `CodeFixResult(run_id, success, fixed, skipped, error, output)`
- [ ] 6.3 在 `core/agent_runner/maintenance_runs.py` 定义 `CodeFixResult` 数据类（字段：`run_id`、`success`、`fixed`、`skipped`、`error`、`output`）
- [ ] 6.4 在 `core/agent_runner/runner.py` 的门面转发表（`run_code_review`/`run_regression` 同处）注册 `"run_code_fix": run_code_fix`，并确认 `code-fix` 不在 `_execute_agent` 路径（不占 spec 维度预算）
- [ ] 6.5 在 `tests/test_code_fix.py` 覆盖：产物硬门（out 缺失/零有效行 → `success=False`）、out 解析（fixed/skipped 计数）、run_id 撞名退避、模型链回退顺序（mock `_get_agent_model_assignment` 返回 `code-review` 级，断言 env 注入与 code-review 一致）

## 7. 激活接线（审查收尾 + full scan）

- [ ] 7.1 在 `core/agent_runner/maintenance_runs.py` 的 `run_code_review` 收尾路径：成功落账且本轮 `inserted > 0` 时，经 `getattr(runner, "_code_fix_orchestrator", None)` 触发一次 `checkpoint()`（包在 try/except 内，异常记 WARNING 不使审查 run 失败）
- [ ] 7.2 在 `core/event_bus.py` 的 `_run_full_scan_body()` 末尾（`check_blockers` 之后）经可选的 `getattr(self, "code_fix_orchestrator", None)` 调用 `checkpoint()`，异常记 WARNING 不阻断扫描（形态对齐既有可选组件调用）
- [ ] 7.3 在 `fenixd.py` 装配 `CodeFixOrchestrator`（在 admin_monitor/executor 就绪后），注入 `self.agent_runner._code_fix_orchestrator` 与 `self.event_bus.code_fix_orchestrator`；executor 复用 `self._admin_executor`（对齐 `_code_review_executor` 注入形态）；宿主禁用态（`admin_monitor is None`）时构造仍成功、`checkpoint()` 返回 `disabled`
- [ ] 7.4 在 `tests/test_code_fix.py` 覆盖激活接线：审查收尾在 `inserted>0` 且开关开启时调用 checkpoint（用 fake runner 记录调用）；full_scan 在编排器未装配时不抛异常；两路并发到同一 checkpoint 时至多一次投递

## 8. 进度 API（后端读侧）

- [ ] 8.1 在 `core/dashboard/data/code_review.py` 新增 `read_code_review_fix_progress(project_root)`（转导 `core.code_fix.read_progress`，缺省态兜底），并在 `core/dashboard/data/__init__.py` 导出
- [ ] 8.2 在 `core/dashboard/routes/code_review_routes.py` 的 `H11CodeReviewRoutesMixin` 新增 `_api_code_review_fix_progress(self, query)`：`GET /api/code-review/fix-progress?project=<name>`，项目不存在 → 404，否则 `self._json(dashboard_data.read_code_review_fix_progress(...))`（形态对齐 `_api_code_review_progress`）
- [ ] 8.3 在 `core/dashboard/routes/base.py` 的 GET 路由表注册 `("exact", "/api/code-review/fix-progress", _get_code_review_fix_progress)` 与其 handler（形态对齐既有 `code-review/progress` 注册处）
- [ ] 8.4 在 `tests/test_code_fix.py` 或 `tests/test_dashboard_regression_api.py` 覆盖：端点返回结构、未知项目 404、无进度文件返回缺省态不 500

## 9. Dashboard 前端

- [ ] 9.1 在 `core/dashboard/static/src/services/dashboard.ts` 新增 `CodeReviewFixConfig { enabled?: boolean; batch_size?: number }`、`ConfigData.code_review_fix?: CodeReviewFixConfig`、`CodeReviewFixProgress` 类型与 `getCodeReviewFixProgress(project)` 函数（形态对齐既有 `getCodeReviewProgress`）
- [ ] 9.2 在 `core/dashboard/static/src/pages/settings/components/QualityPanel.tsx`：在「周期性代码审查」卡片**下方**新增「自动修复代码问题」卡片——`code_review_fix_enabled` Switch（`data-testid="code-review-fix-enabled-switch"`）+ `code_review_fix_batch_size` InputNumber（1–1000）；回填 `config.code_review_fix?.enabled === true` / `?.batch_size ?? 20`；`handleSave` 序列化 `code_review_fix: { enabled, batch_size }`；控件 MUST 落在**同一个** `<Form>` 实例内（防脱管致恒提交缺省）
- [ ] 9.3 在 `core/dashboard/static/src/pages/projects/components/QualityTab.tsx`：新增自动修复进度读取（`getCodeReviewFixProgress`，运行中 2s 轮询，`blocked`/`failed`/`running=false` 停止）与呈现——「已处理 {done}/{total} 条」+ `Progress percent={total? round(done/total*100):0}` + 当前阶段/`current`/`reason` 文案；与既有「审查进行中」卡片并存，MUST NOT 覆盖既有审查进度、问题表格与按钮
- [ ] 9.4 执行 `cd core/dashboard/static && npm run build` 确保前端构建通过（dist 为 `reference` 产物，不入库）

## 10. 配置 UI 与文档

- [ ] 10.1 在 `core/dashboard/data/config_admin.py` 逐条接入 `admin.code_review_fix` 受管键：`_SOURCE_KEYS` 新增、`_DEFAULT_CODE_REVIEW_FIX = {"enabled": False, "batch_size": 20}` 并在 `read_config` 缺省段回显、`read_config`/`read_effective_config` 经 `ConfigLoader.get_code_review_fix_config` 回显、`_deep_merge_managed` 合并、`write_config` 前置校验（`enabled` 严格 bool、`batch_size` 正整数，非法 fail 不落盘）、`_SYNC_PAGE_KEYS` 的 `quality` 页签含该段
- [ ] 10.2 在 `.fenix/config.template.yaml` 新增 `admin.code_review_fix` 段示例（`enabled: false` / `batch_size: 20`，形态对齐同文件既有 `admin.code_review`），并在 `agents.models` 白名单处补 `code-fix` 示例
- [ ] 10.3 在 `docs/help/09-config.md` 新增 `admin.code_review_fix` 专节（`enabled` / `batch_size` 语义、缺省、fail-closed 与 AI 起草复用说明），并在「Dashboard 设置页与配置键映射」表补 `admin.code_review_fix.enabled` / `admin.code_review_fix.batch_size` 两行
- [ ] 10.4 在 `tests/test_code_fix.py` 覆盖配置读写：缺省回显、`sources` 标注 `project`、写入 `enabled`/`batch_size` 后回显、非法 `batch_size` 拒绝落盘且不半写、`_SYNC_PAGE_KEYS` 含该段

## 11. 端到端装配预演

- [ ] 11.1 冒烟预演：全新 Python 进程 `import` `core.code_fix` / `core.config` / `core.dashboard.data.code_review` / `core.dashboard.routes.code_review_routes`，构造 `CodeFixOrchestrator`（fake runner + 临时项目根），断言 `checkpoint()` 在 `enabled=false` 时返回 `disabled`、在缺 `regression` 段时返回 `regression_contract_missing` 并落 `blocked` 进度——无需真实 daemon/agent
- [ ] 11.2 运行 `python3 -m pytest tests/test_code_fix.py tests/test_regression_execution.py tests/test_code_review.py -q` 全绿（本变更新增/改动的相关测试）
