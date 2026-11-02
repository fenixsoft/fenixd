## Why

观测实证与机制核对暴露两个观测缺陷：(1) `aggregate_org` 的「已归档 SPEC 名下 run 全窗剔除」规则将吞蒸馏 run——蒸馏 run 的 spec 段由派发名直出（core/knowledge.py:1627 run_id 中段 = archived_names[0]），push 触发时代（move-distill-trigger-to-push 1.1；其 1.2 移除归档挂载后为唯一生产触发）以 `spec/changes/<名>` 原始 SPEC 名派发（engine.py:3409），run_spec_part 剥段结果与 STATE.archive.md 清单键（原始名）全等，SPEC 随后归档（时效归档/软删除/手动）即被剔除（command_center.py:545 全等匹配、先于窗口过滤，全部窗口生效）——时效归档最终归档一切 SPEC，稳态下知识蒸馏卡趋恒 0。形态边界：归档触发时代历史产物中段为带日期前缀归档目录名（knowledge-distiller-2026-11-02-fenix-prototype-…），与原始名清单键形态错位而偶然漏剔（add-distill-run-artifacts D3 锁定测试所锁即该偶然逃逸；实测 aggregate_org window=all 对两批真实产物计数 runs=2，本草案初稿引「fenix-prototype 批卡片仍 0」为证不成立，已更正为机制归因）；(2) 蒸馏合成产物批中间无写入，spawn 超过 `_RUN_STALE_SECONDS`（1800s）即被读侧判 stale、被 retention 提前移走，批收尾的 error 终态行 fail-open 写空——超时失败在观测上变 stale，成功率分母漏计（fix-frozen-scenario 批实证）。

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
