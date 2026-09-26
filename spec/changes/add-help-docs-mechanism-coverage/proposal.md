## Why

2026-09-26 的 docs/help 与代码现状偏差审计定案：框架近两周演进出的约 30 项重要机制在帮助文档中零记载，用户可感知的行为（验证全绿却停在 testing、ready 迟迟不派发、取消后 SPEC「消失」、审查误报反复上报、门禁面板长什么样）在文档里没有任何解释入口。P0 级「描述与行为相反」的修正由姊妹 SPEC `fix-help-docs-contra-behavior` 承载；本 SPEC 承载 P1（缺失机制补节）与 P2（结构校准），把文档观测面补齐到与代码同一代际。

## What Changes

- `05-verification.md` 新增：env 豁免 admin 握手细节、fastlane 小缺陷轻量通道（主树直接修复+子集重验）、judge 重裁决治理与 verdict 缓存、迟到 verifier 结果终态丢弃、逐测超时门（pytest 10s + tests/timeout-allowlist.yaml）、infra 失败预算豁免、parallel_plan.json 并行出题产物。
- `06-governance.md` 新增：run 止损三件套（`agents.run_stall_budget_*`）、瞬断解封渐进恢复（`agents.transient_unseal_*` 五键 + 冻结>hold>探针>错峰 态序）、信号死法冷却、SPEC 并发在飞守卫、infra 预算豁免对账字段。
- `03-lifecycle.md` 新增：取消保持态 `_cancelled_hold`（「冻结与解冻」节旁），与 08 章详情行工具条「恢复运行」动作互为入口。
- `07-safeguards.md` 新增：stash pop 冲突三分诊细节、merge-back spec 目录在飞顺延守卫、relocation writeback 同层修正、信号前置探测+处置回写、告警降噪治理、陈旧悬空 4h 硬上限。
- `08-dashboard.md` 修正与新增：分面更名（「SPEC 开发」→「功能开发」、「Claude Code 会话」→「会话接入」）、会话接入分面全貌（显式启动/SSE 流/composer `/` 命令与 `@` 文件补全/草稿持久化/空闲 30min 回收）、SPEC 详情页页面级页签全集（运行时间轴/场景结果/Bug 列表/失败截图/Hook）、质量门禁 Card、运行记录降噪+聚合+向前分页、SPEC 列表筛选 URL sticky、回归分面「自动修复回归问题」按钮、代码审查分面五动作、设置页 11 页签与质量页签 2 卡现状、详情行工具条「恢复运行」动作。
- `09-config.md` 补录缺失配置键：`agents.timeout_overrides.*`、`agents.impl_run_budget_max`、`agents.verify_redo_budget`、`agents.transient_unseal_*` 五键、`agents.run_stall_budget_*` 三键、`stale_code_selfheal.max_dangling_seconds`、`admin.code_review.scope/stall_alert_minutes`、`admin.code_review_fix.targeted_retry_max`（若姊妹 SPEC 未覆盖）、`admin.review_stall_minutes`、`admin.mergeback_wip_orphan_grace_minutes`、`verify.repo_code_review_concurrency`、`verify.impl_code_review_mode`、`verify.impl_code_review_lane_timeout_sec`。
- `10-artifacts.md` / `11-logs.md` 补全：STATE.md 内部字段全表（≥35 个 `_` 前缀字段中可观测的关键项）、`.fenix/` 文件地图新增条目（parallel_plan.json、fastlane_decision.json、quality-gates.json、architecture/、code-review 分片与 fix-* 台账、spec_delete_request.json、restart_history.jsonl、supervisor_runtime.json、scheduling_kick/ 等）。
- `04-cli.md` 结构修复：bin/ 辅助脚本表混入托管态表格的三行归位、补录 `fenix_cli.py` 等 18 个脚本中用户可用的主要项；`12-faq.md` 修复重复的「## 9.」编号、紧急止损条目补 run 止损指引。

## Capabilities

### New Capabilities
- `help-docs-mechanism-coverage`: 帮助文档缺失机制补齐与结构校准——近两周演进机制的文档化（验证链新机制、code-fix 车道全机制、调度与守护新机制、质量门禁整链、会话分面）、缺失配置键与 STATE 字段补录、文件地图补全、CLI/FAQ 结构修复与 UI 名称校准。

### Modified Capabilities

## Impact

- 仅改动 `docs/help/*.md`（03/04/05/06/07/08/09/10/11/12 共 10 份），零代码、零配置、零运行时行为变化。
- 帮助页前端按需拉取，合并后刷新即生效；无需 daemon 重启。
- 与姊妹 SPEC `fix-help-docs-contra-behavior` 存在 7 份重叠文件（03/05/06/07/08/09/12）：本 SPEC 以合并后最新文档为基线只增不删其新口径（见 design R3）。
