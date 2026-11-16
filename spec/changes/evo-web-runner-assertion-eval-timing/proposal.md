# Proposal: web-runner-assertion-eval-timing

## Why

验证引擎 web_runner 的断言批后置统一求值设计（core/verify_engine/web_runner.py:393-437，:435 后置求值行）使所有「导航进会话视图」类场景的 no_click_interception 交互断言在错误视图下求值：trial click 延至断言批时刻才执行（core/verify_engine/assertions.py:429），此时应用页已被 show('session') 隐藏，not visible 判定来自非遮挡分支且无视图状态快照留证。judge_attribution.json 三案例互证（web-token-url-autofill-persist-clear、web-fullsession-apps-hud、web-profile-custom-tier——末例为 2026-11-12 07:15:26 冻结轮唯一实质失败）。误报跨轮再生 3 例（11-11 15:00 → 11-12 05:43 → 07:15），逐轮各浮现一个、逐场景补丁修法（whack-a-mole）被 judge 修复记录印证；NCI 类直接触发冻结 1 次、耗 rerun 修复轮≥3；web_runner.py 末次提交 2026-11-03 早于全部事件，缺口在 HEAD。现集 10/34 场景 NCI 已锚 #connect-btn 规避（隐式依赖末步回连接页），5 个深入会话视图场景仍带 NCI 残余风险。

## What Changes

- 断言求值时机分层：web_runner 断言求值计划按断言类型分桶——no_click_interception 等交互型断言绑定目标步骤上下文（步骤执行后即时求值或视图切换感知时机）；no_console_error 等流程级断言保持既有后置统一求值语义不变。
- 误报归因快照：assertions 的 trial click 与 not visible 失败分支附求值时刻视图状态快照（当前可见视图、目标元素所在视图、可见性判定依据），使 judge 能区分「被遮挡」「随视图切走」与「场景真实缺陷」。
- 场景文件零改动受益：求值时机由引擎按断言类型自动分层，无需逐场景补断言落点。

## Capabilities

### New Capabilities

- `web-runner-assertion-eval`: 交互/流程级断言的求值时机分层语义与交互断言失败载荷的视图快照归因。

### Modified Capabilities

（无——改动收敛在验证引擎 runner 求值编排与断言失败载荷两个文件）

## Impact

- 代码：core/verify_engine/web_runner.py（求值计划分层）、core/verify_engine/assertions.py（失败载荷快照）；tests/test_web_runner_assertion_eval_timing.py（新建）。
- 兼容性：流程级断言求值结果与现状一致；既有场景文件无需修改；已锚 #connect-btn 规避的场景行为不变（其断言在新时机下同样求值且仍通过）。
- 风险面：交互断言提前求值可能在其目标步骤尚有后续副作用时误判——以「绑定目标步骤完成点」而非步骤中间态收紧；快照取 DOM 摘要不上截图，控制体积。