# Design: web-runner-assertion-eval-timing

## 现状与根因

core/verify_engine/web_runner.py:393-437 将断言批在全部 steps 执行完后统一求值（:437），trial click 亦延至断言批时刻（core/verify_engine/assertions.py:430）。导航类场景（如 wire-e2e 会话流、web-profile-custom-tier）中途经 show('session') 切换视图，交互断言求值时目标元素已不可见，not visible 走非遮挡分支且无视图证据——judge 只能逐场景补断言落点规避（现集 10/34 场景锚 #connect-btn），同类误报持续再生。

## 方案

- 求值计划分桶：web_runner 构建断言求值计划时按类型分桶——交互桶为第 2 层交互可用性类封闭枚举（no_click_interception / no_overlap / in_viewport / z_index_order，单源 `WEB_ASSERTION_LAYERS` layer=2，core/verify_engine/scenarios.py:612）；流程桶为其余全部断言，保持既有后置批。类型判定读断言声明，场景零改动、无新增断言字段。
- 交互桶求值窗口（视图切换感知）：逐步骤完成点探测各未决交互断言的目标元素可见性，于「目标元素仍可见的最后一个步骤完成点」即时求值（含 trial click）；目标元素全程不可见（真实缺陷面）回退既有后置时机求值并附视图快照。不采用「断言绑定目标步骤索引」变体：断言 schema 无步骤绑定字段（core/verify_engine/scenarios.py:1285 `Assertion` 仅 type/selector/label/expected/threshold/extra），且实测现集 10 条 NCI 选择器与场景步骤动作目标零重合（web-browser-client 语料，/root/cloud-phone/.fenix/verify-progress/web-browser-client/test_scenarios.json），选择器匹配式绑定将全量落空回退、对演示缺陷类零效果。
- 视图快照归因：assertions 的 not visible 失败分支采集轻量 DOM 摘要（当前可见视图 id、目标元素所在视图、可见性判定依据），附入失败载荷；不上截图。

## 取舍

- 不做全量 per-step：流程级断言（no_console_error 等）语义横贯全程，per-step 求值会破坏其语义且放大开销——保持后置。
- 不纳入条目建议②（judge 修复轮批量修复断言落点）：属 judge 行为面而非 runner 结构面，且引擎侧修复后逐场景补丁需求自然消失。
- 交互断言绑定「目标元素可见的最后步骤完成点」而非步骤中间态，避免步骤后续副作用未落时误判。
- 执行纪律约定：交互断言在其求值窗口内失败 MUST NOT 中断后续步骤执行（与现状「断言失败不停步骤」一致），结果按断言声明序回填 assertion_results；流程级断言后置求值、断言失败取证截图触发条件（web_runner.py:459）与视觉对比时机均不变。