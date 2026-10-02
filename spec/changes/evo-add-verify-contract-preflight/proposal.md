# add-verify-contract-preflight

## Why

fenix-init 对每个新项目写入全注释 verify.yaml 模板（fenix-init:145-155；core/verify_contract_template.yaml 非注释行数为 0），而框架对「文件存在但解析为 None」在验证消费期 fail-fast（core/verify_contract.py:2035-2038），对「文件缺失」反而放行（:2006-2007）。两者叠加的后果：每个新项目的首个 spec 首次推进到验证段时必然卡 blocked，等待自主起草解锁。实证（potplayer-base 首个 spec cimbar-airgap-transfer，2026-10-02）：verify_contract_missing 信号 6218aba50ea5（06:35:16Z）→ 处置完成 07:01:01Z，spec 卡 blocked 约 26 分钟、23 条验证场景 0 执行，并连发 2 个 Administrator run（admin-cimbar-airgap-transfer-1790922917 / -1790923106）才落位契约（提交 c7131a5），其中先派 run 整轮空转。契约起草本可与规划/实现阶段并行，现被串行压在验证消费点上，每个新项目都重复支付这笔端到端延迟与重复 run 成本。

## What Changes

- core/verify_contract.py 新增只读判定函数：区分「契约文件缺失（合法回退，不触发）」与「契约文件存在但不可解析（模板态/损坏态，可前置触发）」，复用既有 `_load_verify_contract_with_raw`，不新增第二套解析。
- core/admin_monitor.py 新增周期检测器 `_detect_verify_contract_unresolved` 并挂入 `_detect`：当存在 ready/implementing 状态的 spec 且契约处于模板态时，前置写既有 `verify_contract_missing` 信号（含 spec 名与「前置预检」description），把契约起草从验证消费点前移到实现阶段并行完成。
- 不新增信号类型、不新增去重机制：完整复用 STORED_SIGNAL_TYPES 注册、PREPROBE_SIGNAL_TYPES 满足即免唤起探测、同 spec 信号节流与 autodraft 起草指引。

## Capabilities

- verify-contract-preflight

## Impact

- 改动面：core/verify_contract.py（+1 只读判定函数）、core/admin_monitor.py（+1 检测器及 `_detect` 汇总挂载）、tests/test_verify_contract_template_preflight.py（新增）。
- 风险与边界：(1) 信号重复——检测器只在 ready/implementing 触发，testing 及之后由既有消费期 fail-fast 覆盖（pipeline.py:2850-2894），两段互斥；同 spec 节流防巡检重复写。(2) 语义边界——文件缺失不触发，维持 ADR-080「缺失=合法无契约回退」的既定语义，只收窄「模板态文件挂着却从未裁决」的缺口。(3) 信号写提前不改变起草质量门——起草仍须过三段自证全通才落位。