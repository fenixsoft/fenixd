# tasks — judge 原地修复写回受理门

## 1. 受理预检门（fail-closed 整批校验）

- [x] 1.1 `core/pm_engine/verification/pipeline.py` `_handle_scenario_repaired`：在受理门
  （耗尽持久态拒收）之后、`_apply_scenario_freeze` 之前插入受理预检——读
  `test_scenarios.json` 原始 JSON 数组（复用冻结复用读点的解析容错口径），调
  `validate_scenario_dicts`；错误清单非空即进入拒收分支（design D1），文件不存在/
  解析失败维持既有 corrupt → env_blocked 语义不变
- [x] 1.2 拒收分支接线（design D2）：`update_spec` error 留痕（含「写端校验失败拒收」
  文案 + 错误清单前 3 条）、spec 保持 testing、`_record_repair_claim(rejected=True)`、
  **返回 True**（MUST NOT 返回 False——防穿透守卫假收敛为 verified）；错误清单全文
  经既有重派上下文注入链回传下轮 judge

## 2. 成对落盘核对

- [x] 2.1 核对预检通过后受理采纳路径的备份写点（`core/pm_engine/verification/scenario_gate.py`
  `_scenarios_full.json` 更新点）在「预检通过 ⇒ 全批合法」前提下已满足成对纪律
  （同版本戳、先 `_scenarios_full` 后 `test_scenarios`）；已满足则补回归锚点锁行为，
  未满足则按 `_exec_revise_scenario_reverify` 步骤 5b 形态改写点
  （核对结论：主路径写序已自然满足；声明移除轮与补齐分支存在撕裂窗口——judge
  受理路径以 `pair_writeback=True` 走成对改写点，planner 路径零变化）

## 3. judge 协议模板同步

- [x] 3.1 `agents/planner-judge.md` 原地修复协议段追加：写回将按结构校验门整批校验
  （含 per-kind 词表），任一条非法即拒收本轮修复、按逐条错误清单重修；申报
  `scenario-repaired` 前自校验义务；话术对齐 admin 修复约束段风格

## 4. 测试

- [x] 4.1 新建 `tests/test_judge_repair_writeback_gate.py`：
  - 词表违规条目（`run` 步骤入 api 场景）→ 本轮修复被拒收：error 留痕含错误清单、
    spec 保持 testing、`scenario-repaired` 不重入执行、记账 rejected=True；
  - 全部合法 → 正常受理进入既有冻结/重入流程（行为零变化锚点）；
  - 受理采纳后 `test_scenarios.json` 与 `_scenarios_full.json` 成对同版本戳；
  - 与预算交互：耗尽持久态下预检拒收路径不改变既有「无修复纯归因模式」语义
- [x] 4.2 测试隔离用户级配置与 `.fenix` 真实目录（夹具用 tmp_path，不触碰现存
  verify-progress 数据）；planner 收编路径既有测试全绿（剔除继续语义零变化锚点）

## 5. 收尾

- [ ] 5.1 全量测试通过、merge-back 落地后重启 daemon 生效
- [ ] 5.2 验证报告记录：拒收分支与既有空集拒绝/预算耗尽拒收三分支的报错文案区分度
  （Dashboard/CLI 直读 error 字段可观测）
