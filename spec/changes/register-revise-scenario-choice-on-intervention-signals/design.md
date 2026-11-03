# design — manual-intervention/verify_env_blocked 信号桶注册 revise_scenario_reverify

## 1. 背景与问题机制链

- `revise_scenario_reverify` 仅注册于 `inconclusive_loop` 桶（`ADJUDICATION_CHOICES` 11 桶之一，core/dashboard/data/adjudication_choices.py:224-256；桶键全集实测不含 `manual-intervention` 与 `verify_env_blocked`）。
- 场景争议类升级的实际消费信号：`manual-intervention`（Administrator 处置请求转人工边，core/pm_engine/arbiter.py:92）、`verify_env_blocked`（pipeline 争议/环境阻塞，arbiter.py:81、engine.py:3026）——两信号在注册表无桶。
- `resolve_choice` 解析序（adjudication_choices.py:605-641）：signal_type 未注册 → 全表反查 → 该选项 `spec_scoped=True` → `(None, "scoped-no-reverse")`。执行器同序拒绝（admin_actions.py:3058-3065：「为 spec 作用域动作，信号未注册裁决选项集，不经跨信号全表反查兜底放行」）。
- 结果：Administrator 即便给出完美 `choice_payload` 载荷，处置仍在解析层被拒，烧满 admin run 预算后冻结转人工（2026-11-03 add-knowledge-inbox-pipeline 实测 605s/$1.79）。

## 2. 方案：纯注册表增量，消费侧零改动

### 2.1 选项常量单源化（沿既有约定）

注册表头注约定「跨信号逐字共享的选项提为模块级单源，各信号元组按引用复用：字段演进只改一处」（adjudication_choices.py:59-62；`_ABANDON` / `_MANUAL_FIXED_REVERIFY` 先例）。据此：

- 把 `inconclusive_loop` 桶内联的 `revise_scenario_reverify` 条目（233-256 行，含其上注释块）原字提取为模块常量 `_REVISE_SCENARIO_REVERIFY`，置于既有选项常量区（`_MANUAL_FIXED_REVERIFY` 之后）；
- `inconclusive_loop` 元组改为引用该常量，字段逐字不变（行为零变化）；
- 新桶按引用复用同一常量——id/action/spec_scoped/destructive/requires_payload 跨桶一致由 import 期 `_assert_registry_consistency`（398-425 行）fail-fast 钉死，任何单侧漂移直接拒绝启动。

desc 文案无信号特定措辞（「上限 2 次，超限转人工」对三桶同样成立），满足共享常量的单源前提（头注 60-62 行：仅 desc 带信号特定文案的同名选项保持就地声明）。

### 2.2 新增两桶

```python
"manual-intervention": (_REVISE_SCENARIO_REVERIFY,),
"verify_env_blocked": (_REVISE_SCENARIO_REVERIFY,),
```

- 桶键取实弹信号的注册表拼写：`manual-intervention`（连字符，arbiter.py:92）、`verify_env_blocked`（arbiter.py:81、engine.py:3026、pipeline.py:3783 `ENV_BLOCK_SIGNAL_TYPES`）。
- 单选项桶是有意收窄：本提案只修两次实弹发作的缺口族（场景修订出口不可达）；自由处置（choice_id=None）通道不受影响，admin/人工仍可自由裁量，注册面不扩权。
- 不加 `grant_env_exemption`：无实弹证据支撑该选项在两信号上被拒（两次事故均为 revise_scenario_reverify），避免无证据扩注册面；留待同族后续提案按证据成文。

### 2.3 消费侧为什么零改动（逐通道核对）

| 通道 | 位置 | 泛化性 |
|---|---|---|
| 解析单源 | adjudication_choices.resolve_choice:605 | 桶内精确匹配，新桶即新合法集 |
| 执行器 | admin_actions.execute_adjudication_choice:3049-3089 | resolve_choice 单源 + 按 action 分派（`revise_scenario_reverify` → `_exec_revise_scenario_reverify`:3086），与 signal_type 无关 |
| 自动执行守卫 | admin_monitor._apply_choice_execution:8868-8979 | requires_payload 从解析结果读取（8882-8884）；载荷缺失 → not-ok skipped 信号保留待重审（8968-8979），不产生假收口 |
| 处置产物硬门 | agent_runner/maintenance_runs.py:504-553 | `choice_requires_payload` 注册表单源（adjudication_choices.py:644-660），无选项名单硬编码 |
| 结果闸门 | agent_runner/result_gate.py:291 | 同上单源 |
| 告警选项附加 | pm_engine/family.py:1697 `choices_for(signal_type)` | 新桶注册后新告警自动携带 choices |
| 前端下拉 | dashboard 告警区 + alert_routes.py:536 | 记录快照优先，缺快照回退 choices_for 实时表 |

`requires_payload=True` 形态按注册表现状保持（249-255 行），载荷契约（fix-admin-choice-payload-and-scenario-pairing 1.1/4.1 落地）原样生效：Administrator 自动路径经处置记录 `choice_payload` 整体直传（admin_monitor.py:8965-8967），人工路径经 alert-resolve 端点 note JSON。

## 3. 边界与回归

- **存量告警**：注册前发射的告警若带空 choices 快照，人工下拉路径维持快照集，不回溯获得新选项；admin 自动处置通道走 resolve_choice 实时解析，不受快照限制——本提案主修通道即后者。新发射告警自动携带。
- **is_adjudicable 面扩大**：两信号从不裁决变为可裁决，方向即本提案目的。误选护栏由既有双层设防兜底：载荷缺失 skipped（admin_monitor.py:8968-8979）；`SCENARIO_REVISION_MAX_COUNT` 修订上限超限拒绝转人工（admin_actions.py:2748 起）。
- **信号通道语义不变**：两信号维持 ESCALATION 告警区渲染（`SIGNAL_CHANNEL_SIGNAL_TYPES` 不含它们，adjudication_choices.py:427-430），不新增 kind=SIGNAL 记录形态。
- **destructive 确认门**：该选项非 destructive，前端 choiceNeedsConfirm 回退清单（注册表头注 40-43 行）无需同步。
- **spec_scoped 语义成立**：两信号均携带具体 spec（arbiter.py:81-92 转人工边按 spec 立案），全局信号守卫（`is_global_spec`，admin_monitor.py:8889-8899）不触达。

## 4. 测试策略

- tests/test_adjudication_choices.py 扩展：新桶 resolve_choice 正解（两 signal_type × 该 id → (dict, "") 且 requires_payload=True）、三桶解析等值（单源不漂移）、未注册信号仍 scoped-no-reverse（负向控制）、已注册桶不含该 id 仍 not-in-bucket（负向控制）、inconclusive_loop 既有断言不变。
- 相邻契约回归零改动预期全绿：tests/test_env_scenario_revision_exit.py、tests/test_admin_prompt_choice_payload_contract.py、tests/test_global_signal_choice_guard.py、tests/test_dual_lane_adjudication.py。
