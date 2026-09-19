# Tasks: add-code-review-agent-and-quality-tab

## Deliverables

```yaml
- path: core/code_review.py
  kind: new
- path: core/config.py
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
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: .fenix/config.template.yaml
  kind: modify
- path: docs/help/09-config.md
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

- [ ] 1.1 新建 `core/code_review.py`，定义台账路径常量与读写：`code_review_dir(project_root)` = `<proot>/.fenix/code-review/`，`items_path` = 其下 `items.jsonl`，`read_items()` / `write_items()` 逐行 JSON 读写，缺文件返回空 dict（对齐 `.fenix/evolution/items.jsonl` 的 `read_items`/`write_items` 形态）
- [ ] 1.2 实现 `fingerprint(file, category, title) -> str`：`sha1(f"{file}|{category}|{normalize_title(title)}")[:12]`；`normalize_title` 去首尾空白、折叠内部连续空白为单空格、统一小写——保证同一问题跨轮稳定（`code-review-items` 指纹去重场景）
- [ ] 1.3 实现 `upsert_findings(project_root, findings, review_id, review_kind, spec_map) -> dict`：按 fingerprint 去重——已存在则仅刷新 `last_seen_at`/`severity`/`description`/`suggestion`（MUST NOT 覆盖 `status`/`spec_name`/`first_seen_at`），不存在则插入新条目（`status=open`，`first_seen_at=last_seen_at=now`）；`item_id` 稳定（取 fingerprint 派生或 `sha1(project|file|fingerprint)[:12]`）。返回 `{"inserted": n, "updated": n}`
- [ ] 1.4 实现 `resolve_snapshot(project_root, observed_fingerprints, now)`：仅在 `review_kind == "manual_full"` 时执行核销——台账中 `status == "open"` 且 fingerprint 不在 `observed_fingerprints` 中的条目置 `resolved`（记录 `resolved_at`）；MUST NOT 触碰 `in_spec`/`ignored`（`code-review-items` 全仓快照核销场景）
- [ ] 1.5 实现 `set_item_status(project_root, item_id, status, spec_name=None)`：幂等流转 `open/ignored`（`in_spec`/`resolved` 由系统置入），未知 `item_id` 返回错误不抛异常
- [ ] 1.6 实现 `compute_window(project_root, now) -> (window_start, window_kind)`：读 `.fenix/self_review_state.json` 的 `last_run_at` 作 `window_start`，缺字段回退 `now - 24h`——与 `core/self_review.py` 的窗口计算同源口径（MUST NOT 另立周期逻辑）
- [ ] 1.7 实现 `collect_manifest(project_root, scope, window_start) -> list[str]`：`scope="window"` 收集 `window_start` 之后合并/产出的 SPEC 所变更文件（用 `git log --since` + `git show --name-only` 或 STATE 内 SPEC 分支合并记录推导）；`scope="full"` 收集全仓受控源码文件（排除 `spec/`、`docs/`、`dist/`、`.fenix/` 等非代码路径）；MANIFEST 为空时 MUST NOT 返回"全绿"语义，返回空列表并由调用方明确置 `no_files`
- [ ] 1.8 实现 `read_progress(project_root) -> dict`：扫描 `.fenix/code-review/out-*.jsonl` 与运行态，返回 `{running, review_id, review_kind, total, done, current}`；`done` = 对应 run 的 out jsonl 行数，`total` = 派发时落盘的 manifest 长度（`.fenix/code-review/manifest-<review_id>.json`），`current` = 最后一行落盘的文件名
- [ ] 1.9 实现 `generate_fix_spec(project_root, state_machine, item_ids) -> dict`：见分组 6，函数签名与状态流转在此声明

## 2. code-review agent 类型注册与提示词

- [ ] 2.1 `core/agent_runner/prompt_builder.py`：`AGENT_PROMPT_FILES` 增 `"code-review": "code-review.md"`（附带注释行说明来源变更）
- [ ] 2.2 `core/agent_runner/run_files.py`：`RUN_ID_AGENT_PREFIXES` 增 `("code-review-", "code-review")`（注意顺序——放在无子串冲突的位置；`code-review-` 不与既有前缀互为子串）
- [ ] 2.3 `core/config.py`：`KNOWN_AGENT_TYPES` 增 `"code-review"`（附注释说明不纳入会被静默跳过并回退网关）
- [ ] 2.4 `core/config.py`：新增 `get_code_review_config(cls, config) -> dict`（读 `admin.code_review.*`），返回 `{"enabled": bool, "max_files": int}`，`enabled` 缺省 False，`max_files` 缺省正整数（全仓审查 manifest 上限，非法回退缺省）
- [ ] 2.5 新建 `agents/code-review.md`：定义 code-review agent 的职责——输入含 manifest 文件清单与审查窗口；逐文件审查代码质量（正确性/健壮性/安全/可维护性/一致性），输出结构化 findings（`file/line/severity/category/title/description/suggestion/evidence`）；**MUST 每审完一个文件立即向 `out-<run_id>.jsonl` 追加一行**；MAY 调用 `ocr` 辅助，缺失降级继续；MUST NOT 修改任何业务代码（只读审查）
- [ ] 2.6 `core/agent_runner/prompt_builder.py`：新增 code-review prompt 构建分支（注入 manifest 清单、窗口、输出 jsonl 路径、ocr 可用性提示），登记进 prompt 分发；模型解析（chain 回退 `code-review` → `self-review` → `administrator`）

## 3. 调度检查点与 run 实现

- [ ] 3.1 `core/agent_runner/maintenance_runs.py`：新增 `run_code_review(...)`——生成 `run_id = f"code-review-{int(time.time())}"`；落盘 manifest 到 `.fenix/code-review/manifest-<run_id>.json`；构建 prompt 调 runner（main 树执行，同 `run_self_review` 形态）；run 结束读 `.fenix/code-review/out-<run_id>.jsonl` 并调 `upsert_findings` 入台账；`manual_full` 再调 `resolve_snapshot` 核销
- [ ] 3.2 `core/admin_monitor.py`：新增 `_run_code_review_checkpoint()`——守卫与自省同源（`enabled`、同自然日防重、`run_at` 未到不跑）；读取窗口与 scope（周期=scheduled/window 语义），收集 manifest，manifest 为空则记录并跳过（不派发空 run）；单飞（已有 code-review run 在跑则跳过）
- [ ] 3.3 `core/admin_monitor.py`：在 `run_once()` 的 self_review checkpoint 之后调用 `_run_code_review_checkpoint()`（时点对齐自省；两 checkpoint 互不阻塞）
- [ ] 3.4 `fenixd.py`：登记手动触发信号 `.fenix/code_review_request.json` 的消费（`{scope: "full"|"window", requested_at}`）——主循环读取→删除→派发 `run_code_review`（`scope` 映射 `review_kind`：full→manual_full、window→manual_window）；已有运行中则忽略并记录
- [ ] 3.5 取消：确认 `code-review-*` run 的 run_id 能被既有 `cancel_run` / `.fenix/cancel_run_request.json` 机制正确归一化匹配（若 `_normalize_run_id` 对 `code-review-` 前缀无碍则无需改动；如需则补齐并说明）；取消后**部分 out jsonl 保留**（不清理）

## 4. Dashboard 后端（读取器 + 路由）

- [ ] 4.1 新建 `core/dashboard/data/code_review.py`：`read_code_review_items(project_root, statuses=None)` 读台账并按状态过滤（默认仅 `open`），按 severity 排序；`read_code_review_progress(project_root)` 转导 `core.code_review.read_progress`
- [ ] 4.2 新建 `core/dashboard/routes/code_review_routes.py`：`GET /api/code-review/items`（query `project`、可选 `status`）、`GET /api/code-review/progress`（query `project`）、`POST /api/code-review/run`（body `{project, scope}`；已有运行中返回 409）、`POST /api/code-review/generate-spec`（body `{project, item_ids}`）、`POST /api/code-review/items/status`（body `{project, item_id, status}`）
- [ ] 4.3 `core/dashboard/routes/base.py`：在 `_API_GET_ROUTES` 注册两个 GET（`/api/code-review/items`、`/api/code-review/progress`），在 `_API_POST_ROUTES` 注册三个 POST（`/api/code-review/run`、`/api/code-review/generate-spec`、`/api/code-review/items/status`）——均为 `exact` 路由
- [ ] 4.4 `POST /api/code-review/run` 实现：写 `.fenix/code_review_request.json` 信号（不直接同步跑审查），运行中返回 409 `{"error": "已有审查在进行中"}`
- [ ] 4.5 `POST /api/code-review/generate-spec` 实现：调 `core.code_review.generate_fix_spec`，返回 `{ok, spec_name, skipped, error}`；成功把条目置 `in_spec`

## 5. 前端「质量」分面

- [ ] 5.1 `core/dashboard/static/src/services/dashboard.ts`：新增 5 个服务函数（`getCodeReviewItems` / `getCodeReviewProgress` / `triggerCodeReview` / `generateFixSpec` / `setCodeReviewItemStatus`），对齐既有 `request<T>` 封装与端点
- [ ] 5.2 新建 `core/dashboard/static/src/pages/projects/components/QualityTab.tsx`：props `{ project: string; active: boolean }`；`active` 为真时才拉取与订阅（对齐 `SessionPanel` 的 active 门控，未选中零请求）
- [ ] 5.3 `QualityTab` 表格：`Table` + `rowSelection`（`selectedRowKeys` 状态），列含 严重度/文件:行/问题标题/所属 SPEC/状态，支持严重度与状态过滤排序；默认仅 `open`；随 `EventSource('/api/stream')` 增量刷新 + 心跳兜底
- [ ] 5.4 `QualityTab` 右上角两个按钮「全仓库审查」「立即审查本周期」——分别调 `triggerCodeReview(project, 'full'|'window')`；409 时提示「已有审查在进行中」；成功后进入运行中态
- [ ] 5.5 `QualityTab` 运行中态：轮询 `GET /api/code-review/progress` 渲染真实百分比进度条（`done/total`）+ 当前文件文案 + 取消按钮；取消调既有 `cancelRun(project, runId)`（run_id 由 progress 的 `review_id` 提供）；无运行时不渲染进度区；运行结束收起并刷新表格
- [ ] 5.6 `QualityTab` 底部「生成修复 SPEC」按钮（选中 > 0 才可用）：调 `generateFixSpec(project, selectedRowKeys)`，成功提示 SPEC 名并从 open 列表移除已 `in_spec` 条目
- [ ] 5.7 `QualityTab` 开关区：`admin.code_review.enabled` 的开关（读 `GET /api/config`、写 `POST /api/config`），与两个触发按钮同区（design D7）
- [ ] 5.8 `core/dashboard/static/src/pages/projects/list.tsx`：`quality` 分面 children 由 `Empty` 空态替换为 `<QualityTab project={name} active={activeTab === 'quality'} />`
- [ ] 5.9 运行 `cd core/dashboard/static && npm run build` 通过（构建产物 `dist/` 不入库，由框架重建）

## 6. 生成修复 SPEC（复用 evolution 链路）

- [ ] 6.1 `core/code_review.py` 实现 `generate_fix_spec(project_root, state_machine, item_ids) -> dict`：筛出 `status == "open"` 的选中条目（其余进 `skipped`），缺关键字段（`file`）的进 `skipped` 不整批失败；无有效条目返回错误
- [ ] 6.2 生成草稿内容：`proposal.md`（Why/What/Capabilities/Impact）、`design.md`、`specs/<capability>/spec.md`、`tasks.md`——`tasks.md` MUST 含 `## Deliverables` 声明段（每条目 `file` 作为 `modify`）并内联各条目 `title` 与 `file:line`；`.spec.yaml`（`schema: spec-driven` + `created` + `mode: full`）
- [ ] 6.3 复用同源 lint：`sys.path` 指向 `<proot>/.fenix` 后调 `core.deliverables.lint_declared` / `lint_tasks_parseable`（MUST NOT 自实现第二套）；有 violation 则删除草稿、返回错误、条目状态不变（不半写）
- [ ] 6.4 命名消解：基名 `fix-cr-<slug>`（slug 由首个条目 category/短标题推导，满足 kebab-case）；冲突则追加 `-<fingerprint[:6]>` 重试；判重覆盖 `spec/changes/<cand>`、STATE 既有条目名、`spec/archive/*-<cand>` 三处；仍冲突返回错误不覆盖
- [ ] 6.5 落地与注册：复制草稿到 `spec/changes/<name>` → 仅 `git add spec/changes/<name>` 并 `git commit -m "[fenix] spec: <name>"` → `state_machine.add_spec(name, {"status": "drafted", "priority": 5})`（不写 `start_after`，立即进入调度）；成功后把参与条目置 `in_spec` 并写 `spec_name`
- [ ] 6.6 幂等：同批 `item_ids` 重复提交且已成功时，MUST 返回既有 `spec_name`（通过条目已 `in_spec` + `spec_name` 判定，不重复生成）

## 7. 配置、文档与测试

- [ ] 7.1 `.fenix/config.template.yaml`：新增 `agents.models.code-review` 模型分配示例与 `admin.code_review`（`enabled: false`、`max_files`）段，附注释
- [ ] 7.2 `docs/help/09-config.md`：文档化 `admin.code_review.enabled` / `max_files` 与 `agents.models.code-review`（含缺省值、语义、与 `self_review` 周期同源的说明）
- [ ] 7.3 `tests/test_code_review.py`：覆盖 指纹稳定性（大小写/空白归一）、去重 upsert（同 fingerprint 不增条目、只更新 last_seen_at）、快照核销（manual_full 核销、window 不核销、不动 in_spec/ignored）、窗口计算（有/无 last_run_at）、命名消解（基名/冲突后缀/仍冲突报错）、lint 不通过不半写、生成幂等、`skipped` 语义
- [ ] 7.4 `tests/test_code_review.py`：覆盖 agent 类型四处注册一致性（`AGENT_PROMPT_FILES`、`RUN_ID_AGENT_PREFIXES`、`KNOWN_AGENT_TYPES`、`agents/code-review.md` 存在），以及 `infer_run_agent_type("code-review-...")` 返回 `("code-review", ...)`
- [ ] 7.5 `tests/test_code_review.py`：覆盖 `get_code_review_config`（缺省 enabled=False、非法 max_files 回退缺省），以及开关关闭时 checkpoint 零动作（不派发、不写产物）
