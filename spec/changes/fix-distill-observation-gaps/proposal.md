## Why

add-distill-run-artifacts 端到端实证暴露两个观测缺陷：(1) `aggregate_org` 的「已归档 SPEC 名下 run 全窗剔除」规则误吞蒸馏 run——蒸馏 run 的 spec 段按定义恒为已归档 SPEC 名（蒸馏恰发生在归档/交付之后），导致指挥中心「知识蒸馏」卡在有真实完成批的情况下恒显 runs=0（fenix-prototype 批 11:44 完成、get_runs 正确返回 done，卡片仍 0）；(2) 蒸馏合成产物批中间无写入，spawn 超过 `_RUN_STALE_SECONDS`（1800s）即被读侧判 stale、被 retention 提前移走，批收尾的 error 终态行 fail-open 写空——超时失败在观测上变 stale，成功率分母漏计（fix-frozen-scenario 批实证）。

## What Changes

- **归档清单剔除豁免蒸馏车道**：`aggregate_org` 剔除条件对 `knowledge-distiller` lane 放行（蒸馏 run 是现役知识运营活动，非归档 SPEC 的完结历史实现过程）；其余 lane 剔除语义不变。注意实现顺序：现行代码先剔除（:545）后归一 lane（:548），豁免须在剔除前先取 raw agent_type 判断。
- **蒸馏批心跳保活**：`_run_batch` spawn 等待期间由后台线程定期向产物追加非终态心跳事件行（间隔安全低于 1800s stale 阈值），批收尾 join 停线、终态行覆盖末行——长跑批不再被判 stale、终态如实落盘。心跳写 fail-open（OSError 静默，与既有产物写口径一致）。

## Capabilities

### New Capabilities
- `distill-observation-fixes`: 蒸馏 run 的聚合可见性豁免与批心跳保活契约。

### Modified Capabilities
<!-- 无：distill-run-artifacts（spec/changes/add-distill-run-artifacts，活跃）的
     Requirement 锚定批产物生命周期语义，本变更不改变其批=一 run/终态/fail-open
     契约，心跳是新增保活行为（新能力承载）；聚合剔除是 command_center 既有
     行为的豁免例外（新能力承载）。 -->

## Impact

- `core/dashboard/data/command_center.py`（aggregate_org 剔除豁免，单点条件）
- `core/knowledge.py`（`_run_batch` 心跳线程，spawn 等待期保活）
- `tests/test_command_center_aggregation.py`（豁免用例+非蒸馏 lane 剔除不回归）
- `tests/test_knowledge_distill_run_artifacts.py`（心跳用例：长跑不 stale、终态覆盖、fail-open）
- 读侧零改动：classify_run 对未知非终态 type 判 running（心跳语义正确）、终态行覆盖末行判定不变
