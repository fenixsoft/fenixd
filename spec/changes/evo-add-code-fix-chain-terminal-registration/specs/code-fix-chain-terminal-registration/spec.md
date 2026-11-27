# 能力：code-fix 修复链终态收口登记（code-fix-chain-terminal-registration）

## 目的

code-fix 修复链以 disabled 终态收口时，在告警与待办面留登记，消除「链已终止、无人知晓」的静默悬置面；重新触发后再次停摆能再次登记。

## Requirements

### Requirement: disabled 终态收口登记

修复链 checkpoint 收口为 disabled 终态（phase=blocked、reason=disabled）时，MUST 同时落一条 admin 告警与一条 todo 待办登记，内容含终态原因、剩余未修复条数（total-done）与重新触发入口提示。

#### Scenario: 总开关关闭触发登记

- WHEN 修复链 live 运行中总开关被置为关闭，checkpoint 判定 disabled 终态
- THEN admin 告警面落一条 warning 级告警，todo 待办面落一条登记，两者均含剩余条数与重新触发提示

### Requirement: 同一 disabled 期去重

同一 disabled 期（未重新触发前）重复经过 checkpoint MUST NOT 重复落登记。

#### Scenario: 重复 checkpoint 不重复登记

- WHEN disabled 终态已登记后，链再次经过 checkpoint
- THEN 不产生第二条告警或待办登记

### Requirement: 重新触发后去重窗口重置

人工经 dashboard 端点重新触发链（override_enabled 路径）后链恢复 live，去重窗口重置——链此后再次撞 disabled 时 MUST 落新登记。

#### Scenario: 二次 disabled 再登记

- WHEN 链重新触发运行后再次因总开关关闭撞 disabled 终态
- THEN 落新的一条告警与待办登记