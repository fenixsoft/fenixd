# 验证报告：evo-stale-selfheal-restart-cooldown

> ⚠️ 本报告由框架于 2026-09-22T00:08:50Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-22T00:08:50.116361+00:00

## 结论：✅ 通过（verified）

**状态：verified — 12/12 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 12/12 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 12 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 5.71M |
| 本链增量 Token（输出） | 0.04M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| cli-cooldown-suite-all-green | 运行本 SPEC 新增的完整重启冷却回归套件 tests/test_stale_selfheal_cooldown.py（31 用例，覆盖 FR-1~FR-4 全部正向/异常/空状态路径），要求 31 项全部 PASSED 且退出码 0。出处：tests/test_stale_selfheal_cooldown.py:1-31（用例定义）。 | pass | 0/7 | - |
| cli-cooldown-window-latch-and-alert | FR-1/FR-2 滑动窗口重启计数与冷却锁存：窗口内重启 ≥ cooldown_threshold 进入冷却、超窗条目不计、锁存期内窗口计数回落仍保持冷却、锁存期满恢复触发、enabled:false 时冷却不生效、再次进入冷却重新落告警。出处：tests/test_stale_selfheal_cooldown.py:242-324（TestCooldownWindow）。 | pass | 0/10 | - |
| cli-cooldown-config-keys-validation | FR-1 接口设计（五键校验）：缺 section 时五键回退缺省、合法值透传、bool 陷阱（isinstance(True, int)）与非正整数（0/负数/字符串）回退缺省、非 dict 节不抛异常。出处：core/config.py:1167-1250（get_stale_code_selfheal_config 白名单）；tests/test_stale_selfheal_cooldown.py:186-239（TestCooldownConfigKeys）。 | pass | 0/6 | - |
| cli-restart-history-persistence | FR-1 持久化与容错：成功触发重启后追加 .fenix/restart_history.jsonl 条目、未触发不写、写失败仅记日志不阻断重启、空状态（文件缺失/行损坏/字段缺失）按该条忽略、tick 入口清理 24h 前旧条目。出处：tests/test_stale_selfheal_cooldown.py:326-390（TestRestartHistory）。 | pass | 0/7 | - |
| cli-self-triggered-streak-escalation | FR-3 自触发型 stale 识别与升级：窗口内仅记 WARNING 且不写 restart_request、每周期只告警一次、跨重启周期持久化累计 streak 达阈值升 stale_selfheal_loop(critical)、阈值在缺省配置下可达、过期重启使 streak 归零、陈旧解除重置周期标记。出处：tests/test_stale_selfheal_cooldown.py:392-538（TestSelfTriggeredStale）。 | pass | 0/11 | - |
| cli-is-idle-covers-running-agents | FR-4 _is_idle 补全：agent_runner._running_agents 非空判非空闲、空字典判空闲、缺 agent_runner 属性/缺 _running_agents 不抛异常且判空闲、在飞 run 阻断 tick 触发。出处：fenixd.py:997-1030（_is_idle）；tests/test_stale_selfheal_cooldown.py:547-600（TestIsIdleWithRunningAgents）。 | pass | 0/7 | - |
| cli-panel-save-preserves-cooldown-keys | 设计决策 6 集成验证：Dashboard 面板保存 payload 仅提交 enabled/idle_confirm_seconds 时，文件侧五个冷却键（含非缺省值）经键级白名单合并后不被清除。出处：core/dashboard/data/config_admin.py:1023-1035（write_config 键级合并）。 | pass | 0/9 | - |
| cli-docs-cooldown-keys-documented | 文档同步（task 4.2）：docs/help/09-config.md 的 stale_code_selfheal 键表与 yaml 样例含五个新键及缺省值，并说明冷却无独立开关、整体关闭走 enabled:false。出处：docs/help/09-config.md:241-264。 | pass | 0/6 | - |
| cli-docs-safeguards-idle-and-alert-semantics | 文档同步（task 4.1）：docs/help/07-safeguards.md 空闲判定口径补 agent_runner._running_agents 维度，并补冷却告警 stale_selfheal_cooldown 与自触发升级告警 stale_selfheal_loop 语义。出处：docs/help/07-safeguards.md:101-108。 | pass | 0/5 | - |
| cli-regression-existing-selfheal-suites | 向后兼容回归：既有 tests/test_stale_code_selfheal.py（22 用例）与 tests/test_stale_selfheal_idle.py（9 用例）全绿——新冷却逻辑不得使 _DaemonParts 裸对象（未设 agent_runner）等既有用例失真。出处：spec 行为规范「既有用例不得回归」。 | pass | 0/7 | - |
| api-config-exposes-cooldown-defaults | FR-1 可观测面：GET /api/config 的 stale_code_selfheal 段回显五个新键及其缺省值（1800/3/600/300/3）。出处：core/dashboard/routes/base.py:306（路由注册）、core/dashboard/routes/settings_routes.py:28-34（handler → read_effective_config）、core/dashboard/data/config_admin.py:799（回显经 ConfigLoader.get_stale_code_selfheal_config）、core/config.py:1167（loader 白名单）。 | pass | 0/7 | - |
| api-config-selfheal-section-shape | 向后兼容可观测面回归：GET /api/config 的 stale_code_selfheal 段仍含既有 enabled/idle_confirm_seconds 且类型正确，与五个新键共存（本 SPEC 不改 /api/config 写白名单，键集只增不改）。出处：core/dashboard/data/config_admin.py:557-568（read_config 回显）、core/dashboard/data/config_admin.py:112-113（受管键白名单）。 | pass | 0/3 | - |

## 本轮场景集变更

当前稳定场景集共 12 个（第 1 轮）。

- 首轮写入 12 个场景

