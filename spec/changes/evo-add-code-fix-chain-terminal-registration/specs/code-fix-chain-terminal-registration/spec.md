# 能力：code-fix 修复链终态收口登记（code-fix-chain-terminal-registration）

## 目的

code-fix 修复链以 disabled 终态收口时，在告警与待办面留登记，消除「链已终止、无人知晓」的静默悬置面；重新触发后再次停摆能再次登记。

## Requirements

### Requirement: disabled 终态收口登记

修复链 checkpoint 收口为 disabled 终态（phase=blocked、reason=disabled、running=false）时，MUST 同时落一条 admin 告警与一条 todo 待办登记，内容含终态原因、剩余未修复条数（当前台账 open 数；读台账失败回退进度 total-done）与重新触发入口提示。告警 severity 为 warning。批在飞期间的 disabled 提示写点（running 仍为 true）不属终态收口，MUST NOT 登记。登记任一通道失败 MUST NOT 阻断终态进度落盘或改变 checkpoint 返回值（fail-open，warning 留痕）。

#### Scenario: 总开关关闭触发登记

- WHEN 修复链 live 运行中总开关被置为关闭，checkpoint 判定 disabled 终态（批不在飞）
- THEN admin 告警面落一条 warning 级告警，todo 待办面落一条登记，两者均含剩余条数（当前台账 open 数）、终态原因与重新触发提示

#### Scenario: 批在飞不登记

- WHEN 总开关关闭后批仍在飞，checkpoint 仅写 reason=disabled 的提示性进度（保留 running=true）
- THEN 不落告警与待办登记

#### Scenario: 登记通道失败不阻断终态

- WHEN 终态进度落盘成功但告警或 todo 写入抛异常
- THEN checkpoint 仍返回 `{triggered: false, reason: "disabled"}`，终态进度保持，仅 warning 留痕

### Requirement: 同一 disabled 期去重

同一 disabled 期（未重新触发前）重复经过 checkpoint MUST NOT 重复落登记。判重谓词 MUST 同时满足 running 为 false、phase 为 blocked、reason 为 disabled；MUST NOT 仅以 reason 为 disabled 判重（在飞提示写点同样写该 reason），MUST NOT 以「同 signal_type 未处置信号在场」判重（会吞掉重新触发后的新登记）。

#### Scenario: 重复 checkpoint 不重复登记

- WHEN disabled 终态已登记后，链再次经过 checkpoint
- THEN 不产生第二条告警或待办登记

### Requirement: 重新触发后去重窗口重置

人工经 dashboard 端点重新触发链（override_enabled 路径）后链恢复 live（进度写回 running=true），去重窗口重置——链此后再次撞 disabled 时 MUST 落新登记。

#### Scenario: 二次 disabled 再登记

- WHEN 链重新触发运行后再次因总开关关闭撞 disabled 终态
- THEN 落新的一条告警与待办登记
