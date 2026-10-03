## Deliverables

```yaml
- path: core/pm_engine/verification/escalation.py
  kind: modify
- path: core/pm_engine/verification/judge_gate.py
  kind: modify
- path: core/pm_engine/verification/verdict_evidence.py
  kind: modify
- path: core/state_machine.py
  kind: modify
- path: core/dashboard/data/adjudication_choices.py
  kind: modify
- path: core/dashboard/data/admin_actions.py
  kind: modify
- path: tests/test_env_exemption_exit_reachability.py
  kind: new
- path: docs/help/06-governance.md
  kind: modify
```

## 1. 级二握手首次命中即升级

- [ ] 1.1 `core/pm_engine/verification/escalation.py` `_handle_verdict_env_exemption_inconclusive`：级二命中即升级——写 `_write_inconclusive_loop_signal`（signal_type 保持 inconclusive_loop，evidence 附本轮失败签名摘要 + `_inconclusive_attempts` 当前值）**并**经 `pipeline._context.escalation_notifier` 发 human-escalation-alert（severity=major，description 说明「judge 已裁决全 env、等待人工豁免或修环境」）；spec 停 implemented、tester_run 清空、error 写等待人工裁决文案（**不用** FREEZE_ERROR_PREFIX 冻结前缀）、`_dispatch_backoff_until` 置退避防 orphaned_state 误报；**移除 enqueue verifier 自动重验调用**——升级后停止自动重验，人工处置是唯一出路；升级分支条件从 `attempts >= escalate_attempts or attempts >= max_attempts` 改为恒升级（首次命中即升级）
- [ ] 1.2 失败签名摘要助手：从 report.json 场景表提取（场景 id 集 + 每场景 `首失败断言 type + _normalize_fail_signature(actual)` 摘要），归一化口径与 `infra_classify._normalize_fail_signature` 一致；仅供 evidence 组装与 D2 比较，不新持久化
- [ ] 1.3 `_handle_env_exemption_handshake` 与 `_handle_verdict_env_exemption_inconclusive` 的 docstring 同步新语义（首次命中即升级；重验词形改为「人工处置后重置重验」）；既有 fail-open 守卫（AdminStore 读失败按无放行记录处置）不变

## 2. 级一签名一致提前升级

- [ ] 2.1 `escalation.py` `_handle_env_blocked_inconclusive`：重验上限读 `verify_engine.inconclusive_max_attempts`（缺省 3 → **2**，同步 ConfigLoader 单源注释与 config.template.yaml 缺省注释）；新增提前升级判定——本轮失败签名（1.2 助手扩展支持 blocked-env 场景签名）与 fail_history.json 上一轮完全一致 → 不入队剩余重验，直接写 inconclusive_loop SIGNAL + 人工告警（同 1.1 通道）停止自动重验
- [ ] 2.2 签名比较从 `fail_history.json` 读上一轮 failed_scenarios；fail_history 缺失/损坏按「上一轮签名未知」处理（不提前升级，保守走计数上限）；比较在内存完成，无新持久化文件

## 3. judge 生命周期预算隔离

- [ ] 3.1 `core/state_machine.py` 新增字段常量 `_judge_inconclusive_dispatches` / `_in_inconclusive_reverify` 并入生命周期注释段（与 `_judge_rerun_count` 同生命周期：verified 落定清零）；`core/pm_engine/verification/verdict_evidence.py` verified 清零点（既有 `_judge_rerun_count` 归零处）扩展为三字段一并清零/清除
- [ ] 3.2 `escalation.py` 两处 inconclusive 处置点置旗标 `_in_inconclusive_reverify=True`；judge 申报非全 env 结论处（bug-found 路由 / verified 放行 / scenario-repaired 重入决策点）清旗标——收口选单一助手函数避免多点漂移
- [ ] 3.3 `core/pm_engine/verification/judge_gate.py` `_judge_dispatch_gate` 计数分流：读旗标置位 → 递增 `_judge_inconclusive_dispatches`（不递增 `_judge_rerun_count`），该计数器达上限（= `inconclusive_max_attempts` 配置值）时复用 `_judge_round_escalate` 同款人工升级停车；旗标未置 → 既有 `_judge_rerun_count` 语义零变化；`_judge_rerun_count` helper 的冻结早退语义不受影响
- [ ] 3.4 `core/dashboard/data/admin_actions.py` `reset_verification` 清零清单追加 `_judge_inconclusive_dispatches` / `_in_inconclusive_reverify`（对齐既有计数清理段形态）

## 4. choices 注册与 grant_env_exemption 执行器

- [ ] 4.1 `core/dashboard/data/adjudication_choices.py` 注册 `inconclusive_loop` 选项集（按序）：`grant_env_exemption`（「授予 env 豁免」：落 DISPOSITION 放行记录 + 重置验证，下轮 verified 合法生效带豁免回链）/ `_MANUAL_FIXED_REVERIFY`（复用共享常量）/ `_ABANDON`（复用）；消费通道为 ESCALATION（前端告警区下拉），不加入 `SIGNAL_CHANNEL_SIGNAL_TYPES`
- [ ] 4.2 `core/dashboard/data/admin_actions.py` 新增 `_exec_grant_env_exemption(project_root, spec, note)`：经 AdminStore 写 kind=DISPOSITION（signal_type=inconclusive_loop、result 显式 env 豁免放行语义、note 落人工审计文本、幂等锚点对齐既有 disposition 形态）+ 调 `reset_verification` 复用既有清计数/清验证进度路径；DISPOSITION 写失败不执行重置（fail-closed，防「重置了却没放行」的死循环复发）；`execute_adjudication_choice` 补 action 映射
- [ ] 4.3 `core/alert_lifecycle.py` `build_trigger` 闭环枚举确认：inconclusive_loop 的自动闭环条件不注册（人工豁免不可自动判定），仅人工处置闭环——若枚举缺省即保守不注册，则此处仅补注释说明
- [ ] 4.4 `docs/help/06-governance.md` 裁决选项段追加 inconclusive_loop 三选项语义与「授予豁免后 verified 链路」说明

## 5. 配套测试

- [ ] 5.1 新建 `tests/test_env_exemption_exit_reachability.py`（假 notifier/store 注入，MUST NOT 真调网关，配置源 patch 不落 HOME）：级二首次命中即升级（SIGNAL + 人工告警各一条、无 verifier 入队、attempts 停 1）；grant_env_exemption 执行（DISPOSITION 落库 + 验证重置 + 幂等）；DISPOSITION 写失败时 fail-closed（不重置）；握手守卫查得新鲜放行记录放行 verified 链带回链
- [ ] 5.2 同文件续：级一签名一致提前升级（上一轮同签名 → 不重验直接 SIGNAL）；签名变化继续重验；fail_history 缺失保守走计数上限；重验上限缺省 2
- [ ] 5.3 同文件续：预算隔离（旗标置位时 gate 递增 `_judge_inconclusive_dispatches` 且 `_judge_rerun_count` 不变；独立计数器到顶升级停车；非全 env 结论清旗标恢复正计；verified 落定三字段清零；reset_verification 清新字段）
