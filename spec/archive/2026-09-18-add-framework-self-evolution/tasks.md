## Deliverables

```yaml
- path: fenixd.py
  kind: modify
- path: core/evolution.py
  kind: new
- path: core/config.py
  kind: modify
- path: core/agent_runner/prompt_builder.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: agents/evolution.md
  kind: new
- path: core/dashboard/data.py
  kind: modify
- path: core/dashboard/server.py
  kind: modify
- path: core/dashboard/static/src/pages/settings/index.tsx
  kind: modify
- path: core/dashboard/static/src/pages/settings/components/SuggestedImprovementsPanel.tsx
  kind: new
- path: core/dashboard/static/src/pages/settings/components/StaleCodeSelfhealPanel.tsx
  kind: modify
- path: core/dashboard/static/src/pages/settings/components/selfEvolutionSection.ts
  kind: new
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: tests/test_self_evolution.py
  kind: new
- path: tests/test_dashboard_evolution_api.py
  kind: new
- path: docs/help/03-lifecycle.md
  kind: modify
- path: docs/help/08-dashboard.md
  kind: modify
- path: docs/help/09-config.md
  kind: modify
- path: docs/help/10-artifacts.md
  kind: modify
- path: core/dashboard/static/dist/index.html
  kind: reference
- path: ~/.fenix/config.yaml
  kind: reference
```

## 1. `self_evolution` 配置读取

- [x] 1.1 `core/config.py`：新增 `ConfigLoader.get_self_evolution_config(config) -> dict`，返回 `{"auto_accept": bool, "max_items_per_run": int}`；`self_evolution` 节或键缺失 → 缺省 `False` / `20`；`auto_accept` 非布尔（含 `1`/`"yes"`）、`max_items_per_run` 非整数 / `bool` 混入 / `< 1` / `> 200` → 对应键回退缺省值，MUST NOT 抛异常、MUST NOT 使 daemon 启动失败。缺省常量与上界 `200` 须以模块级常量暴露，便于测试与文档引用。
- [x] 1.2 `core/config.py`：把 `self_evolution` 纳入配置段护栏（键存在但类型非法时按 1.1 回退，不进入 `_validate` 的硬失败路径——与 `stale_code_selfheal` 的处理方式一致），确保 30s 热更新路径（`resolve_config_into`）不会因该节被中断。
- [x] 1.3 `tests/test_self_evolution.py`：覆盖 1.1 的缺省、非法回退（字符串 / 0 / 负数 / 非数字 / 201 / 布尔混入）与不抛异常三项。

## 2. 自进化存储层与水位

- [x] 2.1 `core/evolution.py`（新建）：实现条目身份键 `item_id(project, date_section, section, title) = sha1(f"{project}\x1f{date_section}\x1f{section}\x1f{title}").hexdigest()[:12]`，纯函数、无 IO、与条目在文件中的顺序与行号无关。
- [x] 2.2 `core/evolution.py`：实现 `.fenix/evolution/items.jsonl` 的读写——每条一行 JSON；写路径 MUST 采用「读-改-写 + 文件锁（flock）+ tempfile + rename 原子替换」（与 `StateMachine.write_all` 同范式）；同一 `id` MUST 只保留一条记录（存在则更新字段而非追加行）；文件不存在时按空集合处理。
- [x] 2.3 `core/evolution.py`：实现 `.fenix/evolution/state.json` 的水位读写——per-project `{"last_analyzed_at": "<ISO8601 UTC>", "last_run_id": "<evo-...>"}`；读取时字段缺失/非法按「从未分析」处理。水位推进 MUST 仅在分析 run 成功落地后发生，且 MUST 使用本轮 run 启动时捕获的快照时刻（由调用方传入，MUST NOT 在落地时取 `now()`）。
- [x] 2.4 `core/evolution.py`：实现就绪扫描 `scan_ready_projects(registry_projects) -> list[ready]`——对每个项目读取 `<proj>/.fenix/self_review_state.json` 的 `last_run_at`，与该项目水位比较：`last_run_at` 不可解析或缺失 → 不就绪（记 DEBUG/INFO 日志，MUST NOT 产生 admin 告警）；`last_run_at` 不晚于水位 → 不就绪；`<proj>/.fenix/todo.md` 不存在或去空白后为空 → 不就绪；其余 → 就绪。registry 读取失败 MUST 抛给调用方（由检查点统一捕获），MUST NOT 在此静默吞掉。
- [x] 2.5 `core/evolution.py`：实现 todo.md 条目解析 `parse_todo_entries(text) -> list[entry]`——按 `## <YYYY-MM-DD>` 切日期节、`### 浪费|失误|可改进` 切小节、`- **<标题>**` 起一条并收集其后的 `  - 影响：…` / `  - 证据：…` / `  - 调查评估：…` / `  - 建议：…` 嵌套行（与 `core/self_review.py:_render_entry_lines` 的渲染格式对齐）；`- （当日无）` 占位与无法归类的行 MUST 跳过且不使解析失败；小节名不在三值枚举内的条目 MUST 跳过并记一次 WARNING。
- [x] 2.6 `core/evolution.py`：实现增量筛选 `select_pending_entries(entries, known_ids, limit) -> list[entry]`——过滤掉 `known_ids`（`items.jsonl` 全量 id 集合）中已存在的条目，再按 `limit`（`max_items_per_run`）截断；返回值 MUST 保持 todo.md 中的原始顺序。同一条目在同一批内 MUST NOT 重复（按 id 去重）。

## 3. 草稿落地、lint 校验与接受/拒绝

- [x] 3.1 `core/evolution.py`：实现草稿落盘 `materialize_draft(item) -> draft_dir | None`——在 `.fenix/evolution/drafts/<id>/` 写 `proposal.md`、`specs/<capability>/spec.md`、`design.md`、`tasks.md`、`.spec.yaml`（内容 `schema: spec-driven` + `created: <YYYY-MM-DD>` + `mode: full`）。`spec` 内容缺任一必备文档、`capability` 非法（`^[a-z0-9][a-z0-9-]*$`）或 `name` 非法（同正则）时 MUST 返回 `None` 并给出原因，MUST NOT 半写文件。
- [x] 3.2 `core/evolution.py`：实现同源 lint 预检 `lint_draft(draft_dir, project_root) -> list[violation]`——`sys.path` 指向 `.fenix/` 后调用 `core.deliverables.lint_declared(draft_dir, project_root)` 与 `lint_tasks_parseable(draft_dir, project_root)`，返回合并后的 violation 列表；MUST NOT 自实现第二套声明解析。
- [x] 3.3 `core/evolution.py`：实现「落地单条复核结果」`ingest_item(item) -> status`：`worth_spec` 为假 → 直接入库并置 `analyzed`（不建草稿目录）；为真 → 落盘（3.1）→ lint（3.2）→ 有 violation 或缺内容则**删除草稿目录**、置 `draft_failed`、把 violation 原文与 `spec` 内容摘要写入条目记录；通过则置 `pending`。写入 `items.jsonl` 的条目 MUST 保留 todo.md 原文四字段（`impact`/`evidence`/`analysis`/`suggestion`）。
- [x] 3.4 `core/evolution.py`：实现 SPEC 名生成与冲突消解 `resolve_spec_name(name, item_id, project_root, state_machine) -> str | None`——基名 `evo-<name>`；与 `spec/changes/<candidate>`、STATE.md 既有条目名、`spec/archive/*-<candidate>` 任一冲突时追加 `-<item_id 前 6 位>` 并重新校验全部三处；仍冲突返回 `None`（调用方置 `draft_failed` 并告警）。
- [x] 3.5 `core/evolution.py`：实现接受路径 `accept_item(item_id, decided_by) -> dict`——前置状态校验（仅 `pending` / `accept_failed` 可接受，其它状态幂等返回现状）；把暂存草稿复制到 `spec/changes/<resolved_name>/`；**仅** `git add spec/changes/<resolved_name>/` 后 `git commit -m "[fenix] spec: <name>"`（MUST NOT `git add -A` / `git add .`）；提交成功后 `state_machine.add_spec(name, {"status": "drafted", "priority": 5})`（MUST NOT 写 `start_after`）；注册成功后删除暂存草稿目录并把条目标 `accepted`（`decided_by=manual`）或 `auto_accepted`（`decided_by=auto`），记录 `spec_name` / `decided_at`。提交失败 MUST NOT 注册并把条目标 `accept_failed`、写 admin WARNING 告警；注册失败 MUST 保留草稿、置 `accept_failed`、写告警。任一失败分支 MUST NOT 留下「已提交未注册」与「已注册未提交」并存的状态。
- [x] 3.6 `core/evolution.py`：实现拒绝路径 `reject_item(item_id) -> dict`——仅 `pending` / `draft_failed` / `accept_failed` 可拒绝（`accepted` / `auto_accepted` / `rejected` 返回错误且不改动任何文件）；删除前 MUST 用 `Path.resolve()` 校验目标位于 `.fenix/evolution/drafts/<item_id>/` 之内（含符号链接解析后的越界判定），越界一律报错且不删除；删除成功后置 `rejected` 并记录 `decided_at`。
- [x] 3.7 `core/evolution.py`：实现自动接受 `auto_accept_pending(items) -> summary`——对给定的 `pending` 条目逐个调用 3.5（`decided_by="auto"`），逐条独立捕获异常（单条失败置 `accept_failed` 并写告警，不影响其余）；MUST NOT 触碰 `analyzed` / `draft_failed` 条目。
- [x] 3.8 `core/evolution.py`：实现契约产物解析 `read_contract(path) -> items | raise`——校验 JSON 可解析、含 `items` 数组、每条含 `project`/`date_section`/`title`/`verdict` 且 `section` ∈ {浪费, 失误, 可改进}；任一不满足 MUST 抛出让调用方判整轮失败（不产生任何条目）。解析成功后由调用方删除产物文件。

## 4. 分析 agent 角色与执行

- [x] 4.1 `agents/evolution.md`（新建）：分析 agent prompt 模板，须包含——角色定位（框架自我改进的复核者，不是实现者）；输入（就绪项目清单、各项目根、各自 todo.md 全文、待分析条目清单、产物路径 `{out_path}`）；强制约束（对每个待分析条目派**一个** Task 子代理；子代理只读核查，MUST NOT 创建 spec/changes 条目、MUST NOT 写 STATE.md、MUST NOT 修改任何文件；只读日志/源码/STATE/git 记录，MUST NOT 采信 todo.md 的「调查评估」；核实不了写「未核实」禁编造）；输出契约（`verdict` 三项 + `rationale` 引证据、`analysis_md`、`worth_spec` 为真时给出符合 fenix-new 流程的 `spec` 全套文本，其中 `name`/`capability` 为 kebab-case、`tasks_md` 两段结构齐全：首个 `## Deliverables` 段（fenced yaml，path 为具体文件、kind 取 new/modify/delete/reference 四值） + `## <编号>. <标题>` 分组任务行 `- [ ] <组号>.<序号>`——2026-09-14 事故补正：原表述只要求「含 `## Deliverables` 段」，子代理据此产出无编号分组的 tasks.md，7 条草稿全被判 lint 拦下，故格式契约已改为两段并加派发前/落盘前自检）；工具缺失降级说明（无 Task 工具族时同进程串行逐条并在产物标记 `degraded`）。
- [x] 4.2 `core/agent_runner/prompt_builder.py`：`AGENT_PROMPT_FILES` 增加 `"evolution": "evolution.md"`；新增 `_build_evolution_prompt(...)` 填充占位符（就绪项目清单与各自 todo.md 内容、待分析条目（含 id）、`out_path`、项目根），并在 `_build_prompt` 的分派处接入。
- [x] 4.3 `core/agent_runner/runner.py`：新增 `run_evolution(ready_projects, pending_entries) -> EvolutionResult`——模型链取 `agents.models.self-review` → 回退 `agents.models.administrator` → 既有 `_get_admin_model` 兜底（MUST NOT 引入新的 `agents.models.*` 配置键）；`run_id` 形如 `evo-<epoch>`；**不创建 worktree**，执行目录为主树 `PROJECT_ROOT`（与 `run_self_review` 同形态）；`max_turns` / 超时 / 预算 / 告警 / provider 熔断全部走既有 `_run_claude`；产物路径 `.fenix/evolution/out-<run_id>.json`；token 归账沿用 `_accumulate_self_review_tokens` 的既有类目；返回 dataclass 含 `run_id` / `success` / `items_ingested` / `drafts` / `accepted` / `degraded` / `error`。
- [x] 4.4 `core/agent_runner/runner.py`：`run_evolution` 读取产物后 MUST 删除 `out-<run_id>.json`（与自省 `self_review_out-*.json` 的处理一致）；产物缺失或解析失败 MUST 返回 `success=False` 并带原因，MUST NOT 抛异常穿透到调用方。
- [x] 4.5 `tests/test_self_evolution.py`：覆盖模型链解析（self-review 命中 / 回退 administrator / 两者皆无走兜底）与「不创建 worktree」（断言执行目录为主树、worktree 目录无新增）——可用替身注入，不实测真实 claude 进程。

## 5. daemon 触发检查点

- [x] 5.1 `fenixd.py`：新增自进化检查点（节拍复用 `admin.interval_minutes`，缺省 5 分钟，独立于 admin 巡检线程或复用其节拍均可），流程为——读取 registry 项目 → `scan_ready_projects` → 与在飞 `evo-` run 判定单飞 → 无在途则立刻以**队列中全部就绪项目**启动一次分析 run（同一 run 拿到多份 todo.md），有在途则保留队列到下一检查点。检查点 MUST NOT 因等待其他项目到齐而延迟。
- [x] 5.2 `fenixd.py`：新增宿主守卫——`Path(__file__).resolve().parent`（即 `FRAMEWORK_ROOT`）与 `PROJECT_ROOT.resolve()` 不一致时 MUST NOT 启动任何分析 run，且仅在首次判定时记一条 INFO/WARNING 日志（不刷屏）。
- [x] 5.3 `fenixd.py` / `core/evolution.py`：分析 run 成功落地后，若 `ConfigLoader.get_self_evolution_config(config)["auto_accept"]` 为真 → 调用 3.7 对本轮 `pending` 条目自动接受（`decided_by="auto"`）；为假 → 保持 `pending` 等待用户。
- [x] 5.4 `fenixd.py`：检查点整体 try/except 包裹（异常记 ERROR，MUST NOT 中断主循环）；分析 run 失败（非零退出 / 超时 / 产物缺失 / JSON 非法）MUST 写一条 WARNING 级 admin 告警（含 run_id 与原因）且该项目水位 MUST NOT 推进；每轮成功落地 MUST 记 INFO 日志（就绪项目、条目数、草稿数、接受数、失败数）。

## 6. Dashboard 后端

- [x] 6.1 `core/dashboard/data.py`：`read_config`（用户级视图）注入 `self_evolution` 缺省值并回显（缺省 `auto_accept: false` / `max_items_per_run: 20`，非法值经 `ConfigLoader.get_self_evolution_config` 回退后的生效值），受管键白名单同步加入该节的两键。
- [x] 6.2 `core/dashboard/data.py`：`write_config` 前置校验——`auto_accept` 非布尔、`max_items_per_run` 非 1..200 整数 → 400 且不写盘；**项目级作用域**提交含 `self_evolution` 的配置 → 400 与可读错误（提示该节为全局用户级键），项目级配置文件 MUST 未被写入该键。
- [x] 6.3 `core/dashboard/data.py`：`read_effective_config`（项目级视图）透出 `self_evolution` 的用户级生效值（供面板在项目级作用域下只读展示）。
- [x] 6.4 `core/dashboard/data.py`：新增建议改进项读取助手——读 `.fenix/evolution/items.jsonl` 生成摘要列表（`id` / `project` / `date_section` / `section` / `title` / 三项判定 / `status` / `has_draft`（草稿目录是否存在）/ `spec_name` / `created_at` / `decided_at`），按 `created_at` 倒序；文件缺失返回空列表；单行 JSON 损坏 MUST 跳过并记 WARNING（MUST NOT 让整个列表 500）。
- [x] 6.5 `core/dashboard/data.py`：新增分析结论与草稿文档读取助手——`item_id` 未知返回 `not_found`；`doc` 白名单 `{proposal, design, tasks, spec}`，非法返回 `invalid_doc`；草稿目录不存在返回 `found: false`；读取路径 MUST 由 `item_id` 推导（`.fenix/evolution/drafts/<id>/…`）并校验解析后仍在该目录内，MUST NOT 接受任意路径参数。
- [x] 6.6 `core/dashboard/server.py`：新增 5 个端点与路由分发（GET `/api/evolution/items`、GET `/api/evolution/analysis`、GET `/api/evolution/draft`、POST `/api/evolution/accept`、POST `/api/evolution/reject`），错误语义为——缺参/非法参数/非法 `doc` → 400，未知 `item_id` → 404，成功 → 200 并回传新状态（接受回传 `spec_name` 与 `status`）。
- [x] 6.7 `tests/test_dashboard_evolution_api.py`：覆盖 5 端点的正常与错误分支（列表字段完整性、倒序、未知 item 404、非法 doc 400、`found: false` 空态、路径参数被忽略）、配置读写（用户级往返、非法值 400、**项目级写 `self_evolution` 被 400 拒绝且未落盘**）。

## 7. Dashboard 前端

- [x] 7.1 `core/dashboard/static/src/pages/settings/index.tsx`：页签文案由「自愈」改为「自进化」（内部 key 同步改名，须保持默认选中态与既有页签不受影响），并在该页签下按序渲染既有 `StaleCodeSelfhealPanel` 与新增 `SuggestedImprovementsPanel`（面板接收 `scope` 与 `project`）；两张卡片经 `forwardRef` 暴露 `collect()` 收集句柄，页签内容最下方渲染**唯一**右对齐「保存」按钮（`data-testid="settings-save"`），点击后合并两节配置为一次 `POST /api/config`（校验失败则不发请求）。
- [x] 7.2 `core/dashboard/static/src/pages/settings/components/SuggestedImprovementsPanel.tsx`（新建）：标题「建议改进项」置于**卡片外**（`<h3>` + 功能注解，与第一张卡片同构），配置卡片内为「允许框架自改进」开关（`self_evolution.auto_accept`，开关行——控件在前、名称同行不换行 + 键名注解 + 功能注解）+「每轮分析条目上限」数字输入（1..200，缺省 20，**独占一行**，输入框后缀单位「条」+ 功能注解）；卡片内 MUST NOT 自带保存按钮（保存经页签底部唯一按钮，且 MUST NOT 带 `project` 参数）；用户级作用域可写，项目级作用域两项置只读并显示「全局键，请在用户级作用域修改」且 `collect()` 不返回 `self_evolution`；错误时展示后端文案且不改本地值；面板根元素提供稳定 `data-testid`。
- [x] 7.3 同上文件：表格（列序：项目 / 日期 / 类别 / 问题 / 评估结论 / 状态 / 操作）——评估结论列汇总三项判定、状态列按 `pending|analyzed|draft_failed|accepted|auto_accepted|rejected|accept_failed` 映射中文文案（待决策 / 不需要立项 / 草稿生成失败 / 已同意 / 已自动接受 / 已拒绝 / 接受失败）、空态文案、接口失败展示可读错误；移动端横向滚动 + 操作列固定右侧（不做卡片式降级）。
- [x] 7.4 同上文件：操作列使用与 SPEC 列表页「更多」一致的形态（antd `Dropdown` + `MoreOutlined` + `Button type="link" size="small"`），菜单四项依次为「查看分析结论 / 查看 SPEC 草稿 / 同意 / 拒绝（danger）」；禁用规则——`analyzed` 与 `draft_failed` 禁用「查看 SPEC 草稿」与「同意」（`analyzed` 另禁用「拒绝」），`accepted`/`auto_accepted`/`rejected` 禁用「同意」与「拒绝」；「同意」「拒绝」MUST 经二次确认弹窗后才发请求。
- [x] 7.5 同上文件：查看类交互——「查看分析结论」在 Drawer/Modal 中渲染 `analysis_md`（含加载态、404 可读错误、空态）；「查看 SPEC 草稿」可切换 `proposal` / `design` / `tasks` / `spec` 四类文档，`found: false` 显示空态；接受/拒绝成功后刷新表格并提示（接受提示含新 SPEC 名），失败时展示错误并刷新回真实状态。
- [x] 7.6 `core/dashboard/static/src/services/dashboard.ts`：新增 `SelfEvolutionConfig` 类型、`ConfigData.self_evolution`、建议改进项摘要/分析/草稿/接受/拒绝的请求封装与类型。
- [x] 7.7 `core/dashboard/static/`：执行 `npm run build` 重建 `dist/`，确认产物可被既有静态服务加载、页面无构建告警阻断。

## 8. 文档

- [x] 8.1 `docs/help/09-config.md`：新增 `self_evolution` 节说明（两键、缺省值、上界 200、用户级全局键与项目级写入被拒），并更新文末「页签 → 配置键」对照表（「自愈」改为「自进化」，加入 `self_evolution` 两键）。
- [x] 8.2 `docs/help/08-dashboard.md`：更新设置页说明——「自进化」页签、「代码陈旧自愈」为第一张卡片、「建议改进项」卡片（全局开关、表格、操作列四项与其语义）。
- [x] 8.3 `docs/help/10-artifacts.md`：新增 `.fenix/evolution/` 产物说明（`items.jsonl` 条目状态机、`state.json` 水位语义、`drafts/<id>/` 暂存草稿、`out-<run_id>.json` 契约产物），并注明已接受条目的草稿会被移出暂存区交给 `spec/changes/`。
- [x] 8.4 `docs/help/03-lifecycle.md`：说明框架自动生成的改进 SPEC 统一使用 `evo-*` 前缀，进入流水线的位置与人工 `/fenix-new` 生成的 SPEC 完全相同（`drafted` → 自动晋升 → 实现 → 验证 → `pushed`，推送审批门不变）。

## 9. 回归与端到端

- [x] 9.1 `tests/test_self_evolution.py`：覆盖身份键稳定性与四元组敏感性、`items.jsonl` 同 id 更新不追加、水位「仅在 run 启动快照时刻推进」、已入库条目不被重复选中、`max_items_per_run` 截断后未处理条目下轮仍可选、todo.md 解析（三节 + 四字段 + 占位跳过 + 未知小节跳过）。
- [x] 9.2 `tests/test_self_evolution.py`：覆盖就绪扫描五分支（状态文件缺失 / `last_run_at` 非法 / 不晚于水位 / todo.md 缺失或空白 / 就绪）、非自托管宿主不启用、分析 run 失败（替身返回失败）时水位不推进且写 WARNING 告警、检查点内部抛异常时主循环不中断。
- [x] 9.3 `tests/test_self_evolution.py`：覆盖接受/拒绝路径——`draft_failed`（lint violation / 缺文档 / 非法 name）时草稿目录被删除且不落 `spec/changes/`；接受成功落地提交与注册（用临时 git 仓库 + 临时 STATE）、重名加后缀、提交失败不注册且可重试、重复接受幂等、拒绝越界路径（符号链接）不被删除、已接受条目不可拒绝。
- [x] 9.4 `tests/test_self_evolution.py`：覆盖自动接受——开关为真时全部 `pending` 被接受且 `decided_by=auto`、单条失败不影响其余、`analyzed` 与 `draft_failed` 不受影响、开关为假时保持 `pending`。
- [x] 9.5 全量回归：`python3 -m pytest tests/ -q` 全绿（重点确认 `tests/test_stale_code_selfheal.py`、`tests/test_daily_self_review.py`、`tests/test_dashboard_todo_api.py`、`tests/test_system_settings_config.py` 不受影响），并在主树重建 dashboard 产物。

## 验证修复（原地打回第 1 轮）

- [x] 先复核失败有效性：逐条核对 `spec/changes/add-framework-self-evolution/verification-report.md` 中失败场景的期望断言（状态字面量/选择器/前置数据）与产品实际行为是否相符——断言与产品不符属场景缺陷，修场景文件；确属产品行为不符才修产品代码
- [x] 按复核结论修复：场景缺陷改场景文件，真实产品 Bug 改产品代码
- [x] 修复后重跑验证确认通过

## 布局修订（用户反馈，2026-09-13）

- [x] 10.1 `SuggestedImprovementsPanel.tsx`：卡片标题「建议改进项」提到卡片**外**（`<h3>` + 功能注解，与「代码陈旧自愈」同构）；「允许框架自改进」改为同行开关行（`.switch-inline-row`，开关在前、名称不换行）+ 功能注解；「每轮分析条目上限」改为**独占一行** + 输入框后缀单位「条」+ 功能注解。
- [x] 10.2 新增 `selfEvolutionSection.ts`（`SelfEvolutionSectionHandle` 收集句柄类型）：两张卡片改为 `forwardRef` 暴露 `collect()`——校验并收集本节配置，校验失败返回 `null`，项目级只读卡片返回空补丁；移除各自卡片内的保存按钮（含 `data-testid="stale-code-selfheal-save-btn"`）。
- [x] 10.3 `settings/index.tsx`：页签内容最下方渲染唯一右对齐「保存」按钮（`data-testid="settings-save"`），`handleSelfEvolutionSave` 合并两节配置为**一次** `POST /api/config`（`stale_code_selfheal` + 用户级作用域下的 `self_evolution`；任一卡片校验失败即中止）。
- [x] 10.4 重跑 `npm run build` 并 playwright 实测：用户级/项目级两作用域布局与卡片外标题、开关行不换行、「条」单位、全页唯一保存按钮；用户级保存为单次 `POST /api/config`（200）并回显，项目级两项只读且载荷不含 `self_evolution`。
