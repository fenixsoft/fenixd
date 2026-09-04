# Tasks: add-verdict-evidence-taxonomy

实现依据（实施 agent 必读）：
- 能力定义 `specs/verdict-evidence-taxonomy/spec.md`；设计决策 design.md D1-D5
- 裁决 prompt 与输出解析：`.fenix/core/agent_runner.py`（planner-judge）
- 裁决采纳点与升级告警：`.fenix/core/pm_engine.py`（验证结果处理、`_send_human_escalation_alert`）
- 消费方兼容：`.fenix/core/dashboard/data.py` `parse_verdict`、`.fenix/core/verify_report.py` 合成器
- 真实夹具：`.fenix/verify-progress/v2-config-page/report.json`（11 warning / 3 failed 无证据的现状样本）

## 1. 分类与证据校验

- [x] 1.1 裁决 prompt 更新：非 PASS 场景强制输出 classification（四选一）与 evidence（失败断言/截图/首败步骤），prompt 内含分类定义与映射约束
- [x] 1.2 新增 `.fenix/core/verdict_check.py`：字段齐全性、取值合法性、分类-状态映射校验；不合规走既有裁决重试一次，二次失败 → blocked-env + 告警
- [x] 1.3 采纳处映射强制重写：product-bug/test-defect → failed（含 warning 误挂的修正与报告标注）

## 2. warning 收敛升级

- [x] 2.1 `.fenix/verify-progress/<spec>/warning_streaks.json` 侧车：裁决采纳处更新连续计数，PASS/failed 清零
- [x] 2.2 连续 2 轮 warning → `_send_human_escalation_alert(signal_type="warning_stale_triage")`（含 spec、场景、轮次、证据摘要）+ 下一轮 planner prompt 优先复核注入

## 3. 消费方兼容

- [x] 3.1 `parse_verdict` 与合成器处理新字段（无字段时走旧逻辑）；合成报告引用 evidence 而非重复渲染

## 4. 单元测试

- [x] 4.1 覆盖：分类缺失→重试→blocked-env；product-bug 误挂 warning 被强制 failed；证据落盘；连续 2 轮 warning 升级告警与复核注入；旧格式 report.json 兼容解析
- [x] 4.2 用 v2-config-page 真实 00:14 报告作夹具：11 个 warning 全部产出分类与证据后，其中属于产品缺陷的被强制 failed

## 5. 验证与打包

- [x] 5.1 运行 `python3 -m pytest .fenix/tests/ -v` 确认无回归
- [x] 5.2 执行 `bash scripts/package.sh` 生成最新扩展包

## 验证修复（第 1 轮失败）

- [x] 阅读 `spec/changes/add-verdict-evidence-taxonomy/verification-report.md`，定位「真实产品 Bug」并修复
- [ ] 修复后重跑验证确认通过
