# Tasks: add-code-review-agent-and-quality-tab

## Deliverables

```yaml
- path: core/code_review.py
  kind: new
- path: core/config.py
  kind: modify
- path: core/dashboard/data/config_admin.py
  kind: modify
- path: core/agent_runner/prompt_builder.py
  kind: modify
- path: core/agent_runner/run_files.py
  kind: modify
- path: core/agent_runner/maintenance_runs.py
  kind: modify
- path: agents/code-review.md
  kind: new
- path: fenixd.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: core/dashboard/data/code_review.py
  kind: new
- path: core/dashboard/routes/code_review_routes.py
  kind: new
- path: core/dashboard/routes/base.py
  kind: modify
- path: core/dashboard/static/src/pages/projects/list.tsx
  kind: modify
- path: core/dashboard/static/src/pages/projects/components/QualityTab.tsx
  kind: new
- path: core/dashboard/static/src/pages/settings/components/AgentModelPanel.tsx
  kind: modify
- path: core/dashboard/static/src/pages/settings/components/PromptsPanel.tsx
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: .fenix/config.template.yaml
  kind: modify
- path: docs/help/09-config.md
  kind: modify
- path: docs/help/02-concepts.md
  kind: modify
- path: tests/test_code_review.py
  kind: new
- path: core/dashboard/static/dist/index.html
  kind: reference
```

> 说明：`core/dashboard/static/dist/`（前端构建产物，被 `.gitignore` 的 `dist/` 排除）
> 不入库，由框架在合并后自动重建，属 `reference` 非交付物；本变更只需保证
> `npm run build` 通过。`.fenix/config.yaml` 与 `.fenix/code-review/items.jsonl`
> 均为 gitignored 运行时文件，不进声明段（`.fenix/config.yaml` 的默认键由
> 模板 + `core/config.py` 缺省值提供）。

## 1. 台账核心（`core/code_review.py`）

- [x] 1.1 新建 `core/code_review.py`，定义台账路径常量与读写：`code_review_dir(project_root)` = `<proot>/.fenix/code-review/`，`items_path` = 其下 `items.jsonl`，`read_items()` / `write_items()` 逐行 JSON 读写，缺文件返回空 dict（对齐 `.fenix/evolution/items.jsonl` 的 `read_items`/`write_items` 形态）。**并发写 MUST 复用 evolution 的 flock + 原子替换形态**（`_with_lock` + `_atomic_write`，见 `core/evolution.py:134` 与 `upsert_item`）：本台账同时被 daemon（run 收尾 ingest、全仓核销）与 dashboard（generate-spec 置 `in_spec`、items/status 置 `ignored`、清除归属）两侧写入，无锁的「读-改-写」会整批丢条目（evolution 的 design「daemon 与 Dashboard 同时写同一存储」即为此先例）
- [x] 1.2 实现 `fingerprint(file, category, title) -> str`：`sha1(f"{file}|{category}|{normalize_title(title)}")[:12]`；`normalize_title` 去首尾空白、折叠内部连续空白为单空格、统一小写——保证同一问题跨轮稳定（`code-review-items` 指纹去重场景）
- [x] 1.3 实现 `upsert_findings(project_root, findings, review_id, review_kind, spec_map) -> dict`：按 fingerprint 去重——已存在则仅刷新 `last_seen_at`/`severity`/`description`/`suggestion`（MUST NOT 覆盖 `status`/`spec_name`/`first_seen_at`），不存在则插入新条目（`status=open`，`first_seen_at=last_seen_at=now`）；`item_id` 稳定（取 fingerprint 派生或 `sha1(project|file|fingerprint)[:12]`）。返回 `{"inserted": n, "updated": n}`
- [x] 1.4 实现 `resolve_snapshot(project_root, observed_fingerprints, now)`：**由调用方保证仅在 `review_kind == "manual_full"` 时调用**（本函数不做 review_kind 判定，签名内不携带该参数——核销职责在 `run_code_review` 收尾分支，见 3.1）。核销语义：台账中 `status == "open"` 且 fingerprint 不在 `observed_fingerprints` 中的条目置 `resolved`（记录 `resolved_at`）；MUST NOT 触碰 `in_spec`/`ignored`（`code-review-items` 全仓快照核销场景）
- [x] 1.5 实现 `set_item_status(project_root, item_id, status, spec_name=None)`：幂等流转 `open`/`ignored` 为**人工可置状态**（`resolved` 由全仓核销置入，`in_spec` 由生成链路置入，二者 MUST NOT 经本函数人工置入）；从 `in_spec` 重置回 `open` 时 MUST 同时清空 `spec_name`。未知 `item_id` 返回错误不抛异常
- [x] 1.6 实现 `compute_window(project_root, now) -> (window_start, window_kind)`：读 `.fenix/self_review_state.json` 的 `last_run_at` 作 `window_start`，缺字段回退 `now - 24h`——与 `core/self_review.py` 的窗口计算同源口径（MUST NOT 另立周期逻辑）
- [x] 1.7 实现 `collect_manifest(project_root, scope, window_start) -> list[str]`：`scope="window"` 收集 `window_start` 之后合并/产出的 SPEC 所变更文件（用 `git log --since` + `git show --name-only` 或 STATE 内 SPEC 分支合并记录推导）；`scope="full"` 收集全仓受控源码文件（排除 `spec/`、`docs/`、`dist/`、`.fenix/` 等非代码路径）；MANIFEST 为空时 MUST NOT 返回"全绿"语义，返回空列表并由调用方明确置 `no_files`
- [x] 1.8 实现 `read_progress(project_root) -> dict`：扫描 `.fenix/code-review/out-*.jsonl` 与运行态，返回 `{running, review_id, review_kind, total, done, current}`；`done` = 对应 run 的 out jsonl 行数，`total` = 派发时落盘的 `.fenix/code-review/manifest-<review_id>.json` 长度，`current` = 最后一行落盘的文件名。**`running` 判定口径（MUST 明确，防「已完成 run 永远显示在跑」类误判）**：取最新一个 run（按 `<review_id>` 内嵌 epoch 排序），仅当该 run 的 `.fenix/runs/<review_id>.jsonl` **末行非终态**（无 `result`/`error`/`cancelled` 终态行）且产物 mtime 未超既有 stale 阈值时 `running=true`；已有终态行或超时即 `running=false`（对齐 `core/dashboard/data/runs.py` 的 `_classify_run`/`_RUN_STALE_SECONDS` 同款口径，MUST NOT 另立一套存活判定）。**终态集合 MUST 取 `_RUN_TERMINAL_STATUS_MAP` 的全量四类**（`result`/`error`/`interrupted`/`cancelled`，`core/dashboard/data/runs.py:121-127`）——取消路径落的终态行是 `cancelled`、daemon 停机补写是 `interrupted`，只认 `result`/`error` 会让「已取消/已停机的 run」永远停在 `running=true`，进度条与取消按钮永不收起，且 4.2/5.4 的 409 守卫因「已有运行中」恒真而拒绝后续全部触发。平台无运行/无 manifest 时返回 `running=false` 且其余字段为 null/0
- [x] 1.9 实现 `generate_fix_spec(project_root, state_machine, item_ids) -> dict`：见分组 6，函数签名与状态流转在此声明

## 2. code-review agent 类型注册与提示词

- [x] 2.1 `core/agent_runner/prompt_builder.py`：`AGENT_PROMPT_FILES` 增 `"code-review": "code-review.md"`（附带注释行说明来源变更）
- [x] 2.2 `core/agent_runner/run_files.py`：`RUN_ID_AGENT_PREFIXES` 增 `("code-review-", "code-review")`（注意顺序——放在无子串冲突的位置；`code-review-` 不与既有前缀互为子串）
- [x] 2.3 `core/config.py`：`KNOWN_AGENT_TYPES` 增 `"code-review"`（附注释说明不纳入会被静默跳过并回退网关）
- [x] 2.4 `core/config.py`：新增 `get_code_review_config(cls, config) -> dict`（读 `admin.code_review.*`），返回 `{"enabled": bool, "max_files": int}`，`enabled` 缺省 False，`max_files` 缺省正整数（全仓审查 manifest 上限，非法回退缺省）
- [x] 2.5 新建 `agents/code-review.md`：定义 code-review agent 的职责——输入含 manifest 文件清单与审查窗口；逐文件审查代码质量（正确性/健壮性/安全/可维护性/一致性），输出结构化 findings（`file/line/severity/category/title/description/suggestion/evidence`）；**MUST 每审完一个文件立即向 `out-<run_id>.jsonl` 追加一行**；MAY 调用 `ocr` 辅助，缺失降级继续；MUST NOT 修改任何业务代码（只读审查）
- [x] 2.6 `core/agent_runner/prompt_builder.py`：新增 code-review prompt 构建分支（注入 manifest 清单、窗口、输出 jsonl 路径、ocr 可用性提示），登记进 prompt 分发；模型解析（chain 回退 `code-review` → `self-review` → `administrator`）
- [x] 2.7 `core/dashboard/static/src/pages/settings/components/PromptsPanel.tsx`：`AGENT_LABELS` 增 `'code-review': 'Code-Review（代码审查）'`——该对象的 key 集合与后端 `AGENT_PROMPT_FILES` 严格一致（`tests/test_agent_prompt_files.py:684` 双向比对），漏改即红
- [x] 2.8 `core/dashboard/static/src/pages/settings/components/AgentModelPanel.tsx`：`AGENT_ROLES` 增 `{ key: 'code-review', label: 'Code-Review（代码审查）' }`——该数组 key 集合与 `ConfigLoader.KNOWN_AGENT_TYPES` 严格一致（`tests/test_agent_prompt_files.py:705` 双向比对），漏改即红

## 3. 调度检查点与 run 实现

- [x] 3.1 `core/agent_runner/maintenance_runs.py`：新增 `run_code_review(...)`——生成 `run_id = f"code-review-{int(time.time())}"`；落盘 manifest 到 `.fenix/code-review/manifest-<run_id>.json`；构建 prompt 调 runner（main 树执行，同 `run_self_review` 形态）；run 结束读 `.fenix/code-review/out-<run_id>.jsonl` 并调 `upsert_findings` 入台账；`manual_full` 再调 `resolve_snapshot` 核销
- [x] 3.2 `core/admin_monitor.py`：新增 `_run_code_review_checkpoint()`——守卫与自省同源（`enabled`、同自然日防重、`run_at` 未到不跑）；读取窗口与 scope（周期=scheduled/window 语义），收集 manifest，manifest 为空则记录并跳过（不派发空 run）；单飞（已有 code-review run 在跑则跳过）
  - **线程模型（MUST）**：检查点本身只做判定与投递，**派发经 `_admin_executor` 投递后台 worker 执行完整 run**（对齐 `fenixd._evolution_worker` 形态），**MUST NOT 在巡检线程内同步跑完整审查**——自省 checkpoint 是在 `_admin_monitor_loop` 线程内同步执行的（`core/admin_monitor.py:766`），整轮审查（数十文件 LLM 调用）若照搬会让 admin 巡检停摆整个审查时长，`admin.interval_minutes` 级巡检与信号检测全部被阻塞。单飞标记在**投递即置位、worker 收尾复位**（对齐 `_evolution_in_flight` ← `fenixd.py:189/1329/1371`）
  - **`admin.code_review.enabled` 的落点补充**：周期派发由本检查点读该键守卫；手动触发（3.4）**不受该开关约束**（用户显式点击即执行），与 `admin.self_review` 的「开关只管周期调度」语义一致
  - **防重状态 MUST 独立**：本检查点 MUST 用自己的状态记录（如 `.fenix/code_review_state.json` 的 `last_run_date`）判「同自然日防重」，**MUST NOT 读 `self_review_state.json` 的 `last_run_date`**——后者会被同轮 `run_once` 内的自省检查点写入为今天，复用它会让 code-review 判定「今日已跑」而**永不派发**（静默空转，且日志只留 `already_ran_today`）
- [x] 3.3 `core/admin_monitor.py`：在 `run_once()` 内调用 `_run_code_review_checkpoint()`。**调用位置 MUST 在 `_run_self_review_checkpoint()` 之前（不得照抄 design D3 的「之后」）**：`SelfReviewScheduler._save_state` 会在自省收尾把 `.fenix/self_review_state.json` 的 `last_run_at` 覆写为「此刻」（`core/self_review.py:1121-1133`，成功/失败/零活动跳过三条路径都写），而本变更的 `window_start` 正是读该字段（1.6）。若先跑自省再跑本检查点，窗口退化为 `[now, now]`、manifest 恒为空，周期审查**每天都以 `no_files` 空转**，能力整体失效。先跑本检查点则读到的是上一次自省时刻，窗口 `[上次自省, now]` 正是设计意图。两 checkpoint 仍互不阻塞（各自 try/except 隔离）
- [x] 3.4 `fenixd.py`：登记手动触发信号 `.fenix/code_review_request.json` 的消费（`{scope: "full"|"window", requested_at}`）——主循环读取→删除→派发 `run_code_review`（`scope` 映射 `review_kind`：full→manual_full、window→manual_window）；已有运行中则忽略并记录。**投递同样走后台 worker**（同 3.2 线程模型，MUST NOT 在 1s 主循环内同步跑完整 run——`_check_admin_invoke_requests` 的「拾取后本扫描周期内继续后续工作」注释即此教训，`fenixd.py:1018-1022`）
- [x] 3.5 取消：确认 `code-review-*` run 的 run_id 能被既有 `cancel_run` / `.fenix/cancel_run_request.json` 机制正确归一化匹配（若 `_normalize_run_id` 对 `code-review-` 前缀无碍则无需改动；如需则补齐并说明）；取消后**部分 out jsonl 保留**（不清理）。**实现要点**：取消依赖 `AgentRunner._running_agents` 注册表的前缀匹配（`runner.py:610` `aid.startswith(base_id)`）与 `code-review-` 前缀在 `RUN_ID_AGENT_PREFIXES` 的登记（2.2）——两处齐备则前端以 `progress.review_id` 原样调 `cancelRun` 即可，**不需要** `cancel_run` 侧新增分支
- [x] 3.6 token 归账：`run_code_review` 收尾把 `usage_info` 追加到 `.fenix/cost/code_review_tokens.json`（形态对齐 `_accumulate_self_review_tokens`，`maintenance_runs.py:478`）——**MUST NOT 走 `_accumulate_token_usage`**（该路径按 spec_name 写 STATE 内部字段，而审查 run 无 spec 维度、且 `core/self_review.py` 的「MUST NOT 注册 STATE 条目」硬约束同型适用）。缺此条则该车道的 token 消耗在 cost-observability 中完全不可见
- [x] 3.7 run_id 唯一性与并发：`code-review-<epoch>` 秒级时间戳在「手动触发 + 同秒周期触发」或「秒级内重复点击」下可能撞名（`run_code_review` 落盘 `manifest-<run_id>.json` 与 `out-<run_id>.jsonl` 会被互相覆盖）；单飞守卫已挡住绝大多数并发，实现时仍 MUST 在撞名（目标文件已存在）时追加 `-<n>` 或退避重取 epoch，并保证**同一 review 的 manifest 与 out 文件名同源**
- [x] 3.8 审查 run 的活动通道（不新增代码，但 MUST 逐项确认口径，避免被既有治理机制误判）：审查 run 在 **main 树根**执行（`cwd = project_root`），且 `append_run_line` 首行即写含 `cwd` 的 `system` 事件（`core/agent_runner/run_files.py:53`）——与 `run_self_review` 同构，故 `run_spec_part("code-review-1789...")` 剥前缀后得 `1789...`（非项目名），`core/admin_monitor.py:547 _has_recent_spec_run` 与 `_spec_from_run_id`（`core/admin_monitor.py:2976`，前缀取自真源 `RUN_ID_AGENT_PREFIXES`）对本前缀天然返回不匹配；`core/agent_runner/liveness.py:340 has_live_attempt` 只 glob `impl-<spec>-*` / `verify-<spec>-*`，亦不匹配。实现时 MUST 验证三点仍成立（`code-review-` 前缀加入 `RUN_ID_AGENT_PREFIXES` 后，各治理判定对本 run 均判「非本 spec 活动」，即不把审查 run 误算作任何 SPEC 的驱动证据，也不误报 stuck），并据此在 3.3 的单飞守卫之外不再额外加锁

## 4. Dashboard 后端（读取器 + 路由）

- [x] 4.1 新建 `core/dashboard/data/code_review.py`：`read_code_review_items(project_root, statuses=None)` 读台账并按状态过滤（默认仅 `open`），按 severity 排序；`read_code_review_progress(project_root)` 转导 `core.code_review.read_progress`
- [x] 4.2 新建 `core/dashboard/routes/code_review_routes.py`：`GET /api/code-review/items`（query `project`、可选 `status`）、`GET /api/code-review/progress`（query `project`）、`POST /api/code-review/run`（body `{project, scope}`；已有运行中返回 409）、`POST /api/code-review/generate-spec`（body `{project, item_ids}`）、`POST /api/code-review/items/status`（body `{project, item_id, status}`）
- [x] 4.3 `core/dashboard/routes/base.py`：在 `_API_GET_ROUTES` 注册两个 GET（`/api/code-review/items`、`/api/code-review/progress`），在 `_API_POST_ROUTES` 注册三个 POST（`/api/code-review/run`、`/api/code-review/generate-spec`、`/api/code-review/items/status`）——均为 `exact` 路由
- [x] 4.4 `POST /api/code-review/run` 实现：写 `.fenix/code_review_request.json` 信号（不直接同步跑审查），运行中返回 409 `{"error": "已有审查在进行中"}`。**信号写入 MUST 带消费方守卫**：`code_review_request.json` 与会话/审批推送属同一类「dashboard 原子写 → daemon 主循环消费」文件信号，daemon 未运行或未受 supervisor 托管（`core.fenix_session.hosting_state(proot) == "unmanaged"`）时**无人消费**，信号会永久滞留并在 daemon 下次启动时被消费成一次用户并未请求的审查——既有先例 `request_spec_approve_push`（`core/dashboard/data/admin_actions.py:736-751`，注释「信号无人消费会静默滞留，比明确报错更糟」）即此判据，项目页对 `unmanaged` 项目的「审批推送」正是被它拒绝。本端点 MUST 对齐该判据（`unmanaged` → 400/409 + 明确文案，不写文件），前端 MUST 把该拒绝原样提示而非静默失败
- [x] 4.5 `POST /api/code-review/generate-spec` 实现：调 `core.code_review.generate_fix_spec`，返回 `{ok, spec_name, skipped, error}`；成功把条目置 `in_spec`

## 5. 前端「质量」分面

- [x] 5.1 `core/dashboard/static/src/services/dashboard.ts`：新增 5 个服务函数（`getCodeReviewItems` / `getCodeReviewProgress` / `triggerCodeReview` / `generateFixSpec` / `setCodeReviewItemStatus`），对齐既有 `request<T>` 封装与端点
- [x] 5.2 新建 `core/dashboard/static/src/pages/projects/components/QualityTab.tsx`：props `{ project: string; active: boolean }`；`active` 为真时才拉取与订阅（对齐 `SessionPanel` 的 active 门控，未选中零请求）
- [x] 5.3 `QualityTab` 表格：`Table` + `rowSelection`（`selectedRowKeys` 状态），列含 严重度/文件:行/问题标题/所属 SPEC/状态，支持严重度与状态过滤排序；默认仅 `open`；随 `EventSource('/api/stream')` 增量刷新 + 心跳兜底
- [x] 5.4 `QualityTab` 右上角两个按钮「全仓库审查」「立即审查本周期」——分别调 `triggerCodeReview(project, 'full'|'window')`；409 时提示「已有审查在进行中」；成功后进入运行中态
- [x] 5.5 `QualityTab` 运行中态：轮询 `GET /api/code-review/progress` 渲染真实百分比进度条（`done/total`）+ 当前文件文案 + 取消按钮；取消调既有 `cancelRun(project, runId)`（run_id 由 progress 的 `review_id` 提供）；无运行时不渲染进度区；运行结束收起并刷新表格
- [x] 5.6 `QualityTab` 底部「生成修复 SPEC」按钮（选中 > 0 才可用）：调 `generateFixSpec(project, selectedRowKeys)`，成功提示 SPEC 名并从 open 列表移除已 `in_spec` 条目
- [x] 5.7 `QualityTab` 开关区：`admin.code_review.enabled` 的开关（读 `GET /api/config`、写 `POST /api/config`），与两个触发按钮同区（design D7）
- [x] 5.7a `core/dashboard/data/config_admin.py`（后端写路径 + 回显路径，**缺任一则 5.7 的开关是死键**）：
  (a) 读路径 `read_config`：`admin` 段回显新增 `code_review` 子键（`{enabled, max_files}`，经 `ConfigLoader.get_code_review_config` 归一化缺省填充）——前端 `GET /api/config` 的 `admin.code_review` 由此而来，不回显则开关恒读不到值；
  (b) 写路径 `write_config` 前置校验：`config_patch["admin"]["code_review"]` 的 `enabled` 非严格 bool、`max_files` 非正整数 → `fail(...)` 拒绝落盘（对齐 `admin.self_review` 的校验模式）；
  (c) merge 层 `_deep_merge_managed`：**必须**新增 `admin.code_review` 合并分支——该函数的 admin 分支是**逐键白名单**，未登记的键在 merge 阶段被静默丢弃（`admin.self_review` 即为此单列分支的先例）
- [x] 5.8 `core/dashboard/static/src/pages/projects/list.tsx`：`quality` 分面 children 由 `Empty` 空态替换为 `<QualityTab project={name} active={activeTab === 'quality'} />`
- [x] 5.9 运行 `cd core/dashboard/static && npm run build` 通过（构建产物 `dist/` 不入库，由框架重建）
- [x] 5.10 `QualityTab` 行操作两个入口：(a)「忽略」——对 open 条目调 `setCodeReviewItemStatus(project, item_id, 'ignored')`，成功后从 open 列表移除并提示；(b)「清除归属」——仅对 `in_spec` 条目可见，调 `setCodeReviewItemStatus(project, item_id, 'open')` 重置回默认列表。两入口是 `POST /api/code-review/items/status`（4.2）、`setCodeReviewItemStatus`（5.1）与 `set_item_status`（1.5）三处实现的**唯一消费方**，也是 `code-review-items` spec「忽略问题」场景与质量分面「`ignored` 默认隐藏 / `in_spec` 可撤回」两条要求（`specs/code-review-quality-tab/spec.md`）得以验收的前端落点；缺此条则三个实现无任何调用路径，对应 spec 场景不可验收
- [x] 5.11 `GET /api/config` 侧无需新增回显通道：项目页开关走 `read_effective_config`（`core/dashboard/routes/settings_routes.py:37`），其实现取自 `_managed_admin_keys(effective)`（`core/dashboard/data/config_admin.py:644`）——即 5.7a(a) 的「读路径」**只改这一处**即可；但 **5.7a 与 5.11 须同步处理两条既有硬断言**（否则必红）：(i) `tests/test_system_settings_config.py:40-52` 逐字断言 `echoed["admin"] == {...7 键...}`，新增 `code_review` 子键后须同步更新该断言；(ii) `tests/test_system_settings_config.py:105-113` 断言 `set(echoed["admin"].keys())` 恰为 7 键且 `self_review` 不在其中——`code_review` 子键的落点 MUST 与 `self_review` **一致**（同为 `admin` 段的独立子段、不进 `_managed_admin_keys` 的键集），即 `_managed_admin_keys` 既有的「不透传未知 admin 子段」约定 MUST 对新子键延续；**MUST NOT 把 `code_review` 摊平进 `_managed_admin_keys` 的键集或 `_ADMIN_DEFAULTS`**（那会同时打破 (i) 与 (ii) 两条断言并让 `admin.code_review` 与 `admin.self_review` 两条子段的回显形态分叉）

## 6. 生成修复 SPEC（复用 evolution 链路）

- [x] 6.1 `core/code_review.py` 实现 `generate_fix_spec(project_root, state_machine, item_ids) -> dict`：筛出 `status == "open"` 的选中条目（其余进 `skipped`），缺关键字段（`file`）的进 `skipped` 不整批失败；无有效条目返回错误
- [x] 6.2 生成草稿内容：`proposal.md`（Why/What/Capabilities/Impact）、`design.md`、`specs/<capability>/spec.md`、`tasks.md`——`tasks.md` MUST 含 `## Deliverables` 声明段（每条目 `file` 作为 `modify`）并内联各条目 `title` 与 `file:line`；`.spec.yaml`（`schema: spec-driven` + `created` + `mode: full`）
- [x] 6.3 复用同源 lint：`sys.path` 指向 `<proot>/.fenix` 后调 `core.deliverables.lint_declared` / `lint_tasks_parseable`（MUST NOT 自实现第二套）；有 violation 则删除草稿、返回错误、条目状态不变（不半写）
- [x] 6.4 命名消解：基名 `fix-cr-<slug>`（slug 由首个条目 category/短标题推导，满足 kebab-case）；冲突则追加 `-<fingerprint[:6]>` 重试；判重覆盖 `spec/changes/<cand>`、STATE 既有条目名、`spec/archive/*-<cand>` 三处；仍冲突返回错误不覆盖
- [x] 6.5 落地与注册：复制草稿到 `spec/changes/<name>` → 仅 `git add spec/changes/<name>` 并 `git commit -m "[fenix] spec: <name>"` → `state_machine.add_spec(name, {"status": "drafted", "priority": 5})`（不写 `start_after`，立即进入调度）；成功后把参与条目置 `in_spec` 并写 `spec_name`
- [x] 6.6 幂等：同批 `item_ids` 重复提交且已成功时，MUST 返回既有 `spec_name`（通过条目已 `in_spec` + `spec_name` 判定，不重复生成）

## 7. 配置、文档与测试

- [x] 7.1 `.fenix/config.template.yaml`：新增 `agents.models.code-review` 模型分配示例与 `admin.code_review`（`enabled: false`、`max_files`）段，附注释
- [x] 7.2 `docs/help/09-config.md`：文档化 `admin.code_review.enabled` / `max_files` 与 `agents.models.code-review`（含缺省值、语义、与 `self_review` 周期同源的说明）
- [x] 7.2a `docs/help/02-concepts.md`：「十类 Agent 角色」表增 `code-review` 行（职责：周期性仓库级代码审查；触发时机：每日自省时点同步触发 / 分面手动触发），并**修正标题与正文计数**（现为十类，add-spec-review-gate 即以此先例同步该表，见 `spec/archive/2026-09-19-add-spec-review-gate/tasks.md` 任务 6.2）
- [x] 7.3 `tests/test_code_review.py`：覆盖 指纹稳定性（大小写/空白归一）、去重 upsert（同 fingerprint 不增条目、只更新 last_seen_at）、快照核销（manual_full 核销、window 不核销、不动 in_spec/ignored）、窗口计算（有/无 last_run_at）、命名消解（基名/冲突后缀/仍冲突报错）、lint 不通过不半写、生成幂等、`skipped` 语义
- [x] 7.4 `tests/test_code_review.py`：覆盖 agent 类型四处注册一致性（`AGENT_PROMPT_FILES`、`RUN_ID_AGENT_PREFIXES`、`KNOWN_AGENT_TYPES`、`agents/code-review.md` 存在），以及 `infer_run_agent_type("code-review-...")` 返回 `("code-review", ...)`
- [x] 7.5 `tests/test_code_review.py`：覆盖 `get_code_review_config`（缺省 enabled=False、非法 max_files 回退缺省），以及开关关闭时 checkpoint 零动作（不派发、不写产物）
- [x] 7.6 `tests/test_code_review.py`：覆盖 `admin.code_review` 的 Dashboard 读写链路——`write_config({"admin": {"code_review": {...}}})` 落盘后 `read_config` 回显该子键（验证 merge 分支未被静默丢弃）、非法 `enabled`/`max_files` 被前置校验拒绝（对齐 `tests/test_system_settings_config.py` 既有 admin 校验用例形态）
