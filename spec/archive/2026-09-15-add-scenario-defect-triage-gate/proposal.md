# Proposal: add-scenario-defect-triage-gate

## Why

add-spec-status-modal-budget 事故（2026-09-09/10，三轮实现累计 $119.37 + replan $22.55 + judge 重试 $9.27）暴露场景缺陷处置链的双层缺口：①planner 跨轮 replan 原样写回已裁决场景（含 seed），上一轮的环境假设（字面端口 :57905、跨轮残留状态）随场景集带进新一轮，seed 夹具实际未建成 → 19 个下游场景连锁失败；②judge 将 19 个全部归 test-defect 却申报 bug-found（未走已有的 scenario-repaired 原地修复通道），而框架 bug-found → 打回 implementer 的路由**完全不读 bug 清单的 classification**——100% 场景缺陷的清单照单消耗了两个实现轮（$88+）整轮修场景文件。judge prompt 明文「场景文件问题派 implementer 是错误路由」但无框架侧兜底，prompt 约定已被实证不可靠。

## What Changes

- **场景静态缺陷扫描（纯 Python，零 token，fail-open）**：场景执行前对场景集做模式表驱动的静态扫描（初始模式：cli/api 场景 command/stdin 中字面端口 ≠ 本轮 serving 端口（跨轮端口残留，须用 FENIX_VERIFY_PORT/FENIX_VERIFY_BASE_URL）、web 断言/选择器中双汉字文本（antd autoInsertSpace 渲染为「X X」）、navigate URL 字面端口 ≠ serving 端口）。findings 结构化落盘 `.fenix/verify-progress/<spec>/scenario_static_findings.json` 并注入 judge prompt 定向情报段。**只做情报不拦截执行**——执行证据是 judge 修复的依据。
- **bug-found 分类改道门（框架侧机械判定，零 token）**：judge 申报 bug-found 后、打回 implementer 前，读 report.json 场景 classification 分布——failed 场景全部显式 `test-defect`/`flaky` 且 `product-bug=0`（未分类 None 视为不满足，保守不改道）时，拒绝打回 implementer，定向重派 judge 一次（prompt 附强制指令：清单全部场景缺陷，按原地修复协议申报 scenario-repaired，禁止申报 bug-found）。改道后仍 bug-found 且 product-bug=0 → 升级人工（告警附清单与 judge 两轮行为记录），不再消耗实现轮预算。
- **judge prompt 路由约定强化**：把「场景文件缺陷 → 原地修复（scenario-repaired）」从文末协议段前移至 test-defect 分类定义处；显式声明「修复已裁决场景（含跨轮写回场景）合法，冻结 diff 记账保护（无理由移除才确定性补齐），不视为冻结违规」；收到静态扫描情报段时对已检出场景 MUST 先修已知缺陷再裁决。

## Capabilities

### New Capabilities
- `scenario-static-defect-scan`: 场景集静态缺陷扫描——模式表驱动（跨轮端口残留/双汉字文本选择器等已知模式，模式表可扩展）、执行前扫描、findings 落盘与 judge prompt 注入、fail-open 边界（扫描异常不阻断验证）。
- `scenario-defect-reroute-gate`: 场景缺陷改道门——bug-found 采纳前的 classification 分布判定（全显式 test-defect/flaky 且 product-bug=0 才改道）、定向重派 judge 协议、改道预算与升级路径、judge prompt 场景修复路由约定（scenario-repaired 优先级 + 已裁决场景修复合法性）。

### Modified Capabilities

（无——judge-scenario-repair 通道（1c8f7820 裁决效率治理）系原地修改未落 spec，归档库中无对应 capability 定义；本次全部为新增能力，不改变既有 requirement 语义。）

## Impact

- **代码**：
  - `core/verify_engine/scenario_static_check.py`（新建：模式表扫描器）；
  - `core/pm_engine/verification.py`（bug-found 分支插入改道门、扫描挂点于 `_apply_scenario_freeze` 后）；
  - `core/agent_runner/prompt_builder.py`（新增 `_scenario_static_findings_section` 动态段、planner-judge 分支挂载；改道门定向指令段）；
  - `agents/planner-judge.md`（路由约定前移与合法性声明）。
- **影响的行为**：bug-found → implementer 打回的触发条件（新增改道门前置判定）；judge prompt 构成（新增情报段）；场景集写回后的扫描时机。不改场景 schema、不改 scenario-repaired 既有预算语义（`_SCENARIO_REPAIR_MAX_ROUNDS` 2 轮沿用，改道重派计入该预算）。
- **不受影响**：场景写端 schema 门、replan 消费硬门（fix-frozen-scenario-orphan-reservoir 语义原样）、全绿快道、verified 洗白门禁。
- **与 add-verdict-credibility-gate（已立项）互补不重叠**：该 SPEC 管「归因是否有据」（证据分级、防假归因），本 SPEC 管「归因后走哪条路」（分类→路由）。改道门的保守判定（未分类不改道）与其「推测级归因不得打回」同源。
- **风险**：judge 将真 product-bug 误标 test-defect 时改道门会延迟真 bug 修复一轮（改道 → judge 修场景重验 → 仍失败再裁决 → 正常放行或升级人工），有恢复路径不静默吞——宁可多一轮重验不可烧实现轮修场景。
