# Design: add-payload-authoring-and-verify-wip-isolation

## Context

2026-11-12 web-browser-client 修订重验事故（本 SPEC 第 3 次处理同族问题）暴露两条链路缺口：

**链路 A（裁决自动化）**：`revise_scenario_reverify` 是注册表唯一 `requires_payload=True` 选项，载荷=完整修订场景集 JSON（实测 133,979B）。auto-exec 引擎（core/admin_auto_exec.py `_maybe_auto_exec:350-435`）门序：arbiter 调查痕 → grace（缺省 30min，core/config.py `get_auto_exec_config:3005` 单源）→ 推荐 choice 唯一正向解析 → risk_tier=reversible → **载荷门 :403-408 命中即前置跳过**（requires_payload 且自动通道无载荷）→ spec_scoped 守卫 → 高档冲突 → 连击上限。跳过无闩锁：每分钟 tick 重复完整评估并刷同文 INFO（实测 09:07–09:11 五条）。策略语句写死"转人工"，不派发任何可起草载荷的 agent run——推荐可达但执行永不可达，人工面板（useAlertAdjudication.tsx:72 → alert_routes.py:539 note 即载荷通道）无编辑器/预填/校验/前置指引，人工要连踩「载荷缺失」「冻结未解」两个错才能凑齐执行器门序（admin_actions.py:2702 ②载荷解析先于④冻结前置）。前科：2026-10-31 修 200 字截断、10-30/11-03 修桶注册——均为"推荐可达、执行不可达"的不同断面。

**链路 B（验证构建）**：验证轮构建与场景命令直接在共享主树执行（verify_engine/cli_runner.py 原地 cwd）。同日交互会话在主树留下 boot-recovery 半成品 WIP（StreamService.kt `requestRecovery`/`recoveryPass` 未解析引用），gradle `BUILD FAILED in 11s` 全轮 fail。框架对主树 WIP 已有归因降级（admin_stray_wip.py info 留痕），但 fail 轮数与 `_env_block_rounds` 照计，他人合法并行工作持续逼近本 SPEC 的 env 冻结阈值——语义错位：并行 WIP 是框架隔离问题，不是被测环境失败。merge-back 已有同类先例可对齐口径：`_detect_wip_overlap`（core/worktree_manager/mergeback.py:907，dirty tracked∩分支改动面，排除 `spec/changes/**`，evo-merge-back-wip-overlap-gate D2）、`MergeConflictInfo.wip_overlap`（core/worktree_manager/types.py:206）、autostash `:(exclude)spec/changes`（core/worktree_manager/stash_guard.py:205）。

## Goals / Non-Goals

**Goals**：requires_payload 选项形成"闩锁→起草→人工批准→既有门序执行"闭环；跳过循环静默化；面板一次交互内可见并凑齐全部前置；验证构建与主树 WIP 解耦且跳过不计数。

**Non-Goals**：不自动执行任何 requires_payload 修订（保守原则不变）；不改载荷契约形态；不动执行器既有门序与白名单；不实现通用 payload 编辑器框架（仅裁决告警场景）；不做主树 WIP 的 stash/清理（绝不触碰用户工作区）。

## Decisions

### D1. 闩锁在 auto-exec 引擎内实现，状态挂告警记录
闩锁 = 告警记录 auto_exec 投影字段（`skip_reason="requires_payload"` + 推荐 choice id），引擎读投影短路。不新增独立状态文件、不改 STATE.md schema（否则又是一次双源漂移）。解除事件：告警状态变化、草稿指针落位/移除、记录被编辑。
**Alternatives 竞选**：全局"每告警 skip 一次"幂等表（独立 JSON）——被否决：与告警生命周期脱钩，清理语义复杂。

### D2. 起草 run 复用 Administrator 派发机器，kind=admin_payload_draft
core/admin_monitor.py 既有 dispatch 机器加一种 kind：输入=告警上下文（spec、signal_type、judge 归因引用、推荐 choice、预算余量），输出产物经结果门校验（只许落草稿文件+告警指针，出现任何执行类痕迹判 fail——fail-closed 对齐处置产物硬门先例）。单飞 + 连续上限 2 + grace 复用 auto_exec 配置（不新增配置段，避免多源）。
**Alternatives**：让 arbiter 兼职起草——被否决：arbiter 是只读调查角色，混执行产物撰写会破坏调查独立性；新建独立 worker 进程——被否决：派发/单飞/留痕机器已存在，复用零新增基础设施。

### D3. 草稿落 `.fenix/admin_payload_drafts/<alert_id>.json`，指针挂告警记录
目录加入 .fenix 运行时排除面（gitignore）。落位前必须通过与执行器同源的 `validate_scenario_dicts`（core/verify_engine/scenarios.py:1946）+ `validate_scenario_revision_paths` 预校验——草稿不可执行即为废稿，不留脏产物。执行仍走 alert-resolve note 通道与执行器全门序，零新执行代码。

### D4. 面板：选项元数据随 choices 下发，编辑器纯前端组装
选项增 `requires_payload` 布尔与 payload_schema 摘要（数据源自注册表单源 adjudication_choices.py）；编辑器三态预填（草稿/等待起草/人工粘贴），前置清单（冻结态+一键解冻复用既有 unfreeze API、预算余量、载荷体积）在提交前渲染。服务端不做载荷组装——契约对人工透明，避免服务端黑盒二次漂移。桌面列表行保持现状（用户既有决策），载荷交互仅出现在下拉选中 requires_payload 选项时，普通选项零回归。

### D5. G5 用"干净 worktree 优先、跳过不计数兜底"，否决一切触碰用户工作区的方案
预检 = dirty tracked 清单（口径单源复用 core/worktree_manager/queries.py 的 porcelain 解析）与验证构建输入路径求交（排除 `spec/changes/**`，对齐 `_detect_wip_overlap` evo-merge-back-wip-overlap-gate D2 口径）。重叠 → 从 HEAD 建/复用验证 worktree 执行全流程，verify_root 入报告；创建失败/不可构建 → 本轮 skipped：不计失败轮、不递增 `_env_block_rounds`、不推进 escalation.py ENV_BLOCK_FREEZE_THRESHOLD 判定。
**Alternatives**：stash 用户 WIP 再验——被否决：动他人活跃工作区，风险不可接受；主树构建加文件级快照回滚——被否决：复杂且仍污染工作区；直接跳过不做隔离——被否决：会长期掩盖真实构建回归，worktree 隔离才是正解。

### D6. 跳过语义与失败计数解耦
新增 skip 原因枚举（`wip_overlap_isolation_unavailable` 等）与失败轮计数互斥；judge 归因对隔离轮加 info 级标注。确保「并行 WIP」永不伪装成「环境失败」。

### D7. 风险与回滚
自动通道保守原则不变（对 requires_payload 永不直接执行）→ 最坏情况退化为现状纯人工；闩锁/起草/编辑器/隔离四个改动彼此独立，可按 capability 分批回滚。主树干净时验证行为零变化（预检短路）。

## Deliverables

前置阅读：proposal.md（G1–G5 与 Why）、四个 capability spec（本目录 specs/）、知识域 admin-ops（adjudication-auto-exec / admin-choices-contract）与 verify-pipeline/verdict-adjudication 域页。实现顺序建议：D1 闩锁 → D2/D3 起草 → D4 面板 → D5/D6 隔离；每步跑 tests/ 对应用例。UI 改动遵循仓库根 DESIGN.md。

```yaml
- path: core/admin_auto_exec.py
  kind: modify
  description: 载荷门跳过闩锁：投影字段写入、tick 短路、解除事件重评
- path: core/admin_monitor.py
  kind: modify
  description: 起草 run 派发（kind=admin_payload_draft、单飞、连续上限、grace 复用）
- path: core/admin_choice_exec.py
  kind: modify
  description: 起草 run 结果门校验（只许草稿产物，执行痕迹 fail-closed）
- path: core/dashboard/data/admin_payload_drafts.py
  kind: new
  description: 草稿存取：落盘预校验、告警指针、只读取
- path: core/dashboard/data/admin_alerts.py
  kind: modify
  description: 告警记录投影与 draft 指针字段
- path: core/dashboard/data/adjudication_choices.py
  kind: modify
  description: 注册表导出 requires_payload 与 payload_schema 摘要（单源透出）
- path: core/dashboard/routes/alert_routes.py
  kind: modify
  description: GET 草稿只读端点 + alert-resolve 载荷选项元数据下发
- path: core/dashboard/static/src/hooks/useAlertAdjudication.tsx
  kind: modify
  description: 载荷编辑器、前置清单、一键解冻、按草稿执行
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
  description: 草稿取读客户端与选项类型扩展（resolveAlert 签名不变）
- path: core/verify_engine/engine.py
  kind: modify
  description: 轮启动 WIP 重叠预检与隔离/跳过决策编排
- path: core/verify_engine/cli_runner.py
  kind: modify
  description: verify_root 注入、隔离 worktree 内命令执行与报告标注
- path: core/verify_engine/skip_semantics.py
  kind: new
  description: 跳过原因枚举、不计数语义与 info 留痕
- path: core/worktree_manager/lifecycle.py
  kind: modify
  description: 验证 worktree 供给（从 HEAD 创建/复用，不绑 spec 锁语义，绝不 stash/checkout 主树）
- path: core/worktree_manager/queries.py
  kind: modify
  description: 验证预检口径供给（dirty tracked 清单单源，排除面常量对齐 merge-back）
- path: tests/test_admin_auto_exec_policy.py
  kind: modify
  description: 闩锁首跳/短路/解除重评/人工不受影响用例
- path: tests/test_dual_lane_adjudication.py
  kind: modify
  description: 起草 run 派发幂等与上限用例
- path: tests/test_admin_payload_drafting.py
  kind: new
  description: 起草契约用例（预校验、落位指针、越界拦截、降级）
- path: tests/test_adjudication_choices.py
  kind: modify
  description: requires_payload 元数据透出用例
- path: tests/test_verify_wip_isolation.py
  kind: new
  description: 预检/隔离执行/主树字节不动/跳过不冻结用例
- path: tests/test_verify_cli_runner.py
  kind: modify
  description: verify_root 留痕与标注用例
```
