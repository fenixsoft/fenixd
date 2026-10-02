## Deliverables

```yaml
- path: core/agent_runner/provider_circuit.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: core/agent_runner/maintenance_runs.py
  kind: modify
- path: core/code_fix.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: tests/test_codefix_conn_error_cooldown.py
  kind: new
```

## 1. 失败分类与信封透传

- [x] 1.1 core/agent_runner/provider_circuit.py：新增 code-fix 车道本地连接类词表常量 CODE_FIX_CONN_ERROR_PATTERNS，覆盖「Can't reach the API server」「ENOTFOUND」形态并纳既有连接类形态（共享 SWITCH_ERROR_CONN_PATTERNS 实测对本死因文本漏判，且 MUST NOT 扩充它——该词表被 classify_switch_error（:418）消费、runner.py:2931 以此驱动 spec/impl 切链，扩充会改变 spec/impl 车道切换行为，违反 proposal Non-Goal）；不新增 stderr unrecognized_model 判据（定噪行）
- [x] 1.2 core/agent_runner/runner.py：异常挂载块（exc.api_timeout 同位置）新增连接类失败布尔挂载，判据 = terminal_reason=='api_error' + exit_code!=0 + result_text 命中连接类词表
- [x] 1.3 core/agent_runner/maintenance_runs.py：CodeFixResult 新增 conn_error 布尔与 result_text 字段，run_code_fix except 块抄传；api_timeout/salvage 语义不动

## 2. 车道冷却闸门

- [x] 2.1 core/code_fix.py：失败收尾分支读取 conn_error，命中时写 fix-progress.json 新字段 switch_cooldown_until（write_progress 合并写，持久化跨重启）
- [x] 2.2 core/code_fix.py：checkpoint 投递入口加「下一批不早于 switch_cooldown_until」守卫（覆盖 full scan/手动/自驱动三路）；冷却时长复用 PROVIDER_SWITCH_COOLDOWN_SECONDS，配置键 admin.code_review_fix.switch_cooldown_seconds 覆盖（仿 _orphan_grace_minutes 防御转换，0=关闭）
- [x] 2.3 core/code_fix.py：冷却触发/解除写 AdminStore SIGNAL 告警（signal_type=code_fix_switch_window_deferred，source=code-fix-lane，evidence 携带 run_id/死因/到期时刻），拒写留痕

## 3. 跨日同刻指纹升级

- [x] 3.1 core/admin_monitor.py：daemon_errors 指纹记账增加跨日同刻复发维度（同签名失败终态跨日差 24h±5 分钟），命中升级 escalation 且不受已知指纹 30 分钟冷却压制

## 4. 测试

- [x] 4.1 tests/test_codefix_conn_error_cooldown.py：分类判据单测——ENOTFOUND 文本命中、单轮超时文本不误判、成功信封（exit 0）与 stderr 定噪行均不触发
- [x] 4.2 tests/test_codefix_conn_error_cooldown.py：冷却闸门单测——冷却内置态后 checkpoint 拒投递、到期恢复投递、配置覆盖与非法值回退、持久化读回（重启后仍拦）
- [x] 4.3 tests/test_codefix_conn_error_cooldown.py：告警与跨日指纹单测——SIGNAL 告警字段断言、24h±5 分钟命中升级、10 分钟内同指纹不重复升级

## 验证修复（原地打回第 1 轮）

- [x] 先复核失败有效性：逐条核对 `spec/changes/evo-add-codefix-conn-error-cooldown/verification-report.md` 中失败场景的期望断言（状态字面量/选择器/前置数据）与产品实际行为是否相符——断言与产品不符属场景缺陷，修场景文件；确属产品行为不符才修产品代码（复核结论：BUG-01 属真实产品缺陷——spec R2 原文「0=关闭」，场景期望与 spec 相符，产品守卫却按残留 switch_cooldown_until 字面拦截）
- [x] 按复核结论修复：场景缺陷改场景文件，真实产品 Bug 改产品代码（core/code_fix.py checkpoint 冷却守卫复核 _switch_cooldown_seconds()：0=关闭时不拦残留态并清除、不写解除告警；tests/test_codefix_conn_error_cooldown.py 补 test_zero_config_bypasses_residual_cooldown；顺修 tests/test_code_fix.py::TestRegressionLockRoot 存量替身签名漂移 run_scope）
- [x] 修复后重跑验证确认通过（新套件 22 passed；相关回归 214 passed：test_code_fix/test_code_fix_item_level_progress/test_provider_circuit/test_code_fix_api_timeout_salvage/test_admin_dispatch_escalation；全量回归由验证链复跑）
