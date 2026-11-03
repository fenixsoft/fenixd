# judge 裁决原地修复写场景文件后强制 validate_scenario_dicts 同门校验 + _scenarios_full.json 成对同步

## Why

本次直接根因：planner-judge 原地修复协议直改 test_scenarios.json 绕过写端门，一词表违规步骤（run 入 api 场景）+ 成对撕裂 + 端口漂移潜伏 2 轮才被验收拦住，连带烧掉 impl 修复轮与 admin 处置轮。成对写回与结构校验基建均已存在（_exec_revise_scenario_reverify 内置同款），只需让 judge 原地修复写回路径复用同一门（写后校验失败即拒收本轮修复+按既有打回语义处理），即可在落盘瞬间拦截而非两轮后验收期发现。

## What Changes

- **judge 原地修复受理入口加写端整批校验门**：`scenario-repaired` 申报受理时，框架对盘上场景集原始 JSON 数组先过 `validate_scenario_dicts`（与唯一结构化写端 `_exec_revise_scenario_reverify` 同源、fail-closed 整批拒绝）——任一条非法（含 per-kind 词表违规，如 `run` 步骤入 api 场景）即拒收本轮修复，按既有拒收语义处理（error 留痕、保持 testing、修复申报记账 rejected、不重入执行），逐条错误清单回传下轮 judge 重修；不再等验收期才拦。
- **受理采纳成对落盘**：预检通过后的写回按 `_exec_revise_scenario_reverify` 同款成对纪律同覆盖 `test_scenarios.json` 与 `_scenarios_full.json`（版本戳 + 先 `_scenarios_full` 后 `test_scenarios` 固定顺序），消灭「judge 只改 test_scenarios.json、旧备份对账回填旧定义」的成对撕裂窗口。
- **judge 协议模板同步**：`agents/planner-judge.md` 原地修复协议段追加写回门约束与申报前自校验义务，话术与 admin 修复约束段（`_admin_scenario_fix_constraints`）同风格。
- planner 产出收编路径的「剔除继续」语义、admin `revise_scenario_reverify` 通道、fast-track Phase 2 写入车道均**零变化**。

## Capabilities

### New Capabilities

- `judge-repair-scenario-writeback-gate`: judge 原地修复写回受理门——fail-closed 整批结构校验 + 成对落盘 + 既有打回语义接线。

### Modified Capabilities

（无）

## Impact

- `core/pm_engine/verification/pipeline.py`：`_handle_scenario_repaired` 受理路径加预检与拒收分支（复用预算耗尽拒收先例的接线形态）。
- `core/pm_engine/verification/scenario_gate.py`：受理采纳路径备份写点成对语义核对/补齐。
- `agents/planner-judge.md`：原地修复协议段约束追加。
- `tests/test_judge_repair_writeback_gate.py`：新增门行为测试。
- 既有机制交互：`_SCENARIO_REPAIR_MAX_ROUNDS` 预算口径不变；空集拒绝分支保留（预检通过后的防御性兜底）；`_record_repair_claim` 记账口径扩展 rejected 计数复用。

---

- 立项来源：Arbiter 调查（run_id=None，signature=add-knowledge-inbox-pipeline::verify_env_blocked，source=startup）
- 立项时间：2026-11-03T11:31:05.781961+00:00
