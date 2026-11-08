# 实现期验证契约预检降噪

<!-- knowledge: capability=verify-contract-precheck-noise-reduction rev=1
     sources=spec/changes/add-provider-validation-alert-governance -->

前置预检窗口内的 verify_contract_missing 信号按窗口分级治理：实现窗口（ready/implementing）info 级只沉淀不召唤、同 spec 一次性，验证消费窗口维持 major 召唤语义——首个 SPEC 实现期不再被「契约本就尚未起草」的周期信号淹没。

## 规则

- **分级状态驱动**：前置预检窗口（spec 处 ready/implementing）内契约模板态信号一律 info 级，只沉淀告警账本、不召唤 Administrator（info 不进人工唤起面）；文案保留「spec 仍在实现流程中，起草落位即可，勿复位 spec 状态」指引。
- **同 spec 一次性**：去重键 signal_type:spec，判据持久化随告警账本——同 spec 存在未处理同型记录即跳过成条，daemon 重启不重发；记录被人工处置后允许再次提示（去重态复位的人工出口）。
- **验证窗口恢复 major**：spec 离开前置窗口进入验证消费段后契约仍未裁决的，按 verify_contract_missing 的 major 语义发信号并召唤 Administrator（消费期通道承接）；前置窗口与消费窗口互斥不双发，离开前置窗口时一次性去重态随之失效。
- **一次性判定单判据**：未处理同型记录存在性查询是唯一去重判据（同 spec 严格相等，含 None==None 的 daemon 级形态），不另建进程内去重结构。
- 契约已裁决（可解析为顶层映射）零信号；免唤起前置探测的能力覆盖口径与消费期通道语义均不受本治理影响。

## 代码锚点

- 分级与一次性判定：`core/admin_monitor.py`（契约前置检测器 info 分支与去重）
- 去重判据单源：`core/admin_store.py`（has_unhandled_signal）
- 守卫测试：`tests/test_contract_precheck_noise.py`

## 溯源

- 2026-11-08 add-provider-validation-alert-governance（spec/changes/add-provider-validation-alert-governance/） — 新建本能力页：前置预检窗口信号降 info 级 + 同 spec 一次性去重（持久化随账本、重启不重发），验证消费窗口 major 召唤语义不变
