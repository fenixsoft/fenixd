## Deliverables

```yaml
- path: core/verify_engine/scenarios.py
  kind: modify
- path: core/verify_scenarios.py
  kind: modify
- path: core/pm_engine/verification.py
  kind: modify
- path: core/agent_runner/prompt_builder.py
  kind: modify
- path: tests/test_frozen_scenario_reservoir.py
  kind: new
- path: .fenix/verify-progress/add-verify-contract-autodraft/scenarios.json
  kind: reference
```

## 1. 结构校验函数单一来源

- [x] 1.1 在 `core/verify_engine/scenarios.py` 新增 `validate_scenario_dicts(raw: list) -> list[str]`：输入 dict 列表，复用 `TestScenario.from_dict` + `validate()` 返回逐条错误清单；`load_scenarios` 内部改为调用它（读端行为零变化）
- [x] 1.2 回归确认 `load_scenarios` 既有报错格式（「场景文件包含 N 个错误」）不变，既有测试全绿

## 2. 写端 schema 门接入三文件写入点

- [x] 2.1 `core/verify_scenarios.py` `save_scenario_set`：写回前过 `validate_scenario_dicts` 等价校验（ScenarioEntry → dict 形态），坏条目剔除 + WARNING/ERROR 留痕（id 清单），合法部分照常落盘
- [x] 2.2 `core/pm_engine/verification.py` `_apply_scenario_freeze` 收编写回与补齐写回：写入前过同源校验，坏条目剔除留痕，不整批拒绝
- [x] 2.3 `_scenarios_full.json` 备份更新点（verification.py）：仅当 planner 产出全部合法时更新备份；含非法条目时保留旧备份并 WARNING 留痕
- [x] 2.4 剔除条目写入验证报告场景集变更小节（复用 `render_change_section` change_lines），剔除数超本轮 20% 时 ERROR 升级

## 3. 补齐占位改弃场景

- [x] 3.1 `_apply_scenario_freeze` 补齐路径：备份缺定义的条目不再写 `{"id","description"}` 占位，登记「定义不可恢复」剔除清单（id 列表）进日志与 change_lines，验证以剩余场景继续
- [x] 3.2 备份有完整定义的缺失场景维持现有补回行为不变

## 4. 持久化集加载净化

- [x] 4.1 `core/verify_scenarios.py` `load_scenario_set`：读入时剔除无 `kind` 条目，WARNING 留痕剔除 id 清单；只影响内存集合，不改写 scenarios.json 文件
- [x] 4.2 确认 diff 基线以净化后集合为准：孤儿条目不再产生「无理由缺失」假阳性

## 5. 重跑消费硬门与分级升级

- [x] 5.1 `core/pm_engine/verification.py` 场景验收失败比对点：错误清单与上轮相同或为上轮超集时判定「planner 未消费反馈」，不再 continue 重跑，直接走 `_escalate_env_blocked`（title=场景计划争议）；错误数减少或主体变化时维持预算内重跑
- [x] 5.2 `_escalate_env_blocked` 冻结转人工告警追加最近一次 planner run 成本（STATE `_cost_usd`/`_tokens_in` + run 记录时长），处置选项文本标注「删除冻结集重新出题将重付出题成本」
- [x] 5.3 保持冻结复用路径 corrupt 升级与连续 2 轮冻结阈值语义不变

## 6. admin 修复约束

- [x] 6.1 `core/agent_runner/prompt_builder.py` admin 处置指令段追加：修复写回必须通过结构校验（被门拒绝时按逐条错误清单重修）；`test_scenarios.json` 与 `scenarios.json` 同源坏条目必须同步清理，处置结果报告两文件状态

## 7. 测试

- [x] 7.1 新建 `tests/test_frozen_scenario_reservoir.py`：补齐占位改弃场景（备份缺定义不写占位/有定义正常补回）、写端门拦截（save_scenario_set 与补齐写回拒绝非法条目且合法部分落盘）、加载净化（无 kind 条目剔除+告警+不改文件）、消费硬门（错误清单相同拒绝重跑走升级/错误减少允许重跑）
- [x] 7.2 测试隔离用户级配置与 `.fenix` 真实目录（夹具用 tmp_path，不得触碰现存 verify-progress 数据）

## 8. 收尾

- [x] 8.1 全量测试通过、merge-back 落地后重启 daemon
- [x] 8.2 清理 `.fenix/verify-progress/add-verify-contract-autodraft/scenarios.json` 现存 7 条无 kind 孤儿残留（运行时操作，双文件一致性核对）
