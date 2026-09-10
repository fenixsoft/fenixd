## Deliverables

```yaml
- path: core/verify_engine/scenario_static_check.py
  kind: new
- path: core/pm_engine/verification.py
  kind: modify
- path: core/agent_runner/prompt_builder.py
  kind: modify
- path: agents/planner-judge.md
  kind: modify
- path: tests/test_scenario_static_check.py
  kind: new
- path: tests/test_scenario_reroute_gate.py
  kind: new
```

## 1. 静态扫描器模块（scenario-static-defect-scan R1/R3）

- [x] 1.1 新建 `core/verify_engine/scenario_static_check.py`：模式表驱动的扫描器主体（模式表 = 模块级数据结构：rule_id / 适用 kind / 匹配函数），初始三模式——①cli/api 场景 command/stdin 字面端口 ≠ 本轮 serving 端口（rule_id=stale_literal_port）、②web navigate URL 字面端口 ≠ serving 端口（rule_id=stale_navigate_port）、③双汉字文本选择器（rule_id=double_han_text_selector）；finding 结构含 scenario_id/rule_id/location/message
- [x] 1.2 实现 fail-open 边界：扫描任何异常记 WARNING 返回空 findings（不抛出）；serving 端口未知时端口比对类模式整体跳过（双汉字纯文本模式仍执行）
- [x] 1.3 扫描器单测 `tests/test_scenario_static_check.py`：跨轮端口残留检出、端口一致不误报、双汉字检出、恰 2 汉字边界（1/3 汉字不报）、异常 fail-open、端口未知时端口模式跳过

## 2. 扫描挂点与 judge 情报注入（scenario-static-defect-scan R2）

- [ ] 2.1 `core/pm_engine/verification.py`：在 `_apply_scenario_freeze` 完成后、阶段2 执行前调用扫描器，findings 覆盖写 `.fenix/verify-progress/<spec>/scenario_static_findings.json`（写失败仅 WARNING，不阻断）
- [ ] 2.2 `core/agent_runner/prompt_builder.py`：新增 `_scenario_static_findings_section`（读 findings 文件渲染定向情报段，逐条 scenario_id+缺陷说明+「修复属 judge 职责、先修已知缺陷再裁决」声明），挂载于 planner-judge 分支 `_verdict_cache_section` 之后、`_result_gate_section` 之前；findings 缺失/为空零注入
- [ ] 2.3 情报段注入单测（并入 tests/test_scenario_static_check.py 或独立用例）：有 findings 注入、空 findings 零注入、文件损坏零注入不抛

## 3. bug-found 分类改道门（scenario-defect-reroute-gate R1/R2/R3）

- [ ] 3.1 `core/pm_engine/verification.py` bug-found 分支（`_on_spec_bug_found` 调用前）插入改道判定：读 report.json 场景 classification 分布，failed 全部显式 test-defect/flaky 且 product-bug=0 才触发改道；None/未知值/含任一 product-bug 一律走现行路由；判定分布记日志留痕
- [ ] 3.2 实现定向重派 judge：`core/agent_runner/prompt_builder.py` 新增 `_scenario_reroute_directive_section`（上轮清单全场景缺陷统计 + MUST 申报 scenario-repaired 禁止 bug-found + 已裁决场景修复合法与冻结记账保护声明），改道触发时重派 planner-judge 并注入该段；重派后 scenario-repaired 沿用既有通道重入
- [ ] 3.3 改道预算与升级：定向重派计入 `_SCENARIO_REPAIR_MAX_ROUNDS`（与 scenario-repaired 重入共用 `_repair_depth` 计数）；预算耗尽仍 bug-found 且 product-bug=0 → 停止重派，`_send_human_escalation_alert` 升级人工（附失败清单/classification 分布/judge 各轮申报记录），spec 保持 testing；确认改道路径不触碰 impl_run_budget 计数
- [ ] 3.4 改道门单测 `tests/test_scenario_reroute_gate.py`：全 test-defect 触发改道且不打回 implementer、含 product-bug 不改道、None 保守不改道、改道后 scenario-repaired 正常重入、改道后 bug-found 含 product-bug 正常派发、预算耗尽升级人工、impl_run_budget used 不变

## 4. judge prompt 路由约定修订（scenario-defect-reroute-gate R4）

- [ ] 4.1 修订 `agents/planner-judge.md`：test-defect 分类定义处（`test-defect` 枚举行附近）内联「场景文件缺陷 → 原地修复」路由指引——根因在场景文件本身（{scenarios_path}）而非 tests/ harness 代码时 MUST 申报 scenario-repaired、MUST NOT 写入 bug 清单走 bug-found；显式声明修复已裁决场景（含跨轮写回场景）合法、受冻结 diff 记账保护（无理由移除才确定性补齐）、不视为冻结违规；文末协议段保留细节不删除
- [ ] 4.2 prompt 构建回归核对：planner-judge prompt 含新指引、其余 agent 类型 prompt 逐字节不变（模板改动不外溢）

## 5. 回归与收尾验证

- [ ] 5.1 全量单测回归（pytest tests/），确认既有验证链用例零回归
- [ ] 5.2 用 add-spec-status-modal-budget 事故现场残留场景集（.fenix/verify-progress/add-spec-status-modal-budget/test_scenarios.json，含 :57905 跨轮端口与双汉字样本）做真实数据冒烟：扫描器产出预期 findings、改道判定对当轮 report.json 输出符合预期分布统计
