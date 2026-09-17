# Design: add-verify-unreachable-failfast

## Context

验证管线阶段2.5 `_ensure_app_reachable`（`core/pm_engine/verification.py`）在场景执行前确保被测应用可被浏览器访问：自动启动 `commands.start`/契约 `serve.cmd`、端口冲突换端口重试、就绪探针放行。其返回值 `(reachable, user_blocked, note)` 中 `reachable=False` 有三个确定性来源——纯 cli prepare 失败、契约缺失/解析失败、就绪/普通探针超时——但调用点 `_run_three_stage_verification` 只把结果写日志后直接丢弃（`verification.py:1792-1796`），注释「自愈失败由下方验证门禁兜底」意味着整轮场景照跑、由报告 `env_error` 后置兜底。`add-spec-approve-push-modal` 首轮即因此 14 场景空转（6 过/7 环境伪失败）→ judge 误拒 → 原地重新实现，单 spec $39.12。

本设计复用既有 `_escalate_env_blocked` 升级通道（落 blocked → 自动呼叫 Administrator → 连续 2 轮冻结转人工）与 `_ensure_app_reachable` 已产出的 `reach_note`（`add-verify-preflight-gate` D3 已内嵌 boot.log 尾部），把确定性环境错误从「整轮暴露」前移为「场景执行前短路」，零新机制。

## Goals / Non-Goals

**Goals**
1. `reachable=False and not user_blocked` 时本轮 fail-fast：场景执行数=0，落 blocked 走自动 admin 处置，不退回 plan 重排。
2. 一处短路统一命中三子源（探针超时 / prepare 失败 / 契约缺失），顺带消除契约缺失子案现有的整轮空转。
3. 短路时证据（reach_note 含 boot.log 尾部）完整送达 admin，无需重写 `verify_contract_missing` 信号。
4. 保留 `user_blocked` 守卫，为「需用户参与」场景留不误杀通道。

**Non-Goals**
- 不新增任何升级/信号机制——只复用 `_escalate_env_blocked` 与既有 `reach_note`。
- 不改 `_ensure_app_reachable` 内部自愈逻辑（启动/换端口/探针等待语义全部原地不动）。
- 不改判定链/门禁（`_escalate_env_blocked` 下游、verified 洗白门禁、judge）——短路只前置触发时机。
- 不产 verification-report.md——与消费期轻量自证短路 D2（`verification.py:1751-1771`）同一「fail-fast 态不产报告」语义。

## Decisions

### D1: 短路点——日志行之后、场景重读之前

插入位置为 `_run_three_stage_verification` 中阶段2.5 日志（`verification.py:1793-1796`）之后、自愈后场景重读（`verification.py:1798-1806`）之前：

```python
app_reachable, user_blocked, reach_note = self._pm._ensure_app_reachable(spec_name)
self._pm.logger.info(... )  # 现有日志，保持不变
if not app_reachable and not user_blocked:
    self._pm.logger.error(
        "pm_engine",
        f"[阶段2] 应用不可达，本轮 fail-fast（场景执行数=0）'{spec_name}': "
        f"{reach_note}",
    )
    self._escalate_env_blocked(
        spec_name, [reach_note], title="验证环境阻塞（应用不可达）",
    )
    return
```

- 位置理由：此处 `reach_note` 已确定、自愈副作用（端口改写）已结束，且无需再为重读场景付费；短路要在「重读场景文件」与「`env_error is None` 分支」之前，否则仍会走进场景加载与执行。
- 实现须将 `_user_blocked` 由 `_` 前缀改为绑定 `user_blocked`（条件需读它）；其余行不动。

### D2: 统一只调 `_escalate_env_blocked`，不重写 `verify_contract_missing`

三子源中仅「契约缺失/解析失败」子案已在 `_ensure_app_reachable` 内部（`verification.py:861-884`）自写 `verify_contract_missing` 信号；prepare 失败与探针超时无契约错误语义。故短路统一动作只有一条 `_escalate_env_blocked`：

- 契约缺失子案 → 信号已有一条 + 本次只补 `_escalate_env_blocked` 落 blocked/自动呼叫（与 D1 入口预检「写信号 + escalate」双通道同构，`request_admin_invoke` 有 conflict 去重，`verification.py:3244`）。
- 探针超时 / prepare 失败 → 无信号，仅 `_escalate_env_blocked`，标题「验证环境阻塞（应用不可达）」，violations=[reach_note]（自含具体原因与 boot.log 尾部）。

不按子源分流、不加新标题枚举——reach_note 已自描述，分流只会增加分支面。

### D3: user_blocked 守卫

`_ensure_app_reachable` 的 `user_blocked` 位为「需用户参与（收验证码/登录）」预留判定位（`verification.py:722`），当前所有返回路径恒 `False`（grep 实证）。短路条件显式含 `not user_blocked`：将来该位实现后，「需用户参与」的不可达不得被短路自动判 blocked，须留给既有后续路径人工处理。当前实现下守卫恒真、零行为差异，纯防御。

### D4: fail-fast 态不产报告——与 D2 一致

短路 `return` 早于 `VerifyEngine.run`，故不产生 report.json / verification-report.md，spec 直接落 `blocked`。与消费期轻量自证短路（`verification.py:1751-1771`）、入口预检短路（`_ensure_app_reachable` 内部）同一语义：确定性环境错误在场景执行前终结，无报告可写。blocked 态不经过 verified→pushed 判定链，无洗白风险。

### D5: 测试策略——mock `_ensure_app_reachable` 返回值 + 断言副作用

`tests/test_pm_verification.py` 新增三类回归（monkeypatch 打 `_ensure_app_reachable`）：

1. `(False, False, "就绪探针超时…")` → 断言 `VerifyEngine.run` 未被调用、`_escalate_env_blocked` 被调、STATE 落 blocked。
2. `(True, False, "")` → 断言行为与现状一致（run 被调）。
3. `(False, True, "需用户登录")` → 断言不短路（不落 blocked、不中止）。

优先 monkeypatch（不改生产函数），比构造真实超时（120s）更快更稳；必要时补一条真实不可达端到端（纯 cli 契约 prepare 失败路径 30s 内）。

## Risks / Trade-offs

- [短路可能误判「可达=False」为确定性错误] → 三子源均为「判定无法解决/缺配置」类确定性环境错误，非瞬时抖动；且 `user_blocked` 守卫挡住「需用户参与」未来语义。误杀面为零。
- [不产 verification-report.md 使 dashboard 时间轴缺节点] → 与 D2 自证短路既有表现一致；blocked 态在 STATE/alerts 中完整留痕（error 字段含 reach_note），时间轴读侧已按 STATE 重建 fallback（既有能力）。
- [`_escalate_env_blocked` 的 human alert evidence 引用 `report=.../verification-report.md` 可能陈旧/不存在] → 既有 D2/D1 路径同款；主证据是 violations 里的 reach_note（含 boot.log 尾部），report 引用仅辅助，接受。
- [契约缺失子案「信号 + escalate」双通道可能产生两次 admin 处置] → D1 入口预检既有同构双通道，`request_admin_invoke` 有 conflict 去重（`verification.py:3244`），且信号是 dashboard 展示、invoke 是自动派发，语义不同，接受。
- [frozen 阈值被连续短路快速消耗（2 轮→冻结）] → 是期望行为：环境反复不可达本应转人工；admin 处置成功走 `add-blocked-reverify-lane` 复位清零重验。

## Migration Plan

纯增不改既有语义：`reachable=True` 轮短路点不触发，行为逐字节不变；`reachable=False` 轮从「整轮空转 + 判定误拒」变为「1 次升级 blocked」。无配置新增、无 schema 变更、无数据迁移、无回滚面（改动单点，可随提交 revert）。落地顺序：改 `verification.py` 短路点 → 补测试 → 全量回归 → 由机械验证链验收。

## Open Questions

（无。）