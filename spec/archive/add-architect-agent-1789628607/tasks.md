# Tasks: add-architect-agent

## Deliverables

```yaml
- path: agents/architect.md
  kind: new
- path: core/config.py
  kind: modify
- path: core/agent_runner/prompt_builder.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: core/agent_runner/run_files.py
  kind: modify
- path: core/self_review.py
  kind: modify
- path: core/dashboard/data.py
  kind: modify
- path: core/dashboard/static/src/pages/settings/components/AgentModelPanel.tsx
  kind: modify
- path: core/dashboard/static/src/pages/settings/components/ArchitectPanel.tsx
  kind: new
- path: core/dashboard/static/src/pages/settings/index.tsx
  kind: modify
- path: tests/test_architect_role_registration.py
  kind: new
- path: tests/test_architect_schedule.py
  kind: new
- path: tests/test_architect_scope_window.py
  kind: new
- path: core/dashboard/static/tests/architectRoles.test.mjs
  kind: new
- path: docs/help/02-concepts.md
  kind: modify
- path: docs/help/09-config.md
  kind: modify
- path: .fenix/config.template.yaml
  kind: modify
```

> 路径说明（2026-09-15 评审更正）：原注释以「前序 `refactor-dashboard-data-module` 会拆包、本 SPEC 注册时尚不存在该路径」为由不登记 `core/dashboard/data.py`——**与实测不符**。实测：`core/dashboard/data.py` 存在（5334 行），`core/dashboard/data/` 包不存在，且 `refactor-dashboard-data-module` 仅为 `spec/changes/` 下草稿、未实现。同批次 `spec/changes/fix-observability-gaps/tasks.md` 与 `spec/changes/fix-dashboard-read-path-performance/tasks.md` 已就同一处陈旧注释作出更正，结论为「不登记权威修改路径会导致交付集缺项」。据此本 SPEC 显式登记 `core/dashboard/data.py` 为权威修改路径（受管键合并分支 / 前置校验 / 来源标注 / 缺省回显四处均在该文件）。前端 `dist` 产物由框架 merge 后自动重建，不列为交付物。

## 1. 后端角色接线

- [ ] 1.1 `core/config.py`：`KNOWN_AGENT_TYPES` 追加 `architect`；确认 `agents.models.architect` 通过校验
- [ ] 1.2 新增 `agents/architect.md`：定义身份、五种 DFX 维度、受限审查范围、输出契约、禁止自动建 SPEC
- [ ] 1.3 `core/agent_runner/prompt_builder.py`：`AGENT_PROMPT_FILES` 追加 `architect`；实现 `_build_architect_prompt`（注入窗口内变更文件清单与注入格式）
- [ ] 1.4 `core/agent_runner/runner.py`：`AGENT_TYPE_TO_ROLE` 追加 `architect`；实现 `run_architect` run 入口（参照 `run_self_review`：主树运行、独立前缀、独立结果文件、token 归账）
- [ ] 1.5 `core/agent_runner/run_files.py`：`RUN_ID_AGENT_PREFIXES` 追加架构师前缀
- [ ] 1.6 新增 `tests/test_architect_role_registration.py`：断言五处注册表均含 `architect` 且前后端列表一致

## 2. 调度接入（design D1 / D2 / D8）

- [ ] 2.1 `core/self_review.py`：架构师 run 接入 `SelfReviewScheduler.check_and_run` **唯一门**——固定排在自省路径（含其零活动跳过 `_skip_review`）之后执行；架构师 MUST NOT 在自省写状态之前触发
- [ ] 2.2 `core/self_review.py` **状态键分离**：`_save_state` 新增 `architect_last_run_date` 写入口；架构师路径 MUST NOT 写 `last_run_date`（会抑制当日自省）与 `last_run_at`（自省增量窗口锚点，覆写会使次日窗口起点漂移）；`check_and_run` 整日早退门改为「`last_run_date == today` 且 `architect_last_run_date == today`」——架构师单独失败时同日可补跑
- [ ] 2.3 新增窗口内变更文件清单采集（design D2 三来源并集：`git log --since --name-only` + `git status --porcelain`/`git diff --name-only` + mtime 降级扫描），按后缀白名单与路径白名单过滤、条数上限截断并标注；**MUST NOT 用 `code_files_changed_since` / `max_code_mtime_ns` / `code_tracked_files` 作为清单来源**（前者需先有清单且只返回布尔，后者只 glob `fenixd.py` + `core/**/*.py`，会漏掉 `agents/`、`tests/`、前端 `src/`）
- [ ] 2.4 `core/self_review.py` **run 统计排除**：`collect_runs_stats`（现仅排除 `review-`）把架构师 run_id 前缀一并排除，否则架构师 run 会计入自省自身的 total/failed 并可能点亮零活动防护而误唤起自省；同步确认 `collect_failed_run_samples` 与 Dashboard run 视图口径
- [ ] 2.5 新增配置键 `admin.architect.enabled`（布尔，缺省 false）与 `admin.architect.window_max_hours`（非负整数，0/缺省 = 跟随自省窗口；>0 = 窗口下界取 `max(window_start, now - N hours)`），写入 `config.template.yaml` 缺省并加注释
- [ ] 2.6 新增 `tests/test_architect_schedule.py`（定时触发/开关关闭零动作/同日不重复/**架构师不写 `last_run_date`**/**自省失败后架构师仍可补跑且不影响次日自省窗口锚点**）与 `tests/test_architect_scope_window.py`（仅注入窗口内变更文件/未提交改动被采集/无变更零产出/清单超限被截断且有标注/非 git 仓库走 mtime 降级）
- [ ] 2.7 全量 pytest，独立 commit

## 3. 建议产出与失败处置（design D8）

- [ ] 3.1 架构师产出复用 `todo.md` 既有结构化条目写入路径（与自省同格式、同追加语义）；条目 MUST 含 DFX 维度、涉及文件、证据、建议动作
- [ ] 3.2 断言不自动创建 SPEC / 不注册 STATE / 不派发
- [ ] 3.3 失败处置与自省同款：异常/超时/rc≠0 走 `_record_failure_alert` 记告警、当日不重试（防风暴），次日靠 `architect_last_run_date` 自然重试；`core/admin_monitor.py` 的 `_RUN_PREFIXES` 是否纳入架构师前缀按 D8 决定（建议纳入，否则连续失败无人在失败统计中察觉）
- [ ] 3.4 成本归账：沿用 `.fenix/cost/self_review_tokens.json` 独立类目，条目 `agent_type: "architect"`；写失败静默降级
- [ ] 3.5 全量 pytest（重点 `test_daily_self_review`、`test_agent_prompt_files`、`test_self_review_run_semantics`），独立 commit

## 4. 模型分配与设置界面（design D4 / D7）

- [ ] 4.1 前端 `AgentModelPanel.tsx`：`AGENT_ROLES` 追加 `architect` 卡片（与后端白名单同步）；注意该文件有并行 SPEC 的在飞改动，改动点限于 `AGENT_ROLES` 数组
- [ ] 4.2 后端受管键：确保 `agents.models.architect` 属可写受管键（`_AGENTS_MANAGED_SUBKEYS` 等），读写往返可用
- [ ] 4.3 新增 `ArchitectPanel.tsx` 并在「自进化」页签挂载；接入 `selfEvolutionSection` 的 collect 句柄（`index.tsx` 的 `handleSelfEvolutionSave` 需追加第三个 ref）；卡片 MUST 沿用 `SuggestedImprovementsPanel` 的 scope 约定——用户级作用域只读、`collect()` 返回空补丁
- [ ] 4.4 新增配置键走**四处必改点**（缺一处即静默丢弃）：`core/dashboard/data.py` 的 `_deep_merge_managed` 合并分支、`write_config` 前置校验、`_SOURCE_KEYS` + `_managed_key_sources` 来源标注、缺省回显；**MUST NOT 把架构师键挂在 `admin.self_review.<子键>` 下**（该合并分支只透传 enabled/read_todo/run_at）；同步 `config.template.yaml`；构建前端产物
- [ ] 4.5 前端一致性测试 `core/dashboard/static/tests/architectRoles.test.mjs`：模型分配页含架构师卡片；自进化页签含设置卡片；**保存 → 重新 GET → 值仍在**（读写往返断言，而非仅断言保存成功——本仓两次事故均为保存成功但值消失）
- [ ] 4.6 后端测试 `tests/test_architect_role_registration.py` 覆盖受管键读写往返与未知键降级路径

## 5. 文档同步

- [ ] 5.1 `docs/help/02-concepts.md`：Agent 类型表新增 `architect`（职责 + 触发时机「每日自省时刻」）
- [ ] 5.2 `docs/help/09-config.md`：`agents.models` 段的「键取九角色」枚举改为含 `architect`（该处现为写死枚举，新增角色不更新即成错误文档）；补 `admin.architect.*` 两键说明（先例：`fix-provider-transient-backoff` 的验证报告把「配置键未入模板 / 未入配置文档」记为 failed 项）
- [ ] 5.3 确认 `docs/help/10-artifacts.md` 的 run 前缀与产物映射是否需要补架构师条目

## 6. 收尾

- [ ] 6.1 全量 `bin/run_full_suite.py`；触发一次架构师 run 实证产出条目落入 `todo.md`
- [ ] 6.2 经用户确认时机后重启 daemon 使角色白名单生效并冒烟验证
